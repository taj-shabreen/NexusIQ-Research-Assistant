"""
NexusIQ — main.py

Production-grade FastAPI application.

FIXES in this version:
  1. Embedding dim check uses get_embedding_dimension() via helper
     (removes FutureWarning from sentence-transformers ≥ 3.x)
  2. CORS uses settings.allowed_origins (from env var ALLOWED_ORIGINS)
  3. Request logging middleware
  4. Visitor tracking router mounted at /api/visitors
  5. Upload dir from settings.upload_dir (not hardcoded)
"""

import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Dict

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings

# ── Logging ────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("nexusiq")

# ── Global readiness state ─────────────────────────────────────────
_READINESS: Dict[str, bool] = {
    "vectordb":   False,
    "embeddings": False,
    "llm":        False,
    "uploads":    False,
}
_STARTUP_TIME: float = 0.0
_STARTUP_ERROR: str  = ""


def _all_ready() -> bool:
    return all(_READINESS.values())


# ── Lifespan ───────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _STARTUP_TIME, _STARTUP_ERROR
    t0 = time.monotonic()

    logger.info(
        "🚀 NexusIQ starting | env=%s | model=%s",
        settings.app_env, settings.groq_model,
    )

    # ── 1. Upload directory ────────────────────────────────────────
    try:
        from pathlib import Path
        Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
        _READINESS["uploads"] = True
        logger.info("  Uploads ready ✓ — %s", settings.upload_dir)
    except Exception as exc:
        _STARTUP_ERROR = f"Upload dir: {exc}"
        logger.error("  Upload dir failed: %s", exc)

    # ── 2. ChromaDB ────────────────────────────────────────────────
    # FIX: vectorstore.py now uses settings.chroma_persist_dir
    # (was settings.chroma_path which did not exist → AttributeError)
    try:
        from app.rag.vectorstore import get_or_create_collection
        collection = get_or_create_collection()
        count      = collection.count()
        _READINESS["vectordb"] = True
        logger.info("  ChromaDB ready ✓ — vectors=%d", count)
    except Exception as exc:
        _STARTUP_ERROR = f"ChromaDB: {exc}"
        logger.error("  ChromaDB failed: %s", exc)

    # ── 3. Embedding model ─────────────────────────────────────────
    # FIX: uses _get_embedding_dim() helper — no FutureWarning
    try:
        from app.rag.embeddings import embedding_manager
        from app.rag.embeddings import _get_embedding_dim
        _ = embedding_manager.model            # trigger lazy load
        dim = _get_embedding_dim(embedding_manager.model)
        _READINESS["embeddings"] = True
        logger.info("  Embeddings ready ✓ — dim=%d", dim)
    except Exception as exc:
        _STARTUP_ERROR = f"Embeddings: {exc}"
        logger.error("  Embeddings failed: %s", exc)

    # ── 4. Groq API key ────────────────────────────────────────────
    try:
        if settings.groq_api_key and len(settings.groq_api_key) > 10:
            _READINESS["llm"] = True
            logger.info("  Groq key ready ✓ — model=%s", settings.groq_model)
        else:
            _STARTUP_ERROR = "GROQ_API_KEY missing"
            logger.error("  Groq key missing")
    except Exception as exc:
        _STARTUP_ERROR = f"Groq: {exc}"
        logger.error("  Groq check failed: %s", exc)

    _STARTUP_TIME = time.monotonic() - t0
    not_ready = [k for k, v in _READINESS.items() if not v]

    if _all_ready():
        logger.info("✅ All systems ready (%.2fs)", _STARTUP_TIME)
    else:
        logger.error("❌ Startup errors — not ready: %s", not_ready)

    yield

    logger.info("🛑 Shutting down")
    for k in _READINESS:
        _READINESS[k] = False


# ── Application factory ────────────────────────────────────────────

def create_app() -> FastAPI:
    _app = FastAPI(
        title="NexusIQ API",
        version=settings.app_version,
        # Disable docs in production
        docs_url="/docs"   if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # ── CORS — reads from ALLOWED_ORIGINS env var ──────────────────
    # FIX: was hardcoded list — now uses settings.allowed_origins
    _app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Request logging middleware ─────────────────────────────────
    @_app.middleware("http")
    async def _log_requests(request: Request, call_next):
        t_start  = time.monotonic()
        response = await call_next(request)
        duration = round((time.monotonic() - t_start) * 1000, 1)
        # Skip health/ready polling from logs in production (too noisy)
        skip = settings.is_production and request.url.path in ("/health", "/ready")
        if not skip:
            logger.info(
                "%s %s → %d (%.1fms)",
                request.method, request.url.path,
                response.status_code, duration,
            )
        return response

    # ── Routers ────────────────────────────────────────────────────
    from app.api.documents  import router as documents_router
    from app.api.query      import router as query_router
    from app.api.evaluation import router as evaluation_router
    from app.api.debug      import router as debug_router

    _app.include_router(documents_router,  prefix="/api/documents",  tags=["Documents"])
    _app.include_router(query_router,      prefix="/api/query",      tags=["Query"])
    _app.include_router(evaluation_router, prefix="/api/evaluation", tags=["Evaluation"])
    _app.include_router(debug_router,      prefix="/api/debug",      tags=["Debug"])

    # Visitor router — only if visitors.py exists
    try:
        from app.api.visitors import router as visitors_router
        _app.include_router(visitors_router, prefix="/api/visitors", tags=["Visitors"])
    except ImportError:
        logger.debug("Visitors router not available — skipping")

    # ── Global exception handler ───────────────────────────────────
    @_app.exception_handler(Exception)
    async def _global_exc(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "Unhandled %s on %s: %s",
            type(exc).__name__, request.url.path, exc,
        )
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Internal server error — check logs.",
                "path":   str(request.url),
            },
        )

    # ── /health — always responds, per-subsystem breakdown ─────────
    @_app.get("/health", tags=["Health"])
    async def health() -> dict:
        """Always responds — even during startup."""
        try:
            from app.rag.vectorstore import get_or_create_collection
            chunks = get_or_create_collection().count()
        except Exception:
            chunks = -1

        return {
            "status":         "ok" if _all_ready() else "starting",
            "ready":          _all_ready(),
            "subsystems":     dict(_READINESS),
            "startup_time_s": round(_STARTUP_TIME, 2),
            "startup_error":  _STARTUP_ERROR or None,
            "version":        settings.app_version,
            "model":          settings.groq_model,
            "embed_model":    settings.embedding_model,
            "chunks_stored":  chunks,
            "env":            settings.app_env,
        }

    # ── /ready — 200 only when ALL subsystems ready ────────────────
    @_app.get("/ready", tags=["Health"])
    async def ready() -> JSONResponse:
        """Frontend polls this to gate uploads and queries."""
        if _all_ready():
            return JSONResponse(status_code=200, content={
                "ready":       True,
                "subsystems":  dict(_READINESS),
                "model":       settings.groq_model,
                "embed_model": settings.embedding_model,
            })
        return JSONResponse(status_code=503, content={
            "ready":      False,
            "subsystems": dict(_READINESS),
            "error":      _STARTUP_ERROR or "Backend still initialising…",
            "not_ready":  [k for k, v in _READINESS.items() if not v],
        })

    return _app


app: FastAPI = create_app()