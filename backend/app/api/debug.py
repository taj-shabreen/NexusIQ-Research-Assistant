"""
NexusIQ — api/debug.py

FastAPI router: retrieval introspection and debugging
  GET  /api/debug/health           — backend health: model, chroma, groq key status
  GET  /api/debug/stats            — collection stats: doc count, chunk count
  POST /api/debug/retrieve         — test retrieval: return chunks for a query
  POST /api/debug/chunks           — (original) full chunk debug with all scores
  GET  /api/debug/collection-stats — (original) ChromaDB collection info
  GET  /api/debug/documents/{id}   — (original) per-document chunk breakdown
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.rag.retriever import debug_retrieval
from app.rag.vectorstore import get_or_create_collection

logger = logging.getLogger("nexusiq.api.debug")
router = APIRouter()


# ══════════════════════════════════════════════════════════════════
# NEW ENDPOINTS — required by frontend DebugPage
# ══════════════════════════════════════════════════════════════════

class HealthResponse(BaseModel):
    status:          str
    model:           str
    embed_model:     str
    groq_key_set:    bool
    chroma_collection: str
    chunks_stored:   int
    env:             str


class StatsResponse(BaseModel):
    total_chunks:    int
    total_documents: int
    collection_name: str
    persist_dir:     str
    embed_model:     str


class RetrieveRequest(BaseModel):
    query:  str = Field(..., min_length=1, max_length=1000)
    top_k:  int = Field(default=6, ge=1, le=30)
    method: str = Field(default="hybrid")


class RetrieveChunk(BaseModel):
    rank:     int
    source:   str
    page:     int
    score:    Optional[float] = None
    preview:  str


class RetrieveResponse(BaseModel):
    query:          str
    method:         str
    total_returned: int
    chunks:         List[RetrieveChunk]


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Backend health — model name, chroma status, Groq key configured",
)
async def health() -> HealthResponse:
    """
    Quick health check for the DebugPage frontend panel.
    Shows whether Groq API key is set, which model is loaded,
    which embedding model, and how many chunks are in ChromaDB.
    """
    from app.config import settings

    try:
        collection    = get_or_create_collection()
        chunks_stored = collection.count()
    except Exception:
        chunks_stored = -1

    return HealthResponse(
        status=           "ok",
        model=            settings.groq_model,
        embed_model=      settings.embedding_model,
        groq_key_set=     bool(settings.groq_api_key and len(settings.groq_api_key) > 10),
        chroma_collection=settings.chroma_collection,
        chunks_stored=    chunks_stored,
        env=              settings.app_env,
    )


@router.get(
    "/stats",
    response_model=StatsResponse,
    summary="Collection stats — document count and chunk count",
)
async def stats() -> StatsResponse:
    """
    Returns document and chunk counts from ChromaDB.
    Used by the DebugPage Stats panel.
    """
    from app.config import settings

    try:
        collection    = get_or_create_collection()
        total_chunks  = collection.count()

        # Count unique documents by distinct document_id in metadata
        raw       = collection.get(include=["metadatas"])
        metas     = raw.get("metadatas") or []
        doc_ids   = {m.get("document_id", "") for m in metas if m.get("document_id")}
        total_docs = len(doc_ids)
    except Exception as exc:
        logger.error("Stats error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not retrieve stats: {exc}",
        ) from exc

    return StatsResponse(
        total_chunks=    total_chunks,
        total_documents= total_docs,
        collection_name= settings.chroma_collection,
        persist_dir=     settings.chroma_persist_dir,
        embed_model=     settings.embedding_model,
    )


@router.post(
    "/retrieve",
    response_model=RetrieveResponse,
    summary="Test retrieval — return top-k chunks for a query",
)
async def retrieve(request: RetrieveRequest) -> RetrieveResponse:
    """
    Test hybrid retrieval for a given query and return the top-k chunks.
    Used by the DebugPage Retrieval Tester panel.

    Each returned chunk includes:
      - rank: position in result list
      - source: filename
      - page: page number (1-indexed)
      - score: reranker score if available
      - preview: first 300 chars of chunk text
    """
    logger.info(
        "Debug retrieve | query='%s…' | top_k=%d | method=%s",
        request.query[:60], request.top_k, request.method,
    )

    try:
        raw = await debug_retrieval(
            query=request.query,
            top_k=request.top_k,
            method=request.method.lower(),
        )
    except Exception as exc:
        logger.error("Debug retrieval error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Retrieval failed: {exc}",
        ) from exc

    raw_chunks      = raw.get("chunks", [])
    reranked_scores = raw.get("reranked_scores") or []
    semantic_scores = raw.get("semantic_scores") or []

    chunks: List[RetrieveChunk] = []
    for i, c in enumerate(raw_chunks):
        meta     = c.get("metadata", {})
        filename = meta.get("filename", meta.get("doc_filename", "unknown"))
        page_raw = meta.get("page", 0)
        page     = int(page_raw) + 1 if isinstance(page_raw, (int, float)) else 1

        # Best available score: reranked > semantic > None
        score: Optional[float] = None
        if i < len(reranked_scores) and reranked_scores[i] is not None:
            score = round(float(reranked_scores[i]), 4)
        elif i < len(semantic_scores) and semantic_scores[i] is not None:
            score = round(float(semantic_scores[i]), 4)

        chunks.append(RetrieveChunk(
            rank=    i + 1,
            source=  filename,
            page=    page,
            score=   score,
            preview= c.get("text", "")[:300],
        ))

    return RetrieveResponse(
        query=          request.query,
        method=         request.method,
        total_returned= len(chunks),
        chunks=         chunks,
    )


# ══════════════════════════════════════════════════════════════════
# ORIGINAL ENDPOINTS — kept for backward compatibility
# ══════════════════════════════════════════════════════════════════

class ChunkDebugRequest(BaseModel):
    query:  str = Field(..., min_length=1, max_length=1000)
    top_k:  int = Field(default=10, ge=1, le=50)
    method: str = Field(default="hybrid")

    def model_post_init(self, __context: Any) -> None:
        allowed = {"hybrid", "semantic", "bm25"}
        if self.method.lower() not in allowed:
            raise ValueError(f"method must be one of {allowed}")
        self.method = self.method.lower()


class ChunkInfo(BaseModel):
    text:           str
    metadata:       Dict             = Field(default_factory=dict)
    bm25_score:     Optional[float]  = None
    semantic_score: Optional[float]  = None
    reranked_score: Optional[float]  = None


class ChunkDebugResponse(BaseModel):
    chunks:          List[ChunkInfo]
    bm25_scores:     List[float]           = Field(default_factory=list)
    semantic_scores: List[float]           = Field(default_factory=list)
    reranked_scores: Optional[List[float]] = None
    query_rewrite:   Optional[str]         = None
    method_used:     str                   = "hybrid"
    total_returned:  int                   = 0


class CollectionStats(BaseModel):
    collection:   str
    total_chunks: int
    persist_dir:  str
    status:       str


class DocumentChunkInfo(BaseModel):
    document_id:  str
    filename:     str
    total_chunks: int
    chunks:       List[Dict[str, Any]]


@router.post(
    "/chunks",
    response_model=ChunkDebugResponse,
    status_code=status.HTTP_200_OK,
    summary="Full chunk debug — BM25/semantic/reranker scores",
)
async def debug_chunks(request: ChunkDebugRequest) -> ChunkDebugResponse:
    logger.info(
        "Debug chunks | query='%.60s' | top_k=%d | method=%s",
        request.query, request.top_k, request.method,
    )
    try:
        raw = await debug_retrieval(
            query=request.query,
            top_k=request.top_k,
            method=request.method,
        )
    except Exception as exc:
        logger.error("Debug retrieval failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Retrieval failed: {exc}",
        ) from exc

    raw_chunks      = raw.get("chunks", [])
    bm25_scores     = raw.get("bm25_scores", [])
    semantic_scores = raw.get("semantic_scores", [])
    reranked_scores = raw.get("reranked_scores")

    chunks: List[ChunkInfo] = []
    for i, c in enumerate(raw_chunks):
        chunks.append(ChunkInfo(
            text=           c.get("text", ""),
            metadata=       c.get("metadata", {}),
            bm25_score=     bm25_scores[i]     if i < len(bm25_scores)     else None,
            semantic_score= semantic_scores[i]  if i < len(semantic_scores) else None,
            reranked_score= reranked_scores[i]  if reranked_scores and i < len(reranked_scores) else None,
        ))

    return ChunkDebugResponse(
        chunks=          chunks,
        bm25_scores=     bm25_scores,
        semantic_scores= semantic_scores,
        reranked_scores= reranked_scores,
        query_rewrite=   raw.get("query_rewrite"),
        method_used=     request.method,
        total_returned=  len(chunks),
    )


@router.get(
    "/collection-stats",
    response_model=CollectionStats,
    summary="ChromaDB collection statistics",
)
async def collection_stats() -> CollectionStats:
    from app.config import settings as cfg
    try:
        collection = get_or_create_collection()
        count      = collection.count()
    except Exception as exc:
        logger.error("Collection stats error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not retrieve collection statistics.",
        ) from exc

    return CollectionStats(
        collection=  cfg.chroma_collection,
        total_chunks=count,
        persist_dir= cfg.chroma_persist_dir,
        status=      "ok",
    )


@router.get(
    "/documents/{document_id}",
    response_model=DocumentChunkInfo,
    summary="Inspect all chunks for a specific document",
)
async def document_chunks(
    document_id: str,
    page: Optional[int] = Query(default=None, ge=1),
) -> DocumentChunkInfo:
    collection   = get_or_create_collection()
    where_filter: dict = {"document_id": document_id}
    if page is not None:
        where_filter["page"] = page - 1

    try:
        result = collection.get(
            where=where_filter,
            include=["documents", "metadatas"],
        )
    except Exception as exc:
        logger.error("Document chunks error for '%s': %s", document_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not retrieve document chunks.",
        ) from exc

    texts: List[str]  = result.get("documents") or []
    metas: List[dict] = result.get("metadatas") or []

    if not texts:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No chunks found for document_id='{document_id}'.",
        )

    filename = metas[0].get("filename", "unknown") if metas else "unknown"
    chunks   = [
        {
            "chunk_index": m.get("chunk_index", i),
            "page":        m.get("page", 0) + 1,
            "char_count":  m.get("char_count", len(t)),
            "text_preview": t[:300],
        }
        for i, (t, m) in enumerate(zip(texts, metas))
    ]

    return DocumentChunkInfo(
        document_id= document_id,
        filename=    filename,
        total_chunks=len(chunks),
        chunks=      chunks,
    )