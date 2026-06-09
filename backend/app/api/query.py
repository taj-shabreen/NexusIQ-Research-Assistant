"""
NexusIQ — api/query.py

FastAPI router: conversational RAG query endpoint
  POST /api/query/   — ask a question, receive a cited, confidence-scored answer

Changes vs original:
  1. Response now includes query_type field so frontend can display
     which mode was used (factual_qa / summary / revision_notes / etc.)
  2. enable_multi_query default changed to False — reduces Groq API calls.
  3. Query schema allows optional query_type override from frontend.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from app.rag.pipeline import rag_pipeline

logger = logging.getLogger("nexusiq.api.query")
router = APIRouter()


# ── Request / Response schemas ────────────────────────────────────

class Message(BaseModel):
    """Single turn in the conversation history."""
    role:    str = Field(..., description="'user' or 'assistant'")
    content: str = Field(..., min_length=1)

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in {"user", "assistant", "system"}:
            raise ValueError("role must be 'user', 'assistant', or 'system'")
        return v


class QueryRequest(BaseModel):
    """Incoming query payload."""
    question:             str           = Field(..., min_length=1, max_length=2000)
    conversation_history: List[Message] = Field(
        default_factory=list,
        max_length=20,
    )
    top_k:              Optional[int]  = Field(default=None, ge=1, le=30)
    enable_reranking:   bool           = Field(default=True)
    enable_multi_query: bool           = Field(default=False)


class Citation(BaseModel):
    """Source reference for a specific claim in the answer."""
    document_id:    str   = Field(...)
    filename:       str   = Field(...)
    page:           int   = Field(..., ge=1)
    chunk_text:     str   = Field(...)
    relevance_score: float = Field(..., ge=0.0, le=1.0)


class QueryResponse(BaseModel):
    """Full answer with provenance and diagnostics."""
    answer:           str            = Field(...)
    citations:        List[Citation]  = Field(default_factory=list)
    confidence_score: float           = Field(..., ge=0.0, le=1.0)
    retrieval_trace:  Dict[str, Any]  = Field(default_factory=dict)
    rewritten_query:  Optional[str]   = Field(default=None)
    sub_queries:      List[str]       = Field(default_factory=list)
    query_type:       Optional[str]   = Field(
        default=None,
        description="Detected query type: factual_qa | summary | revision_notes | interview_guide | table | conclusion | long_synthesis",
    )


# ── Endpoint ──────────────────────────────────────────────────────

@router.post(
    "/",
    response_model=QueryResponse,
    summary="Ask a research question — auto-routes by query type",
    status_code=status.HTTP_200_OK,
)
async def query(request: QueryRequest) -> QueryResponse:
    """
    Execute the full RAG pipeline with intelligent query-type routing.

    The pipeline automatically detects query type and adjusts:
    - Retrieval parameters (top_k, fetch_k, reranking)
    - LLM prompt (factual / summary / revision / interview / table / conclusion)
    - Generation strategy (single-pass vs map-reduce)

    Filename detection is automatic:
    - "Summarize AIACASE.pdf" → retrieves only from AIACASE.pdf
    """
    logger.info(
        "Query | question='%.80s' | top_k=%s | reranking=%s | multi_query=%s",
        request.question,
        request.top_k,
        request.enable_reranking,
        request.enable_multi_query,
    )

    try:
        result = await rag_pipeline(
            question=request.question,
            history=[m.model_dump() for m in request.conversation_history],
            top_k=request.top_k,
            enable_reranking=request.enable_reranking,
            enable_multi_query=request.enable_multi_query,
        )
    except RuntimeError as exc:
        logger.error("Pipeline runtime error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"RAG pipeline error: {exc}",
        ) from exc
    except Exception as exc:
        logger.exception("Unexpected pipeline error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during query processing.",
        ) from exc

    # Validate citations
    validated_citations: List[Citation] = []
    for raw_cite in result.get("citations", []):
        try:
            validated_citations.append(Citation(**raw_cite))
        except Exception as exc:
            logger.warning("Skipping malformed citation (%s): %s", exc, raw_cite)

    logger.info(
        "Query answered | qt=%s | citations=%d | confidence=%.2f",
        result.get("query_type", "unknown"),
        len(validated_citations),
        result.get("confidence_score", 0.0),
    )

    return QueryResponse(
        answer=           result["answer"],
        citations=        validated_citations,
        confidence_score= result.get("confidence_score", 0.0),
        retrieval_trace=  result.get("retrieval_trace", {}),
        rewritten_query=  result.get("rewritten_query"),
        sub_queries=      result.get("sub_queries", []),
        query_type=       result.get("query_type"),
    )