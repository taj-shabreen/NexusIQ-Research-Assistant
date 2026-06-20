"""
query.py — /api/query/ endpoint.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("nexusiq.api.query")
router = APIRouter()


class QueryRequest(BaseModel):
    question: str
    history:  List[Dict[str, str]] = []
    top_k:    Optional[int]        = None
    enable_reranking:   bool       = True
    enable_multi_query: bool       = False


class QueryResponse(BaseModel):
    answer:           str
    citations:        List[Dict[str, Any]] = []
    confidence_score: float                = 0.0
    retrieval_trace:  Dict[str, Any]       = {}
    rewritten_query:  str                  = ""
    sub_queries:      List[str]            = []
    query_type:       str                  = "factual_qa"


@router.post("/", response_model=QueryResponse)
async def query(req: QueryRequest, x_session_id: str = Header(..., alias="X-Session-Id")):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")
    if not x_session_id or not x_session_id.strip():
        raise HTTPException(status_code=400, detail="X-Session-Id header is required.")

    from app.rag.pipeline import rag_pipeline  # noqa: PLC0415

    try:
        result = await rag_pipeline(
            question           = req.question,
            session_id         = x_session_id.strip(),
            history            = req.history,
            top_k              = req.top_k,
            enable_reranking   = req.enable_reranking,
            enable_multi_query = req.enable_multi_query,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Pipeline error for question: %s", req.question[:80])
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return QueryResponse(**result)