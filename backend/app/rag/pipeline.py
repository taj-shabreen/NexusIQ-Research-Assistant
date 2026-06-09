"""
NexusIQ — rag/pipeline.py

Production-grade RAG pipeline with intelligent query-type routing
and strict token budget management.

═══════════════════════════════════════════════════════════════════
ROOT CAUSES OF 413 TOKEN OVERFLOW — FIXED IN THIS VERSION
═══════════════════════════════════════════════════════════════════

BUG 1 (PRIMARY): _build_context() used max_chars=14000
  14000 chars ÷ 4 ≈ 3500 context tokens.
  _llm_writer had max_tokens=4096.
  3500 + 4096 = 7596 total → exceeds Groq's ~6000 combined limit → 413.
  FIX: Token budget system. Reserve tokens for system prompt + answer.
       Context chars = (budget_tokens - reserved) × CHARS_PER_TOKEN.

BUG 2: _map_reduce_summarize() passed combined[:12000] to reduce LLM
  12000 chars ÷ 4 = 3000 tokens input.
  max_tokens=4096 output requested.
  3000 + 4096 = 7096 → overflow.
  FIX: Map LLM max_tokens=800 (bullet summaries don't need more).
       Reduce LLM max_tokens=1500.
       Reduce input capped at 6000 chars (1500 tokens).

BUG 3: _llm_writer max_tokens=4096 hardcoded
  Caused overflow when combined with any large context.
  FIX: Dynamic max_tokens computed per-query from remaining budget.

BUG 4: REVISION_NOTES/INTERVIEW_GUIDE without filename
  hybrid_retrieve(top_k=20) misses topic-diverse chunks because
  BM25+semantic scores generic "revision notes" query poorly.
  Chunks about Strategy, Adapter, Composite, OCL all missed.
  FIX: Synthesis queries retrieve ALL chunks from collection
       (sorted by page), then token-budget trims to fit.

BUG 5: MAP groups chunk[:3000] but map LLM max_tokens=4096
  Even map phase could overflow with verbose system prompt.
  FIX: Map LLM max_tokens=800, chunk input capped at 2000 chars.

═══════════════════════════════════════════════════════════════════
TOKEN BUDGET CONSTANTS
═══════════════════════════════════════════════════════════════════

Groq llama-3.1-8b-instant limits:
  Context window:  8192 tokens
  Max output:      8192 tokens
  Combined budget: ~6000 tokens (conservative safe limit)

Budget allocation:
  SYSTEM_PROMPT_TOKENS = 400   (reserved for system prompt)
  ANSWER_TOKENS        = 1800  (reserved for answer generation)
  CONTEXT_BUDGET       = 6000 - 400 - 1800 = 3800 tokens
  CHARS_PER_TOKEN      = 3.5   (conservative; English text ~4, code ~3)
  MAX_CONTEXT_CHARS    = 3800 × 3.5 = 13300 chars → use 12000 for safety

For synthesis queries (revision notes, interview guide):
  These need richer answers → reduce context, increase answer budget:
  ANSWER_TOKENS        = 2500
  CONTEXT_BUDGET       = 6000 - 400 - 2500 = 3100 tokens
  MAX_CONTEXT_CHARS    = 3100 × 3.5 = 10850 → use 9000 for safety
"""

import asyncio
import logging
import math
import re
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq

from app.config import settings
from app.observability.langsmith_tracer import traced
from app.rag.retriever import hybrid_retrieve

logger = logging.getLogger("nexusiq.pipeline")

# ── Strict no-answer ───────────────────────────────────────────────
_NO_ANSWER = "The uploaded documents do not contain enough information to answer this."
_MIN_CONFIDENCE_THRESHOLD = 0.25

# ── Token budget constants ─────────────────────────────────────────
_GROQ_SAFE_COMBINED  = 6000   # conservative combined input+output limit
_SYSTEM_PROMPT_TOKS  = 400    # reserved for system prompt
_CHARS_PER_TOKEN     = 3.5    # chars per token (conservative)

# Per query-type answer token budget
_ANSWER_TOKENS: Dict[str, int] = {
    "factual_qa":      1200,
    "summary":         1800,
    "revision_notes":  2200,
    "interview_guide": 2200,
    "table":           1400,
    "conclusion":      1400,
    "long_synthesis":  2000,
}

# Map-reduce specific token limits
_MAP_CHUNK_GROUP_SIZE  = 4     # chunks per map group (reduced from 5)
_MAP_MAX_INPUT_CHARS   = 2000  # per map group input (≈570 tokens)
_MAP_MAX_OUTPUT_TOKENS = 600   # map LLM answer budget
_REDUCE_MAX_INPUT_CHARS = 5500 # combined map summaries (≈1570 tokens)
_REDUCE_MAX_OUTPUT_TOKENS = 1500  # reduce LLM answer budget


def _context_char_budget(qt_value: str) -> int:
    """
    Compute max context chars for a query type based on token budget.
    context_tokens = GROQ_SAFE - SYSTEM_PROMPT - ANSWER_TOKENS
    context_chars  = context_tokens × CHARS_PER_TOKEN
    Apply 15% safety margin.
    """
    answer_toks   = _ANSWER_TOKENS.get(qt_value, 1200)
    context_toks  = _GROQ_SAFE_COMBINED - _SYSTEM_PROMPT_TOKS - answer_toks
    context_chars = int(context_toks * _CHARS_PER_TOKEN * 0.85)   # 15% safety
    logger.debug(
        "Token budget | qt=%s | answer=%d | ctx_toks=%d | ctx_chars=%d",
        qt_value, answer_toks, context_toks, context_chars,
    )
    return max(context_chars, 2000)   # minimum 2000 chars always


def _answer_max_tokens(qt_value: str) -> int:
    """Return the max_tokens to request from the LLM for this query type."""
    return _ANSWER_TOKENS.get(qt_value, 1200)


# ══════════════════════════════════════════════════════════════════
# QUERY TYPE DETECTION
# ══════════════════════════════════════════════════════════════════

class QueryType(str, Enum):
    FACTUAL_QA      = "factual_qa"
    SUMMARY         = "summary"
    REVISION_NOTES  = "revision_notes"
    INTERVIEW_GUIDE = "interview_guide"
    TABLE           = "table"
    CONCLUSION      = "conclusion"
    LONG_SYNTHESIS  = "long_synthesis"


_QT_PATTERNS: List[Tuple[QueryType, List[str]]] = [
    (QueryType.SUMMARY, [
        r'\bsummar(y|ize|ise|ization)\b',
        r'\bbrief\s+(overview|description)\b',
        r'\bwhat\s+is\s+.{0,30}\s+about\b',
        r'\boverall\s+content\b',
        r'\bgive\s+me\s+(a\s+)?(brief|quick|short)\b',
        r'\bexplain\s+the\s+(entire|whole|full)\b',
    ]),
    (QueryType.REVISION_NOTES, [
        r'\brevision\s+note',
        r'\bstudy\s+(note|guide|material)',
        r'\bkey\s+(concept|point|idea|term|topic)',
        r'\bimportant\s+(concept|point|formula|term)',
        r'\bquick\s+revision\b',
        r'\bcheat\s+sheet\b',
        r'\bflash\s*card',
        r'\bmemorize\b',
        r'\bprep(are|aration)\s+(for\s+)?(exam|test|quiz)',
        r'\bexecutive[\s\-]level\b',
    ]),
    (QueryType.INTERVIEW_GUIDE, [
        r'\binterview\s+(question|guide|prep|preparation)',
        r'\bplacement\s+(guide|prep|ready|question)',
        r'\bcommonly?\s+asked\b',
        r'\bfrequently?\s+asked\b',
        r'\btop\s+\d+\s+question',
        r'\bpractice\s+question',
        r'\bjob\s+(interview|ready)',
        r'\bviva\b',
    ]),
    (QueryType.TABLE, [
        r'\b(create|make|generate|show|list)\s+(a\s+)?table\b',
        r'\bcompare\b.*\b(table|tabular|format)\b',
        r'\bdifference(s)?\s+between\b',
        r'\bcomparison\s+(of|between)\b',
        r'\bclassif(y|ication)\s+(in\s+)?table\b',
        r'\btabulate\b',
        r'\bside[- ]by[- ]side\b',
        r'\bversus\b',
        r'\bvs\.?\b',
        r'\bcontrast\b',
    ]),
    (QueryType.CONCLUSION, [
        r'\b(give|provide|write|generate)\s+(a\s+)?conclusion\b',
        r'\bfinal\s+(thought|insight|remark|summary)\b',
        r'\bconcluding\s+(remark|paragraph|section)\b',
        r'\bwrap\s*up\b',
        r'\bkey\s+takeaway',
        r'\bunit\s+\d+\s+conclusion\b',
    ]),
    (QueryType.LONG_SYNTHESIS, [
        r'\bexplain\s+(in\s+detail|thoroughly|comprehensively|everything)\b',
        r'\belaborate\b',
        r'\bin[- ]depth\s+(explanation|analysis|overview)',
        r'\bcomprehensive\s+(overview|explanation|analysis)',
        r'\bdetailed\s+(explanation|analysis|description)',
        r'\bfull\s+(explanation|analysis|description)',
        r'\ball\s+(about|aspects|topics)',
    ]),
]


def detect_query_type(question: str) -> QueryType:
    q_lower = question.lower()
    for qt, patterns in _QT_PATTERNS:
        for pat in patterns:
            if re.search(pat, q_lower):
                logger.info("QueryType: %s (pattern='%s')", qt.value, pat)
                return qt
    return QueryType.FACTUAL_QA


def detect_filename(question: str) -> Optional[str]:
    match = re.search(r'\b([\w\-]+\.pdf)\b', question, re.IGNORECASE)
    if match:
        fname = match.group(1)
        logger.info("Filename in query: '%s'", fname)
        return fname
    return None


def get_retrieval_params(qt: QueryType) -> Dict[str, Any]:
    """
    Retrieval parameters per query type.
    NOTE: top_k here is used ONLY as a fallback cap when full-collection
    retrieval is not possible. The actual number of chunks passed to the
    LLM is capped by the token budget in _build_context().
    """
    return {
        QueryType.FACTUAL_QA:      {"top_k": 6,  "fetch_k": 24, "enable_reranking": True,  "full_collection": False},
        QueryType.SUMMARY:         {"top_k": 40, "fetch_k": 80, "enable_reranking": False, "full_collection": True},
        QueryType.REVISION_NOTES:  {"top_k": 40, "fetch_k": 80, "enable_reranking": False, "full_collection": True},
        QueryType.INTERVIEW_GUIDE: {"top_k": 40, "fetch_k": 80, "enable_reranking": False, "full_collection": True},
        QueryType.TABLE:           {"top_k": 15, "fetch_k": 40, "enable_reranking": True,  "full_collection": False},
        QueryType.CONCLUSION:      {"top_k": 30, "fetch_k": 60, "enable_reranking": False, "full_collection": True},
        QueryType.LONG_SYNTHESIS:  {"top_k": 18, "fetch_k": 45, "enable_reranking": True,  "full_collection": False},
    }.get(qt, {"top_k": 6, "fetch_k": 24, "enable_reranking": True, "full_collection": False})


# ══════════════════════════════════════════════════════════════════
# LLM FACTORY — dynamic max_tokens
# ══════════════════════════════════════════════════════════════════

def _make_llm(temperature: float = 0.0, max_tokens: int = 1200) -> ChatGroq:
    return ChatGroq(
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        temperature=temperature,
        max_tokens=max_tokens,
    )


# Static LLMs for rewriting / sub-queries (small outputs)
_llm_precise  = _make_llm(temperature=0.0, max_tokens=256)
_llm_creative = _make_llm(temperature=0.3, max_tokens=256)

# Map LLM — small budget per group
_llm_map      = _make_llm(temperature=0.0, max_tokens=_MAP_MAX_OUTPUT_TOKENS)
# Reduce LLM — moderate budget for final synthesis
_llm_reduce   = _make_llm(temperature=0.1, max_tokens=_REDUCE_MAX_OUTPUT_TOKENS)


def _make_generation_llm(qt_value: str) -> ChatGroq:
    """Create a generation LLM with token budget appropriate for query type."""
    max_toks = _answer_max_tokens(qt_value)
    return _make_llm(temperature=0.1, max_tokens=max_toks)


# ══════════════════════════════════════════════════════════════════
# PROMPTS — one per query type
# ══════════════════════════════════════════════════════════════════

_BASE_SYSTEM_RULES = (
    "STRICT RULES:\n"
    "- Use ONLY the CONTEXT SECTIONS provided below.\n"
    "- NEVER use training data, world knowledge, or external sources.\n"
    "- If context does not contain enough information, say ONLY:\n"
    "  \"The uploaded documents do not contain enough information to answer this.\"\n"
    "- Cite sources as [filename, page N] inline.\n"
)

_PROMPT_FACTUAL_QA = ChatPromptTemplate.from_messages([
    ("system",
     "You are NexusIQ, a strict document-grounded research assistant.\n\n"
     + _BASE_SYSTEM_RULES),
    ("human",
     "CONTEXT:\n---\n{context}\n---\n\n"
     "HISTORY:\n{history}\n\n"
     "QUESTION: {question}\n\n"
     "ANSWER:"),
])

_PROMPT_SUMMARY = ChatPromptTemplate.from_messages([
    ("system",
     "You are NexusIQ, an expert document summarizer.\n\n"
     + _BASE_SYSTEM_RULES +
     "\nFORMAT:\n"
     "1. **Overview** — 2-3 sentence summary\n"
     "2. **Main Topics** — bullet list\n"
     "3. **Key Concepts** — important definitions\n"
     "4. **Key Takeaways** — 3-5 points\n"
     "Be concise. Cover breadth over depth."),
    ("human",
     "DOCUMENT CONTENT:\n---\n{context}\n---\n\n"
     "REQUEST: {question}\n\nSUMMARY:"),
])

_PROMPT_REVISION_NOTES = ChatPromptTemplate.from_messages([
    ("system",
     "You are NexusIQ, an expert study notes generator.\n\n"
     + _BASE_SYSTEM_RULES +
     "\nFORMAT (be concise per section):\n"
     "## Key Concepts\n- concept: definition\n\n"
     "## Important Points\n- bullet facts\n\n"
     "## Patterns/Algorithms\n- formulas or pseudocode\n\n"
     "## Common Mistakes\n- pitfalls\n\n"
     "## Exam Questions (5 max)\n1. question\n\n"
     "Keep each section SHORT. Cover ALL topics in the document."),
    ("human",
     "DOCUMENT CONTENT:\n---\n{context}\n---\n\n"
     "REQUEST: {question}\n\nREVISION NOTES:"),
])

_PROMPT_INTERVIEW_GUIDE = ChatPromptTemplate.from_messages([
    ("system",
     "You are NexusIQ, an expert interview coach.\n\n"
     + _BASE_SYSTEM_RULES +
     "\nFORMAT (be concise):\n"
     "## Top Topics\n- topic list\n\n"
     "## Beginner Q&A (3 max)\n**Q:** ...\n**A:** ...\n\n"
     "## Intermediate Q&A (3 max)\n**Q:** ...\n**A:** ...\n\n"
     "## Advanced Questions (2 max)\n**Q:** ...\n\n"
     "## Quick Revision\n- one-liners\n\n"
     "Keep answers SHORT. Cover breadth."),
    ("human",
     "DOCUMENT CONTENT:\n---\n{context}\n---\n\n"
     "REQUEST: {question}\n\nINTERVIEW GUIDE:"),
])

_PROMPT_TABLE = ChatPromptTemplate.from_messages([
    ("system",
     "You are NexusIQ, an expert technical writer.\n\n"
     + _BASE_SYSTEM_RULES +
     "\nRULES:\n"
     "- ALWAYS produce a markdown table with | headers |\n"
     "- One row per item being compared\n"
     "- Brief intro sentence before table\n"
     "- Cite as [filename, page N] after table\n"
     "- NEVER use bullet points instead of a table."),
    ("human",
     "DOCUMENT CONTENT:\n---\n{context}\n---\n\n"
     "REQUEST: {question}\n\nMARKDOWN TABLE:"),
])

_PROMPT_CONCLUSION = ChatPromptTemplate.from_messages([
    ("system",
     "You are NexusIQ, an expert academic writer.\n\n"
     + _BASE_SYSTEM_RULES +
     "\nFORMAT:\n"
     "## Conclusion\n"
     "**Opening:** Main subject/purpose.\n"
     "**Key Findings:** Most important insights.\n"
     "**Significance:** Why this matters.\n"
     "**Final Remarks:** 1-2 sentence closing.\n"
     "Academic style. Cite [filename, page N]."),
    ("human",
     "DOCUMENT CONTENT:\n---\n{context}\n---\n\n"
     "REQUEST: {question}\n\nCONCLUSION:"),
])

_PROMPT_LONG_SYNTHESIS = ChatPromptTemplate.from_messages([
    ("system",
     "You are NexusIQ, an expert technical explainer.\n\n"
     + _BASE_SYSTEM_RULES +
     "\nFORMAT:\n"
     "1. **Introduction**\n2. **Core Components**\n"
     "3. **How It Works**\n4. **Examples**\n"
     "5. **Summary**\n"
     "Use headers and bullets. Be thorough but concise."),
    ("human",
     "DOCUMENT CONTENT:\n---\n{context}\n---\n\n"
     "HISTORY:\n{history}\n\n"
     "REQUEST: {question}\n\nEXPLANATION:"),
])

_PROMPT_MAP = ChatPromptTemplate.from_messages([
    ("system",
     "Summarize this document excerpt in 3-4 bullet points. "
     "Extract key concepts, definitions, patterns. Be very concise. "
     "Use ONLY the provided text."),
    ("human", "EXCERPT:\n{chunk}\n\nKEY POINTS:"),
])

_PROMPT_REDUCE = ChatPromptTemplate.from_messages([
    ("system",
     "Combine these partial summaries into one comprehensive document summary.\n"
     "FORMAT:\n"
     "1. **Overview** (2 sentences)\n"
     "2. **Main Topics** (bullets)\n"
     "3. **Key Concepts** (brief definitions)\n"
     "4. **Key Takeaways** (3-4 points)\n"
     "Be concise. Do NOT add outside information."),
    ("human",
     "PARTIAL SUMMARIES:\n---\n{summaries}\n---\n\n"
     "REQUEST: {question}\n\nFINAL SUMMARY:"),
])

_REWRITE_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "Rewrite the user question for document retrieval. "
     "Keep all technical terms. Output ONLY the rewritten question."),
    ("human", "{question}"),
])

_MULTI_QUERY_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "Generate {n} diverse sub-questions covering different aspects. "
     "One per line. No numbering."),
    ("human", "{question}"),
])


def _get_prompt(qt: QueryType) -> ChatPromptTemplate:
    return {
        QueryType.FACTUAL_QA:      _PROMPT_FACTUAL_QA,
        QueryType.SUMMARY:         _PROMPT_SUMMARY,
        QueryType.REVISION_NOTES:  _PROMPT_REVISION_NOTES,
        QueryType.INTERVIEW_GUIDE: _PROMPT_INTERVIEW_GUIDE,
        QueryType.TABLE:           _PROMPT_TABLE,
        QueryType.CONCLUSION:      _PROMPT_CONCLUSION,
        QueryType.LONG_SYNTHESIS:  _PROMPT_LONG_SYNTHESIS,
    }.get(qt, _PROMPT_FACTUAL_QA)


# ══════════════════════════════════════════════════════════════════
# FILENAME-AWARE RETRIEVAL
# ══════════════════════════════════════════════════════════════════

async def _retrieve_by_filename(
    filename: str,
    query: str,
    top_k: int,
) -> List[Any]:
    """Semantic retrieval filtered to a specific document filename."""
    try:
        from app.rag.vectorstore import get_or_create_collection
        from app.rag.embeddings import embedding_manager
        from langchain_core.documents import Document

        collection      = get_or_create_collection()
        total           = collection.count()
        query_embedding = embedding_manager.embed_query(query)

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, max(total, 1)),
            where={"filename": filename},
            include=["documents", "metadatas", "distances"],
        )

        docs = []
        if results["ids"] and results["ids"][0]:
            for text, meta, _ in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            ):
                docs.append(Document(page_content=text, metadata=meta or {}))

        logger.info("Filename-filtered: '%s' → %d chunks", filename, len(docs))
        return docs
    except Exception as exc:
        logger.warning("Filename-filtered retrieval failed: %s", exc)
        return []


async def _retrieve_all_chunks_for_file(filename: str) -> List[Any]:
    """Retrieve ALL chunks for a file, sorted by chunk_index (page order)."""
    try:
        from app.rag.vectorstore import get_or_create_collection
        from langchain_core.documents import Document

        collection = get_or_create_collection()
        results    = collection.get(
            where={"filename": filename},
            include=["documents", "metadatas"],
        )

        docs = []
        if results.get("documents"):
            pairs = list(zip(
                results["documents"],
                results.get("metadatas", [{}] * len(results["documents"])),
            ))
            pairs.sort(key=lambda x: int(x[1].get("chunk_index", 0)))
            for text, meta in pairs:
                docs.append(Document(page_content=text, metadata=meta or {}))

        logger.info("All-chunk retrieval for '%s': %d chunks", filename, len(docs))
        return docs
    except Exception as exc:
        logger.warning("All-chunk retrieval failed: %s", exc)
        return []


async def _retrieve_all_chunks(limit: int = 200) -> List[Any]:
    """
    Retrieve ALL chunks from the collection, sorted by document + page order.
    Used for synthesis queries without a specific filename.
    This ensures no topic is missed by keyword/semantic scoring.
    """
    try:
        from app.rag.vectorstore import get_or_create_collection
        from langchain_core.documents import Document

        collection = get_or_create_collection()
        total      = collection.count()
        if total == 0:
            return []

        results = collection.get(
            include=["documents", "metadatas"],
            limit=min(total, limit),
        )

        docs = []
        if results.get("documents"):
            pairs = list(zip(
                results["documents"],
                results.get("metadatas", [{}] * len(results["documents"])),
            ))
            # Sort by filename + chunk_index so related content is contiguous
            pairs.sort(key=lambda x: (
                x[1].get("filename", ""),
                int(x[1].get("chunk_index", 0)),
            ))
            for text, meta in pairs:
                docs.append(Document(page_content=text, metadata=meta or {}))

        logger.info("Full-collection retrieval: %d/%d chunks", len(docs), total)
        return docs
    except Exception as exc:
        logger.warning("Full-collection retrieval failed: %s", exc)
        return []


# ══════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════════

async def _rewrite_query(question: str) -> str:
    try:
        chain     = _REWRITE_PROMPT | _llm_precise | StrOutputParser()
        rewritten = await chain.ainvoke({"question": question})
        rewritten = rewritten.strip().strip('"').strip("'")
        if rewritten and 3 < len(rewritten) < 500:
            logger.info("Rewrite: '%s' → '%s'", question[:50], rewritten[:50])
            return rewritten
        return question
    except Exception as exc:
        logger.warning("Rewrite failed: %s", exc)
        return question


async def _generate_sub_queries(question: str, n: int) -> List[str]:
    try:
        chain  = _MULTI_QUERY_PROMPT | _llm_creative | StrOutputParser()
        raw    = await chain.ainvoke({"question": question, "n": n})
        lines  = [l.strip().lstrip("•-–*0123456789.) ") for l in raw.splitlines() if l.strip()]
        valid  = [s for s in lines if len(s) > 5][:n]
        logger.info("Sub-queries: %s", valid)
        return valid
    except Exception as exc:
        logger.warning("Sub-query gen failed: %s", exc)
        return []


def _build_context(docs, qt_value: str = "factual_qa") -> str:
    """
    Build context string with STRICT token budget enforcement.

    FIX: max_chars now computed dynamically per query type using
    the token budget formula:
      context_chars = (GROQ_SAFE - SYSTEM_PROMPT_TOKS - ANSWER_TOKS) × CHARS_PER_TOKEN × 0.85

    This prevents 413 overflow regardless of chunk count or size.
    """
    if not docs:
        return ""

    max_chars = _context_char_budget(qt_value)
    blocks    = []
    total     = 0

    for i, doc in enumerate(docs, start=1):
        filename = doc.metadata.get("filename", "unknown")
        page     = int(doc.metadata.get("page", 0)) + 1
        content  = doc.page_content.strip()
        block    = f"[{i}] {filename} p.{page}\n{content}"

        if total + len(block) > max_chars:
            logger.info(
                "Context budget reached at chunk %d/%d | used=%d/%d chars | qt=%s",
                i - 1, len(docs), total, max_chars, qt_value,
            )
            break
        blocks.append(block)
        total += len(block) + 2   # +2 for separator

    context = "\n\n".join(blocks)
    logger.info(
        "Context built: %d/%d chunks | %d chars | budget=%d | qt=%s",
        len(blocks), len(docs), len(context), max_chars, qt_value,
    )
    return context


def _build_history_str(history: List[Dict[str, str]]) -> str:
    if not history:
        return "None"
    return "\n".join(
        f"{m.get('role','user').capitalize()}: {m.get('content','')[:200]}"
        for m in history[-4:]
    )


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _build_citations(docs, reranked_scores: Optional[List[float]] = None) -> List[Dict]:
    citations = []
    for i, doc in enumerate(docs):
        raw_score = float(reranked_scores[i]) if reranked_scores and i < len(reranked_scores) else 3.0
        relevance = round(_sigmoid(raw_score), 4)
        citations.append({
            "document_id":     doc.metadata.get("document_id", ""),
            "filename":        doc.metadata.get("filename", ""),
            "page":            int(doc.metadata.get("page", 0)) + 1,
            "chunk_text":      doc.page_content[:300],
            "relevance_score": min(max(relevance, 0.0), 1.0),
        })
    return citations


def _compute_confidence(
    docs,
    reranked_scores: Optional[List[float]],
    top_k: int,
) -> float:
    if not docs:
        return 0.0
    coverage = min(len(docs) / max(top_k, 1), 1.0)
    quality  = (
        sum(_sigmoid(s) for s in reranked_scores[:3]) / min(3, len(reranked_scores))
        if reranked_scores else 0.65
    )
    return round(min(max(0.4 * coverage + 0.6 * quality, 0.0), 1.0), 4)


def _is_context_too_weak(reranked_scores: Optional[List[float]]) -> bool:
    if not reranked_scores:
        return False
    best = max(_sigmoid(s) for s in reranked_scores)
    if best < _MIN_CONFIDENCE_THRESHOLD:
        logger.warning("Context weak: best_sigmoid=%.3f < %.2f", best, _MIN_CONFIDENCE_THRESHOLD)
        return True
    return False


# ══════════════════════════════════════════════════════════════════
# MAP-REDUCE SUMMARIZATION — with tight token budgets
# ══════════════════════════════════════════════════════════════════

async def _map_reduce_summarize(
    docs: List[Any],
    question: str,
) -> str:
    """
    Map-Reduce summarization with strict per-phase token limits.

    FIX: Each phase uses its own LLM instance with appropriate max_tokens.
      Map:    max_tokens=600  — bullet summaries, very concise
      Reduce: max_tokens=1500 — final synthesis, moderate length
      Input caps prevent overflow even with many groups.
    """
    if not docs:
        return _NO_ANSWER

    logger.info(
        "Map-reduce: %d chunks | group=%d | map_max_chars=%d | reduce_max_chars=%d",
        len(docs), _MAP_CHUNK_GROUP_SIZE,
        _MAP_MAX_INPUT_CHARS, _REDUCE_MAX_INPUT_CHARS,
    )

    # ── Map phase ─────────────────────────────────────────────────
    groups = [
        docs[i:i + _MAP_CHUNK_GROUP_SIZE]
        for i in range(0, len(docs), _MAP_CHUNK_GROUP_SIZE)
    ]

    map_chain       = _PROMPT_MAP | _llm_map | StrOutputParser()
    group_summaries = []

    for gi, group in enumerate(groups):
        chunk_text = "\n\n".join(
            f"[p.{int(d.metadata.get('page',0))+1}]: {d.page_content.strip()}"
            for d in group
        )
        # FIX: cap map input at _MAP_MAX_INPUT_CHARS to prevent token overflow
        chunk_text = chunk_text[:_MAP_MAX_INPUT_CHARS]
        try:
            summary = await map_chain.ainvoke({"chunk": chunk_text})
            group_summaries.append(summary.strip())
            logger.debug(
                "Map group %d/%d: in=%d chars out=%d chars",
                gi + 1, len(groups), len(chunk_text), len(summary),
            )
        except Exception as exc:
            logger.warning("Map group %d failed: %s", gi, exc)
            # Add a placeholder so topic coverage is maintained
            group_summaries.append(f"[Section {gi+1}: summary unavailable]")

    if not group_summaries or all("unavailable" in s for s in group_summaries):
        return _NO_ANSWER

    # ── Reduce phase ──────────────────────────────────────────────
    combined = "\n\n---\n\n".join(
        f"[Sec {i+1}]:\n{s}"
        for i, s in enumerate(group_summaries)
    )
    # FIX: cap reduce input at _REDUCE_MAX_INPUT_CHARS (was 12000 → now 5500)
    combined = combined[:_REDUCE_MAX_INPUT_CHARS]

    reduce_chain = _PROMPT_REDUCE | _llm_reduce | StrOutputParser()
    try:
        final = await reduce_chain.ainvoke({
            "summaries": combined,
            "question":  question,
        })
        return final.strip()
    except Exception as exc:
        logger.error("Reduce failed: %s — joining map summaries", exc)
        # Fallback: join the map summaries directly
        return "\n\n".join(
            f"**Section {i+1}:**\n{s}"
            for i, s in enumerate(group_summaries)
            if "unavailable" not in s
        )


# ══════════════════════════════════════════════════════════════════
# MAIN PIPELINE
# ══════════════════════════════════════════════════════════════════

@traced(name="rag_pipeline")
async def rag_pipeline(
    question: str,
    history: List[Any],
    top_k: Optional[int] = None,
    enable_reranking: bool = True,
    enable_multi_query: bool = False,
) -> Dict[str, Any]:
    """
    Intelligent RAG pipeline with query-type routing and token budgeting.

    Key behaviours:
    - Detects query type → selects retrieval strategy + prompt
    - Synthesis queries (revision/interview/summary/conclusion) retrieve
      ALL collection chunks sorted by page order to ensure full coverage
    - Token budget is computed per query type — never exceeds Groq limits
    - Map-reduce used for large documents to stay within token limits
    """
    logger.info("=" * 60)
    logger.info("RAG START | q='%s'", question[:80])

    # ── Step 1: Classify query ─────────────────────────────────────
    qt       = detect_query_type(question)
    filename = detect_filename(question)
    params   = get_retrieval_params(qt)

    effective_top_k     = top_k or params["top_k"]
    effective_reranking = enable_reranking and params["enable_reranking"]
    use_full_collection = params.get("full_collection", False)

    logger.info(
        "qt=%s | filename=%s | top_k=%d | full_coll=%s | reranking=%s",
        qt.value, filename, effective_top_k, use_full_collection, effective_reranking,
    )

    # ── Step 2: Query rewriting (factual only) ─────────────────────
    rewritten = await _rewrite_query(question) if qt == QueryType.FACTUAL_QA else question

    # ── Step 3: Sub-queries (factual only) ─────────────────────────
    sub_queries: List[str] = []
    if enable_multi_query and qt == QueryType.FACTUAL_QA:
        sub_queries = await _generate_sub_queries(rewritten, n=settings.multi_query_count)

    # ── Step 4: Retrieval ──────────────────────────────────────────
    all_docs:        List                  = []
    primary_trace:   Dict                  = {}
    reranked_scores: Optional[List[float]] = None

    # Path A: Summary with specific filename → get ALL chunks for that file
    if qt == QueryType.SUMMARY and filename:
        all_docs = await _retrieve_all_chunks_for_file(filename)
        primary_trace = {
            "semantic_count": len(all_docs), "bm25_count": 0,
            "merged_count": len(all_docs), "final_count": len(all_docs),
            "reranked": False, "mode": "full_document",
        }

    # Path B: Synthesis without filename → retrieve ALL collection chunks
    # FIX: This is the critical fix for missing topics (Strategy, Adapter, etc.)
    # BM25/semantic can't reliably retrieve all topics for generic synthesis queries.
    elif use_full_collection and not filename:
        all_docs = await _retrieve_all_chunks(limit=200)
        primary_trace = {
            "semantic_count": len(all_docs), "bm25_count": 0,
            "merged_count": len(all_docs), "final_count": len(all_docs),
            "reranked": False, "mode": "full_collection",
        }

    # Path C: Filename mentioned → filter to that file
    elif filename:
        all_docs = await _retrieve_by_filename(filename, rewritten, effective_top_k)
        if all_docs:
            primary_trace = {
                "semantic_count": len(all_docs), "bm25_count": 0,
                "merged_count": len(all_docs), "final_count": len(all_docs),
                "reranked": False, "mode": "filename_filtered",
            }

    # Path D: Standard hybrid retrieval (factual QA, table, long_synthesis)
    if not all_docs:
        all_queries = [rewritten] + sub_queries
        tasks       = [
            hybrid_retrieve(q, top_k=effective_top_k, enable_reranking=effective_reranking)
            for q in all_queries
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error("Retrieval[%d] failed: %s", i, result)
                continue
            docs, trace = result
            logger.info("Retrieval[%d]: %d docs", i, len(docs))
            if i == 0:
                primary_trace   = trace
                reranked_scores = trace.get("reranked_scores")
            all_docs.extend(docs)

    # ── Step 5: Deduplication ──────────────────────────────────────
    seen:   set  = set()
    unique: list = []
    for doc in all_docs:
        key = doc.page_content[:120]
        if key not in seen:
            seen.add(key)
            unique.append(doc)

    # For synthesis: keep ALL unique docs (token budget trims context later)
    # For factual: cap at effective_top_k
    if use_full_collection or (qt == QueryType.SUMMARY and filename):
        final_docs = unique   # token budget handles trimming in _build_context
    else:
        final_docs = unique[:effective_top_k]

    logger.info(
        "Docs: %d total → %d unique → %d final",
        len(all_docs), len(unique), len(final_docs),
    )

    # ── Guard: empty retrieval ─────────────────────────────────────
    if not final_docs:
        logger.error("NO DOCS for '%s'", question[:60])
        return {
            "answer":           _NO_ANSWER,
            "citations":        [],
            "confidence_score": 0.0,
            "retrieval_trace":  primary_trace,
            "rewritten_query":  rewritten,
            "sub_queries":      sub_queries,
            "query_type":       qt.value,
        }

    # ── Guard: weak context (factual QA only) ─────────────────────
    if qt == QueryType.FACTUAL_QA and effective_reranking and _is_context_too_weak(reranked_scores):
        citations  = _build_citations(final_docs, reranked_scores)
        confidence = _compute_confidence(final_docs, reranked_scores, effective_top_k)
        return {
            "answer":           _NO_ANSWER,
            "citations":        citations,
            "confidence_score": confidence,
            "retrieval_trace":  primary_trace,
            "rewritten_query":  rewritten,
            "sub_queries":      sub_queries,
            "query_type":       qt.value,
        }

    # ── Step 6: Generation ─────────────────────────────────────────
    answer = ""
    try:
        is_synthesis = qt in (
            QueryType.SUMMARY,
            QueryType.REVISION_NOTES,
            QueryType.INTERVIEW_GUIDE,
            QueryType.CONCLUSION,
        )

        if is_synthesis and len(final_docs) > _MAP_CHUNK_GROUP_SIZE:
            # Map-reduce for large doc sets — each phase has its own token budget
            logger.info("Map-reduce | qt=%s | docs=%d", qt.value, len(final_docs))
            answer = await _map_reduce_summarize(final_docs, question)
        else:
            # Single-pass generation with token-budgeted context
            context     = _build_context(final_docs, qt_value=qt.value)
            history_str = _build_history_str(
                [
                    {"role": m.get("role","user"), "content": m.get("content","")}
                    if isinstance(m, dict)
                    else {"role": getattr(m,"role","user"), "content": getattr(m,"content","")}
                    for m in history
                ]
            )

            # FIX: create LLM with token budget appropriate for this query type
            llm    = _make_generation_llm(qt.value)
            prompt = _get_prompt(qt)

            logger.info(
                "LLM | qt=%s | context_chars=%d | max_tokens=%d",
                qt.value, len(context), _answer_max_tokens(qt.value),
            )

            chain  = prompt | llm | StrOutputParser()
            kwargs = {"context": context, "question": rewritten}
            if qt in (QueryType.FACTUAL_QA, QueryType.LONG_SYNTHESIS):
                kwargs["history"] = history_str

            answer = (await chain.ainvoke(kwargs)).strip()

        if not answer:
            logger.warning("Empty LLM response")
            answer = _NO_ANSWER

        logger.info(
            "Answer: %d chars | preview='%s…'",
            len(answer), answer[:80].replace("\n"," "),
        )

    except Exception as exc:
        logger.error("Generation failed: %s", exc, exc_info=True)
        # Check if it's a token overflow error and return a helpful message
        if "413" in str(exc) or "too large" in str(exc).lower() or "token" in str(exc).lower():
            answer = (
                "The document is too large to process in one pass. "
                "Try asking about a specific topic or section instead of the full document."
            )
        else:
            answer = f"Generation failed: {exc}. Please check your Groq API key."

    # ── Step 7: Citations + confidence ────────────────────────────
    # For synthesis: cite first N docs that fit in budget
    cite_docs   = final_docs[:min(len(final_docs), effective_top_k)]
    citations   = _build_citations(cite_docs, reranked_scores)
    confidence  = _compute_confidence(cite_docs, reranked_scores, effective_top_k)

    if use_full_collection and cite_docs and confidence < 0.5:
        confidence = max(confidence, 0.6)

    logger.info(
        "DONE | qt=%s | docs=%d | citations=%d | confidence=%.2f",
        qt.value, len(final_docs), len(citations), confidence,
    )

    return {
        "answer":           answer,
        "citations":        citations,
        "confidence_score": confidence,
        "retrieval_trace":  primary_trace,
        "rewritten_query":  rewritten,
        "sub_queries":      sub_queries,
        "query_type":       qt.value,
    }