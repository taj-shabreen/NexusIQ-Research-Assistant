"""
NexusIQ — app/config.py

FIXES in this version:
  1. Restored settings.langchain_tracing_v2 alias
     langsmith_tracer.py references settings.langchain_tracing_v2
     The deployment rewrite renamed it to settings.langchain_tracing.
     Fix: keep settings.langchain_tracing AND add langchain_tracing_v2
     as an alias so both the old tracer code and any new code work.

  2. load_dotenv() called before any os.getenv() — fixes GROQ_API_KEY
     appearing missing on local dev startup.

  3. All original settings attributes preserved exactly.
     No removed or renamed attrs that other files depend on.
"""

import os
import sys
import logging
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("nexusiq.config")


class Settings:
    def __init__(self):
        # ── Load .env FIRST — before any os.getenv() call ────────────
        self._load_dotenv()

        # ── Required ──────────────────────────────────────────────────
        self.groq_api_key: str = self._require("GROQ_API_KEY")

        # ── LLM ───────────────────────────────────────────────────────
        self.groq_model:      str = os.getenv("GROQ_MODEL",      "llama-3.1-8b-instant")
        self.groq_max_tokens: int = int(os.getenv("GROQ_MAX_TOKENS", "1200"))

        self.embedding_model = os.getenv(
            "EMBEDDING_MODEL",
            "sentence-transformers/all-MiniLM-L6-v2"
        )

        self.embedding_device = os.getenv(
            "EMBEDDING_DEVICE",
            "cpu"
        )

        self.embedding_batch_size = int(
            os.getenv("EMBEDDING_BATCH_SIZE", "4")
        )
        # ── ChromaDB ──────────────────────────────────────────────────
        self.chroma_collection:  str = os.getenv("CHROMA_COLLECTION",  "nexusiq_docs")
        self.chroma_persist_dir: str = os.getenv("CHROMA_PERSIST_DIR", "./data/chroma")

        # ── File system ───────────────────────────────────────────────
        self.upload_dir:      str = os.getenv("UPLOAD_DIR",      "./data/uploads")
        self.model_cache_dir:     str = os.getenv("MODEL_CACHE_DIR",     "./data/model_cache")
        self.eval_history_path:   str = os.getenv("EVAL_HISTORY_PATH",  "./data/eval_history.jsonl")
        self.visitor_log_path:    str = os.getenv("VISITOR_LOG_PATH",   "./data/visitors.jsonl")

        # ── Retrieval ─────────────────────────────────────────────────
        self.chunk_size:    int = int(os.getenv("CHUNK_SIZE",    "512"))
        self.chunk_overlap: int = int(os.getenv("CHUNK_OVERLAP", "64"))

        self.top_k:              int = int(os.getenv("TOP_K",              "6"))
        self.multi_query_count:  int = int(os.getenv("MULTI_QUERY_COUNT",  "3"))

        self.reranker_model: str = os.getenv(
            "RERANKER_MODEL",
            "cross-encoder/ms-marco-MiniLM-L-6-v2"
        )
        self.reranker_enabled: bool = (
            os.getenv("RERANKER_ENABLED", "true").lower() == "true"
        )

        # ── App ───────────────────────────────────────────────────────
        self.log_level:   str = os.getenv("LOG_LEVEL",   "INFO").upper()
        self.app_env:     str = os.getenv("APP_ENV",     "development")
        self.app_version: str = os.getenv("APP_VERSION", "1.0.0")

        # ── Convenience ───────────────────────────────────────────────
        self.debug: bool = self.app_env.lower() != "production"

        # ── Extended retrieval (optional, used by future features) ──────
        self.max_upload_size_mb:         int   = int(os.getenv("MAX_UPLOAD_SIZE_MB",          "50"))
        self.top_k_vector:               int   = int(os.getenv("TOP_K_VECTOR",                "10"))
        self.top_k_bm25:                 int   = int(os.getenv("TOP_K_BM25",                  "10"))
        self.top_k_rerank:               int   = int(os.getenv("TOP_K_RERANK",                 "6"))
        self.confidence_threshold:       float = float(os.getenv("CONFIDENCE_THRESHOLD",     "0.25"))
        self.retrieval_fetch_multiplier: int   = int(os.getenv("RETRIEVAL_FETCH_MULTIPLIER",   "4"))

        # ── CORS ──────────────────────────────────────────────────────
        raw_origins = os.getenv(
            "ALLOWED_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000",
        )
        self.allowed_origins: List[str] = [
            o.strip() for o in raw_origins.split(",") if o.strip()
        ]

        # ── LangSmith / LangChain tracing ─────────────────────────────
        self.langchain_api_key: Optional[str] = os.getenv("LANGCHAIN_API_KEY")

        _tracing_enabled = (
            os.getenv("LANGCHAIN_TRACING", "false").lower() == "true"
            and bool(self.langchain_api_key)
        )

        # Primary name (new code uses this)
        self.langchain_tracing: bool = _tracing_enabled

        # FIX: Alias restored — langsmith_tracer.py uses langchain_tracing_v2
        self.langchain_tracing_v2: bool = _tracing_enabled

        # ── HuggingFace cache ─────────────────────────────────────────
        if self.model_cache_dir:
            os.environ.setdefault("HF_HOME",           self.model_cache_dir)
            os.environ.setdefault("TRANSFORMERS_CACHE", self.model_cache_dir)

        # ── Ensure data directories exist ─────────────────────────────
        for dir_path in [self.chroma_persist_dir, self.upload_dir, self.model_cache_dir]:
            try:
                Path(dir_path).mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                logger.warning("Could not create directory %s: %s", dir_path, exc)

        self._log_summary()

    # ── .env loader ───────────────────────────────────────────────────

    @staticmethod
    def _load_dotenv() -> None:
        """
        Load backend/.env into os.environ.
        Must be called before any os.getenv() call.
        override=False: deployment env vars take precedence over .env
        """
        candidates = [
            Path(".env"),
            Path("../.env"),
            Path(os.path.dirname(__file__)).parent.parent / ".env",
            Path(os.path.dirname(__file__)).parent / ".env",
        ]

        try:
            from dotenv import load_dotenv, find_dotenv
            env_path = find_dotenv(usecwd=True)
            if env_path:
                load_dotenv(env_path, override=False)
                return
            for candidate in candidates:
                if candidate.exists():
                    load_dotenv(candidate, override=False)
                    return
        except ImportError:
            for candidate in candidates:
                if candidate.exists():
                    Settings._parse_dotenv_manually(candidate)
                    return

    @staticmethod
    def _parse_dotenv_manually(path: Path) -> None:
        """Minimal .env parser fallback when python-dotenv is absent."""
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key   = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
        except Exception as exc:
            logger.warning("Failed to parse .env at %s: %s", path, exc)

    def _require(self, key: str) -> str:
        val = os.getenv(key, "").strip()
        if not val:
            print(
                f"\n❌  STARTUP ERROR: Required environment variable '{key}' is not set.\n"
                f"\n"
                f"    Checklist:\n"
                f"    1. Does backend/.env exist?\n"
                f"    2. Does it contain: {key}=your_value_here\n"
                f"    3. Is python-dotenv installed?  pip install python-dotenv\n"
                f"    4. Are you running uvicorn from the backend/ directory?\n"
                f"\n"
                f"    Run: cd backend && uvicorn app.main:app --reload\n",
                file=sys.stderr,
            )
            sys.exit(1)
        return val

    def _log_summary(self) -> None:
        logger.info(
            "Config | env=%s | model=%s | embed=%s | device=%s | top_k=%d",
            self.app_env,
            self.groq_model,
            self.embedding_model,
            self.embedding_device,
            self.top_k,
        )

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def is_development(self) -> bool:
        return self.app_env.lower() == "development"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()