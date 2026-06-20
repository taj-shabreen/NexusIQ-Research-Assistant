"""
debug.py — /api/debug/ endpoints for the Debug Console UI.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger("nexusiq.api.debug")
router = APIRouter()


class RetrieveRequest(BaseModel):
    query:  str
    top_k:  int = 5


@router.get("/health")
async def debug_health():
    from app.rag.vectorstore import get_or_create_collection
    from app.rag.embeddings  import embedding_manager

    try:
        collection  = get_or_create_collection()
        chunk_count = collection.count()
        db_status   = "ok"
    except Exception as exc:
        chunk_count = 0
        db_status   = str(exc)

    # No local model to "load" anymore — Jina is a stateless API client.
    # embedding_manager._model existed only in the old SentenceTransformer
    # wrapper and no longer exists on the current class.
    model_loaded = True   # always true: there's nothing to lazily load

    return {
        "status":       "ok",
        "groq_model":   settings.groq_model,
        "groq_key_set": bool(settings.groq_api_key),
        "embed_model":  settings.embedding_model,
        "embed_loaded": model_loaded,
        "chroma_path":  settings.chroma_persist_dir,
        "chunk_count":  chunk_count,
        "db_status":    db_status,
        "reranker":     settings.reranker_model,
        "reranker_on":  settings.reranker_enabled,
    }


@router.get("/stats")
async def debug_stats():
    try:
        from app.rag.vectorstore import get_or_create_collection
        collection = get_or_create_collection()
        total      = collection.count()

        result    = collection.get(include=["metadatas"])
        metadatas = result.get("metadatas") or []

        doc_chunks: Dict[str, int] = {}
        for m in metadatas:
            fname = m.get("filename", "unknown")
            doc_chunks[fname] = doc_chunks.get(fname, 0) + 1

        return {
            "total_chunks":    total,
            "total_documents": len(doc_chunks),
            "documents":       [
                {"filename": k, "chunks": v}
                for k, v in sorted(doc_chunks.items())
            ],
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/retrieve")
async def debug_retrieve(req: RetrieveRequest, x_session_id: str = Header(..., alias="X-Session-Id")):
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")
    if not x_session_id or not x_session_id.strip():
        raise HTTPException(status_code=400, detail="X-Session-Id header is required.")
    session_id = x_session_id.strip()

    try:
        from app.rag.retriever import hybrid_retrieve
        docs, trace = await hybrid_retrieve(
            req.query, session_id, top_k=req.top_k, enable_reranking=True
        )
        return {
            "query":   req.query,
            "results": [
                {
                    "text":     doc.page_content[:500],
                    "filename": doc.metadata.get("filename", ""),
                    "page":     doc.metadata.get("page", 0),
                    "chunk_index": doc.metadata.get("chunk_index", 0),
                }
                for doc in docs
            ],
            "trace": trace,
        }
    except Exception as exc:
        logger.exception("Debug retrieve failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/collection-stats")
async def collection_stats():
    return await debug_stats()