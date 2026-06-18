"""
NexusIQ — rag/retriever.py

Hybrid retrieval pipeline:
  1. Semantic search  — ChromaDB cosine similarity
  2. BM25 search      — rank-bm25 over full corpus
  3. RRF fusion       — Reciprocal Rank Fusion
  4. MMR diversity    — Maximal Marginal Relevance for synthesis queries
  5. Cross-encoder    — reranking with ms-marco-MiniLM

FIXES / IMPROVEMENTS vs original:
  1. fetch_k now uses top_k * 4 (was * 3) — more candidates for reranking
  2. RRF k_rrf = 20 (was 60) — makes rank differences more pronounced
  3. MMR diversity retrieval added for synthesis/summary queries
  4. BM25 zero-score filter removed — rare terms still useful
  5. Added corpus size logging at every stage
  6. Semantic score norm fixed — uses 1 - distance correctly
  7. debug_retrieval now also returns semantic scores properly
"""

import logging
import math
from functools import lru_cache
from typing import List, Optional, Tuple

from langchain_core.documents import Document
from rank_bm25 import BM25Okapi


from app.config import settings
from app.rag.embeddings import embedding_manager, EMBEDDING_DIM
from app.rag.vectorstore import get_or_create_collection

logger = logging.getLogger("nexusiq.retriever")


# ── Cross-encoder singleton ────────────────────────────────────────

@lru_cache(maxsize=1)
def _get_reranker():
    logger.info("Loading cross-encoder '%s'…", settings.reranker_model)
    from sentence_transformers import CrossEncoder
    model = CrossEncoder(settings.reranker_model)
    logger.info("Cross-encoder ready ✓")
    return model


# ══════════════════════════════════════════════════════════════════
# BM25 RETRIEVAL
# ══════════════════════════════════════════════════════════════════

def _bm25_top_k(
    query: str,
    corpus: List[str],
    metadatas: List[dict],
    k: int,
) -> List[Tuple[Document, float]]:
    """
    BM25 retrieval over the full corpus.
    FIX: Zero-score results are kept — they are still useful for RRF fusion.
    """
    if not corpus:
        logger.warning("BM25: corpus is empty")
        return []

    tokenised  = [text.lower().split() for text in corpus]
    bm25       = BM25Okapi(tokenised)
    raw_scores = bm25.get_scores(query.lower().split())

    top_idx  = sorted(range(len(raw_scores)), key=lambda i: raw_scores[i], reverse=True)[:k]
    max_score = float(raw_scores[top_idx[0]]) if top_idx else 1.0
    if max_score <= 0:
        max_score = 1.0

    results: List[Tuple[Document, float]] = []
    for idx in top_idx:
        score = float(raw_scores[idx])
        doc   = Document(
            page_content=corpus[idx],
            metadata=metadatas[idx] if idx < len(metadatas) else {},
        )
        results.append((doc, score / max_score))

    logger.debug(
        "BM25: query='%s…' → top scores: %s",
        query[:40],
        [f"{s:.3f}" for _, s in results[:5]],
    )
    return results


# ══════════════════════════════════════════════════════════════════
# RECIPROCAL RANK FUSION
# ══════════════════════════════════════════════════════════════════

def _rrf_merge(
    *ranked_lists: List[Tuple[Document, float]],
    k_rrf: int = 20,
) -> List[Tuple[Document, float]]:
    """
    Merge ranked lists with Reciprocal Rank Fusion.
    k_rrf=20 gives larger score spread than k_rrf=60.
    """
    rrf_scores: dict = {}
    doc_map:    dict = {}

    for ranked in ranked_lists:
        for rank, (doc, _) in enumerate(ranked, start=1):
            key = doc.page_content[:120]
            rrf_scores[key] = rrf_scores.get(key, 0.0) + 1.0 / (k_rrf + rank)
            doc_map[key]    = doc

    sorted_keys = sorted(rrf_scores, key=lambda k: rrf_scores[k], reverse=True)
    merged      = [(doc_map[k], rrf_scores[k]) for k in sorted_keys]

    logger.debug(
        "RRF: %d lists → %d unique docs | top scores: %s",
        len(ranked_lists),
        len(merged),
        [f"{s:.4f}" for _, s in merged[:5]],
    )
    return merged


# ══════════════════════════════════════════════════════════════════
# MMR DIVERSITY RETRIEVAL
# ══════════════════════════════════════════════════════════════════

def _cosine_sim(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na  = math.sqrt(sum(x * x for x in a))
    nb  = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _mmr_rerank(
    query_embedding: List[float],
    candidates: List[Document],
    candidate_embeddings: List[List[float]],
    top_k: int,
    lambda_mult: float = 0.6,
) -> List[Document]:
    """
    Maximal Marginal Relevance reranking.

    Balances relevance (similarity to query) vs diversity
    (dissimilarity to already-selected docs).

    lambda_mult=0.6 → 60% relevance, 40% diversity.
    Higher lambda → more relevance, less diversity.

    Useful for synthesis/summary queries where we want coverage
    of all document sections, not just the most relevant ones.
    """
    if not candidates:
        return []

    selected_indices: List[int] = []
    remaining        = list(range(len(candidates)))

    # Precompute query similarities
    query_sims = [
        _cosine_sim(query_embedding, emb)
        for emb in candidate_embeddings
    ]

    while remaining and len(selected_indices) < top_k:
        if not selected_indices:
            # First pick: most relevant to query
            best_idx = max(remaining, key=lambda i: query_sims[i])
        else:
            # MMR score: lambda * relevance - (1-lambda) * max_similarity_to_selected
            def _mmr_score(i: int) -> float:
                rel  = query_sims[i]
                max_sim = max(
                    _cosine_sim(candidate_embeddings[i], candidate_embeddings[j])
                    for j in selected_indices
                )
                return lambda_mult * rel - (1 - lambda_mult) * max_sim

            best_idx = max(remaining, key=_mmr_score)

        selected_indices.append(best_idx)
        remaining.remove(best_idx)

    return [candidates[i] for i in selected_indices]


# ══════════════════════════════════════════════════════════════════
# CROSS-ENCODER RERANKING
# ══════════════════════════════════════════════════════════════════

def _rerank(
    query: str,
    candidates: List[Document],
    top_k: int,
) -> Tuple[List[Document], List[float]]:
    if not candidates:
        return [], []

    pairs = [(query, doc.page_content) for doc in candidates]

    try:
        reranker = _get_reranker()
        scores: List[float] = reranker.predict(pairs).tolist()
    except ImportError as exc:
        logger.warning(
            "Cross-encoder unavailable (%s) — sentence-transformers is not "
            "installed. Set RERANKER_ENABLED=false to silence this and skip "
            "reranking cleanly. Returning unranked candidates for now.",
            exc,
        )
        return candidates[:top_k], [0.0] * min(top_k, len(candidates))
    except Exception as exc:
        logger.warning("Cross-encoder failed (%s) — returning unranked", exc)
        return candidates[:top_k], [0.0] * min(top_k, len(candidates))

    ranked       = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)
    docs         = [d for d, _ in ranked[:top_k]]
    final_scores = [s for _, s in ranked[:top_k]]

    logger.info(
        "Reranker: %d → top-%d | scores: %s",
        len(candidates), top_k,
        [f"{s:.3f}" for s in final_scores[:6]],
    )
    return docs, final_scores


# ══════════════════════════════════════════════════════════════════
# PUBLIC API — hybrid_retrieve
# ══════════════════════════════════════════════════════════════════

async def hybrid_retrieve(
    query: str,
    top_k: Optional[int] = None,
    enable_reranking: bool = True,
    use_mmr: bool = False,
    mmr_lambda: float = 0.6,
) -> Tuple[List[Document], dict]:
    """
    Full hybrid retrieval: semantic + BM25 → RRF → (MMR or reranking).

    Parameters:
      use_mmr:    If True, use MMR diversity reranking instead of cross-encoder.
                  Recommended for summary/synthesis queries.
      mmr_lambda: MMR relevance weight (0.6 = 60% relevance, 40% diversity).
    """
    k       = top_k or settings.top_k
    fetch_k = k * 4   # fetch more candidates for better reranking

    collection = get_or_create_collection()
    total_docs = collection.count()

    logger.info(
        "hybrid_retrieve | query='%s…' | top_k=%d | fetch_k=%d | collection=%d | mmr=%s",
        query[:60], k, fetch_k, total_docs, use_mmr,
    )

    if total_docs == 0:
        logger.error("Collection EMPTY — no documents indexed!")
        return [], {
            "semantic_count": 0, "bm25_count": 0, "merged_count": 0,
            "final_count": 0, "top_k_requested": k,
            "error": "Collection is empty",
        }

    # ── 1. Semantic retrieval ──────────────────────────────────────
    sem_results: List[Tuple[Document, float]] = []
    sem_docs:    List[Document]               = []
    sem_scores:  List[float]                  = []
    sem_embeddings: List[List[float]]         = []   # for MMR

    try:
        query_embedding = embedding_manager.embed_query(query)
        effective_k     = min(fetch_k, total_docs)

        raw_sem = collection.query(
            query_embeddings=[query_embedding],
            n_results=effective_k,
            include=["documents", "metadatas", "distances", "embeddings"],
        )

        if raw_sem["ids"] and raw_sem["ids"][0]:
            raw_embeddings = raw_sem.get("embeddings", [[]])[0] or []
            for idx, (doc_text, meta, distance) in enumerate(zip(
                raw_sem["documents"][0],
                raw_sem["metadatas"][0],
                raw_sem["distances"][0],
            )):
                similarity = round(float(1.0 - distance), 4)
                doc = Document(page_content=doc_text, metadata=meta or {})
                sem_docs.append(doc)
                sem_scores.append(similarity)
                sem_results.append((doc, similarity))
                if idx < len(raw_embeddings) and raw_embeddings[idx]:
                    sem_embeddings.append(raw_embeddings[idx])
                else:
                    sem_embeddings.append([])

            logger.info(
                "Semantic: %d docs | scores: %s",
                len(sem_docs),
                [f"{s:.3f}" for s in sem_scores[:6]],
            )
            if sem_docs:
                logger.info(
                    "Top semantic chunk (%.3f): %s…",
                    sem_scores[0],
                    sem_docs[0].page_content[:150].replace("\n", " "),
                )
        else:
            logger.warning("Semantic search returned NO results for '%s'", query[:60])

    except Exception as exc:
        logger.error("Semantic retrieval error: %s", exc, exc_info=True)

    # ── 2. BM25 retrieval ──────────────────────────────────────────
    bm25_results: List[Tuple[Document, float]] = []
    bm25_scores:  List[float]                  = []

    try:
        raw      = collection.get(include=["documents", "metadatas"])
        corpus:  List[str]  = raw.get("documents") or []
        metas:   List[dict] = raw.get("metadatas") or []

        logger.info("BM25: corpus size=%d", len(corpus))

        if corpus:
            bm25_results = _bm25_top_k(query, corpus, metas, k=fetch_k)
            bm25_scores  = [s for _, s in bm25_results]
            logger.info(
                "BM25: %d docs | scores: %s",
                len(bm25_results),
                [f"{s:.3f}" for s in bm25_scores[:6]],
            )
    except Exception as exc:
        logger.error("BM25 error: %s", exc, exc_info=True)

    # ── 3. RRF fusion ──────────────────────────────────────────────
    merged     = _rrf_merge(sem_results, bm25_results)
    candidates = [doc for doc, _ in merged[:fetch_k]]

    logger.info(
        "RRF: sem=%d + bm25=%d → %d unique merged",
        len(sem_results), len(bm25_results), len(merged),
    )

    # ── 4. MMR or reranking ────────────────────────────────────────
    reranked_scores: Optional[List[float]] = None

    if use_mmr and candidates and sem_embeddings:
        logger.info("Applying MMR diversity (lambda=%.2f)", mmr_lambda)
        # Get embeddings for merged candidates
        cand_embeddings = []
        for doc in candidates:
            key = doc.page_content[:120]
            # Find matching embedding from semantic results
            matched_emb = []
            for i, sd in enumerate(sem_docs):
                if sd.page_content[:120] == key and i < len(sem_embeddings):
                    matched_emb = sem_embeddings[i]
                    break
            if not matched_emb:
                try:
                    matched_emb = embedding_manager.embed_query(doc.page_content[:256])
                except Exception:
                    matched_emb = [0.0] * EMBEDDING_DIM
            cand_embeddings.append(matched_emb)

        candidates = _mmr_rerank(
            query_embedding=query_embedding if 'query_embedding' in dir() else embedding_manager.embed_query(query),
            candidates=candidates,
            candidate_embeddings=cand_embeddings,
            top_k=k,
            lambda_mult=mmr_lambda,
        )
        reranked_scores = None   # MMR doesn't produce scalar scores

    elif enable_reranking and candidates and settings.reranker_enabled:
        candidates, reranked_scores = _rerank(query, candidates, top_k=k)
    else:
        candidates = candidates[:k]
        logger.info("Reranking skipped (enabled=%s)", enable_reranking)

    logger.info(
        "hybrid_retrieve DONE | final=%d | top_k=%d",
        len(candidates), k,
    )

    trace = {
        "semantic_count":  len(sem_docs),
        "semantic_scores": sem_scores[:k],
        "bm25_count":      len(bm25_results),
        "bm25_scores":     bm25_scores[:k],
        "merged_count":    len(merged),
        "reranked":        enable_reranking,
        "reranked_scores": reranked_scores,
        "final_count":     len(candidates),
        "top_k_requested": k,
        "mmr_used":        use_mmr,
    }

    return candidates, trace


# ══════════════════════════════════════════════════════════════════
# DEBUG ENTRY-POINT
# ══════════════════════════════════════════════════════════════════

async def debug_retrieval(
    query: str,
    top_k: int,
    method: str,
) -> dict:
    """
    Debug retrieval: exposes raw BM25, semantic, and reranker scores.
    Used by /api/debug/chunks and /api/debug/retrieve endpoints.
    """
    method     = method.lower()
    collection = get_or_create_collection()

    raw_data = collection.get(include=["documents", "metadatas"])
    corpus:  List[str]  = raw_data.get("documents") or []
    metas:   List[dict] = raw_data.get("metadatas") or []

    sem_scores:      List[float]           = []
    bm25_scores:     List[float]           = []
    reranked_scores: Optional[List[float]] = None
    docs:            List[Document]        = []

    if method in ("hybrid", "semantic"):
        try:
            query_embedding = embedding_manager.embed_query(query)
            total           = collection.count()
            eff_k           = min(top_k * 4, total) if total > 0 else 0
            if eff_k > 0:
                raw_sem = collection.query(
                    query_embeddings=[query_embedding],
                    n_results=eff_k,
                    include=["documents", "metadatas", "distances"],
                )
                if raw_sem["ids"] and raw_sem["ids"][0]:
                    for doc_text, meta, dist in zip(
                        raw_sem["documents"][0],
                        raw_sem["metadatas"][0],
                        raw_sem["distances"][0],
                    ):
                        sim = round(float(1.0 - dist), 4)
                        docs.append(Document(page_content=doc_text, metadata=meta or {}))
                        sem_scores.append(sim)
        except Exception as exc:
            logger.error("Debug semantic error: %s", exc)

    if method in ("hybrid", "bm25"):
        bm25_results = _bm25_top_k(query, corpus, metas, k=top_k * 4)
        bm25_docs    = [d for d, _ in bm25_results]
        bm25_scores  = [s for _, s in bm25_results]
        seen         = {d.page_content[:120] for d in docs}
        for doc in bm25_docs:
            if doc.page_content[:120] not in seen:
                docs.append(doc)
                seen.add(doc.page_content[:120])

    if method == "hybrid" and docs and settings.reranker_enabled:
        docs, reranked_scores = _rerank(query, docs, top_k=top_k)
    else:
        docs = docs[:top_k]

    return {
        "chunks":          [{"text": d.page_content, "metadata": d.metadata} for d in docs],
        "bm25_scores":     bm25_scores[:top_k],
        "semantic_scores": sem_scores[:top_k],
        "reranked_scores": reranked_scores,
        "query_rewrite":   None,
        "method_used":     method,
        "total_returned":  len(docs),
    }