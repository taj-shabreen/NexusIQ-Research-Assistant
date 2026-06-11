"""
NexusIQ — main.py

MEMORY FIX for Render Free Tier (512MB RAM):

ROOT CAUSE:
  The previous version called `embedding_manager.model` inside the
  lifespan startup block. This forced SentenceTransformer (BAAI/bge-small-en)
  to load at startup, consuming ~300MB immediately — crashing Render Free Tier
  before a single request was ever handled.

FIX:
  1. Removed the embedding warm-up block from startup entirely.
     SentenceTransformer now loads lazily on the FIRST actual upload/query.
  2. Removed the reranker warm-up (CrossEncoder loads lazily too).
  3. _READINESS["embeddings"] is now set based on config validity only
     (is the model name configured?) NOT on whether the model is loaded.
  4. /health and /ready respond instantly — no model loading triggered.
  5. Startup RAM usage drops from ~350MB to ~80MB, well within 512MB.

BEHAVIOUR:
  - Startup: fast, low memory (~80MB)
  - First upload: SentenceTransformer loads once (~300MB, one-time cost)
  - Subsequent requests: model already in memory, instant
  - Local dev: identical behaviour — lazy loading works the same way
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
    "embeddings": False,   # True = model name is configured (NOT that model is loaded)
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
    """
    Startup: only initialise lightweight components.
    Heavy models (SentenceTransformer, CrossEncoder) are NOT loaded here.
    They load lazily on first use.
    """
    global _STARTUP_TIME, _STARTUP_ERROR
    t0 = time.monotonic()

    logger.info(
        "🚀 NexusIQ starting | env=%s | model=%s",
        settings.app_env, settings.groq_model,
    )

    # ── 1. Upload directory (lightweight) ─────────────────────────
    try:
        from pathlib import Path
        Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
        _READINESS["uploads"] = True
        logger.info("  Uploads dir ready ✓ — %s", settings.upload_dir)
    except Exception as exc:
        _STARTUP_ERROR = f"Upload dir: {exc}"
        logger.error("  Upload dir failed: %s", exc)

    # ── 2. ChromaDB (lightweight — just creates the client) ────────
    # This does NOT load any embedding model. ChromaDB with
    # PersistentClient only reads/writes HNSW index files.
    try:
        from app.rag.vectorstore import get_or_create_collection
        collection = get_or_create_collection()
        count      = collection.count()
        _READINESS["vectordb"] = True
        logger.info("  ChromaDB ready ✓ — vectors=%d", count)
    except Exception as exc:
        _STARTUP_ERROR = f"ChromaDB: {exc}"
        logger.error("  ChromaDB failed: %s", exc)

    # ── 3. Embedding model config check (NOT loading the model) ────
    # We only verify the model name is configured.
    # SentenceTransformer loads lazily on first embed_documents() call.
    # MEMORY FIX: do NOT call embedding_manager.model here.
    try:
        if settings.embedding_model and len(settings.embedding_model) > 2:
            _READINESS["embeddings"] = True
            logger.info(
                "  Embedding config ready ✓ — model=%s (loads on first use)",
                settings.embedding_model,
            )
        else:
            _STARTUP_ERROR = "EMBEDDING_MODEL not configured"
            logger.error("  Embedding model name missing in config")
    except Exception as exc:
        _STARTUP_ERROR = f"Embedding config: {exc}"
        logger.error("  Embedding config check failed: %s", exc)

    # ── 4. Groq API key check (no network call, just validates key) ─
    try:
        if settings.groq_api_key and len(settings.groq_api_key) > 10:
            _READINESS["llm"] = True
            logger.info("  Groq key ready ✓ — model=%s", settings.groq_model)
        else:
            _STARTUP_ERROR = "GROQ_API_KEY missing"
            logger.error("  Groq API key missing or too short")
    except Exception as exc:
        _STARTUP_ERROR = f"Groq config: {exc}"
        logger.error("  Groq config check failed: %s", exc)

    # ── NOTE: Reranker (CrossEncoder) is NOT initialised here ──────
    # It loads lazily via @lru_cache in retriever.py on first rerank call.

    _STARTUP_TIME = time.monotonic() - t0
    not_ready     = [k for k, v in _READINESS.items() if not v]

    if _all_ready():
        logger.info(
            "✅ All systems ready (%.2fs) — models load on first request",
            _STARTUP_TIME,
        )
    else:
        logger.error("❌ Startup errors — not ready: %s", not_ready)

    yield

    # ── Shutdown ───────────────────────────────────────────────────
    logger.info("🛑 Shutting down")
    for k in _READINESS:
        _READINESS[k] = False


# ── Application factory ────────────────────────────────────────────

def create_app() -> FastAPI:
    _app = FastAPI(
        title="NexusIQ API",
        version=settings.app_version,
        docs_url="/docs"   if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # ── CORS ───────────────────────────────────────────────────────
    logger.info("ALLOWED_ORIGINS loaded: %s", settings.allowed_origins)
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

    try:
        from app.api.visitors import router as visitors_router
        _app.include_router(visitors_router, prefix="/api/visitors", tags=["Visitors"])
    except ImportError:
        pass

    # ── Global exception handler ───────────────────────────────────
    @_app.exception_handler(Exception)
    async def _global_exc(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled %s on %s: %s", type(exc).__name__, request.url.path, exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error.", "path": str(request.url)},
        )

    # ── /health — always responds instantly, no model loading ──────
    @_app.get("/health", tags=["Health"])
    async def health() -> dict:
        """
        Lightweight health probe — responds instantly.
        Does NOT trigger any model loading.
        """
        try:
            from app.rag.vectorstore import get_or_create_collection
            chunks = get_or_create_collection().count()
        except Exception:
            chunks = -1

        from app.rag.embeddings import embedding_manager
        model_loaded = embedding_manager._model is not None

        return {
            "status":         "ok" if _all_ready() else "starting",
            "ready":          _all_ready(),
            "subsystems":     dict(_READINESS),
            "startup_time_s": round(_STARTUP_TIME, 2),
            "startup_error":  _STARTUP_ERROR or None,
            "version":        settings.app_version,
            "model":          settings.groq_model,
            "embed_model":    settings.embedding_model,
            "embed_loaded":   model_loaded,   # shows if model is in RAM yet
            "chunks_stored":  chunks,
            "env":            settings.app_env,
        }

    # ── /ready — 200 only when all config checks pass ──────────────
    @_app.get("/ready", tags=["Health"])
    async def ready() -> JSONResponse:
        """
        Readiness probe — responds instantly.
        Returns 200 when all subsystems are configured.
        Does NOT trigger any model loading.
        """
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
