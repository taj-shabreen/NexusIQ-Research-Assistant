"""
main.py — FastAPI application entry point for NexusIQ.

Memory management:
  - SentenceTransformer (~300MB) is NOT loaded at startup.
  - It loads lazily on the first upload or query request.
  - This prevents OOM crashes on Render Free Tier (512MB RAM).

Readiness:
  - /ready returns subsystem status without loading models.
  - Frontend polls /ready until all non-embedding subsystems are up.
  - "embeddings" subsystem becomes ready after first upload/query.
"""
from __future__ import annotations

import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.config import settings

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("nexusiq")

# ── Readiness state ───────────────────────────────────────────────────────────
# Shared mutable dict — subsystem name → bool
_READINESS: dict[str, bool] = {
    "uploads": False,
    "vectordb": False,
    "embeddings": False,  # becomes True after first embed call
    "groq": False,
}


# ── Request logging middleware ────────────────────────────────────────────────

class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        dur = (time.perf_counter() - start) * 1000
        logger.debug(
            "%s %s → %d  (%.1fms)",
            request.method,
            request.url.path,
            response.status_code,
            dur,
        )
        return response


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "🚀 NexusIQ starting | env=%s | model=%s",
        settings.app_env,
        settings.groq_model,
    )

    errors: list[str] = []

    # 1. Upload directory
    try:
        upload_path = Path(settings.upload_dir)
        upload_path.mkdir(parents=True, exist_ok=True)
        _READINESS["uploads"] = True
        logger.info("  Uploads ready ✓ — %s", settings.upload_dir)
    except Exception as exc:
        errors.append("uploads")
        logger.error("  Uploads failed: %s", exc)

    # 2. ChromaDB — initialise collection WITHOUT loading embeddings
    try:
        from app.rag.vectorstore import get_vectorstore  # noqa: PLC0415
        vs = get_vectorstore()
        count = vs.collection.count()
        _READINESS["vectordb"] = True
        logger.info("  ChromaDB ready ✓ — %d chunks indexed", count)
    except Exception as exc:
        errors.append("vectordb")
        logger.error("  ChromaDB failed: %s", exc)

    # 3. Groq — verify API key is present (no network call at startup)
    try:
        if settings.groq_api_key:
            _READINESS["groq"] = True
            logger.info(
                "  Groq key ready ✓ — model=%s", settings.groq_model
            )
        else:
            errors.append("groq")
            logger.error("  Groq API key is missing")
    except Exception as exc:
        errors.append("groq")
        logger.error("  Groq check failed: %s", exc)

    # NOTE: embeddings subsystem is intentionally NOT loaded here.
    # SentenceTransformer (~300MB) loads lazily on first upload/query.
    # This is critical for Render Free Tier (512MB RAM limit).
    logger.info(
        "  Embeddings: lazy — will load on first upload/query (~300MB)"
    )

    if errors:
        logger.error("❌ Startup errors — not ready: %s", errors)
    else:
        logger.info("✅ All systems ready (embeddings load on demand)")

    yield

    logger.info("NexusIQ shutting down")


# ── App factory ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="NexusIQ Research AI",
    description="Multi-document RAG research assistant",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request logging (dev only to keep prod logs clean)
if settings.debug:
    app.add_middleware(RequestLogMiddleware)


# ── Routers ───────────────────────────────────────────────────────────────────

from app.api import documents, query, evaluation, debug, visitors  # noqa: E402

app.include_router(documents.router, prefix="/api")
app.include_router(query.router, prefix="/api")
app.include_router(evaluation.router, prefix="/api")
app.include_router(debug.router, prefix="/api")
app.include_router(visitors.router, prefix="/api")


# ── Health & readiness endpoints ──────────────────────────────────────────────

@app.get("/health", tags=["system"])
async def health():
    return {
        "status": "ok",
        "env": settings.app_env,
        "model": settings.groq_model,
    }


@app.get("/ready", tags=["system"])
async def ready():
    """
    Returns per-subsystem readiness.
    Frontend polls this until ready=True.

    Note: embeddings starts False and becomes True after first embed call.
    The application is usable as soon as uploads + vectordb + groq are ready.
    """
    # Consider ready when core subsystems are up (embeddings loads on demand)
    core_ready = all(
        _READINESS.get(s, False) for s in ("uploads", "vectordb", "groq")
    )
    return {
        "ready": core_ready,
        "subsystems": dict(_READINESS),
    }


# ── Callback for embeddings subsystem ─────────────────────────────────────────
# embeddings.py calls this after model loads successfully

def mark_embeddings_ready():
    _READINESS["embeddings"] = True
    logger.info("Embeddings subsystem ready ✓")