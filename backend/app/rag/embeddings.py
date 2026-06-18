"""
NexusIQ — rag/embeddings.py

Embedding layer using sentence-transformers (BAAI/bge-small-en).

FIX: get_sentence_embedding_dimension() → get_embedding_dimension()
  sentence-transformers ≥ 3.x renamed this method.
  The old name still works but throws FutureWarning on every startup.
  Fix: try new name first, fall back to old name for older installs.
"""

from __future__ import annotations

import logging
import threading
from typing import ClassVar, List


from app.config import settings

logger = logging.getLogger("nexusiq.embeddings")

BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


def _get_embedding_dim(model) -> int:
    """
    Get embedding dimension — compatible with both old and new
    sentence-transformers API.

    sentence-transformers < 3.0 : get_sentence_embedding_dimension()
    sentence-transformers ≥ 3.0 : get_embedding_dimension()
    """
    if hasattr(model, "get_embedding_dimension"):
        return model.get_embedding_dimension()
    return model.get_sentence_embedding_dimension()


class EmbeddingManager:
    """
    Singleton wrapper around SentenceTransformer (BAAI/bge-small-en).
    Uses the model directly (not HuggingFaceEmbeddings wrapper) to
    ensure correct asymmetric BGE embedding:
      Documents: no prefix
      Queries:   BGE_QUERY_PREFIX + query
    """

    _instance: ClassVar[EmbeddingManager | None] = None
    _model = None  # SentenceTransformer instance — loaded lazily
    _lock:  ClassVar[threading.Lock] = threading.Lock()

    def __new__(cls) -> "EmbeddingManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _load(self) -> None:
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:   # double-checked — prevents duplicate loads
                return
            import time
            import os
            from sentence_transformers import SentenceTransformer  # deferred import

            cache_dir = os.environ.get("HF_HOME") or os.environ.get("TRANSFORMERS_CACHE") or "(default ~/.cache)"
            logger.info(
                "Loading embedding model '%s' on device='%s' | cache_dir=%s",
                settings.embedding_model,
                settings.embedding_device,
                cache_dir,
            )
            t0 = time.monotonic()
            try:
                self._model = SentenceTransformer(
                    settings.embedding_model,
                    device=settings.embedding_device,
                )
            except Exception:
                logger.exception(
                    "Embedding model load FAILED after %.1fs — likely a download/network/disk issue",
                    time.monotonic() - t0,
                )
                raise
            elapsed = time.monotonic() - t0
            if elapsed > 60:
                logger.warning(
                    "Embedding model load took %.1fs (>60s) — this usually means a slow/"
                    "uncached download. Pre-download the model at build time to avoid "
                    "this on every cold start.",
                    elapsed,
                )
            logger.info(
                "SentenceTransformer constructor returned after %.1fs",
                time.monotonic() - t0,
            )

        dim = _get_embedding_dim(self._model)
        logger.info(
            "Embedding model '%s' loaded ✓ — dim=%d",
            settings.embedding_model,
            dim,
        )

    @property
    def model(self):
        self._load()
        assert self._model is not None
        return self._model

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embed document chunks — NO BGE prefix (correct for indexing)."""
        if not texts:
            return []

        vectors = self.model.encode(
            texts,
            batch_size=settings.embedding_batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )

        logger.debug(
            "Document embeddings: count=%d dim=%d",
            len(vectors), vectors.shape[1] if len(vectors) > 0 else 0,
        )
        return vectors.tolist()

    def embed_query(self, query: str) -> List[float]:
        """Embed a search query — WITH BGE prefix (correct for retrieval)."""
        prefixed = BGE_QUERY_PREFIX + query.strip()
        vector   = self.model.encode(
            prefixed,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return vector.tolist()

    def embed_documents_batched(self, texts: List[str], batch_size: int = 8) -> List[List[float]]:
        """Embed document chunks with explicit batch size for memory control."""
        if not texts:
            return []
        import time
        logger.info("embed_documents_batched: about to access self.model (triggers load if needed)")
        model = self.model   # forces _load() here, with its own logging
        logger.info("embed_documents_batched: model ready, starting encode() for %d texts", len(texts))
        t0 = time.monotonic()
        vectors = model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        logger.info(
            "embed_documents_batched: encode() finished in %.1fs — count=%d batch_size=%d dim=%d",
            time.monotonic() - t0, len(vectors), batch_size, vectors.shape[1] if len(vectors) > 0 else 0,
        )
        return vectors.tolist()

    def embed_queries(self, queries: List[str]) -> List[List[float]]:
        """Embed multiple queries in one batch."""
        if not queries:
            return []
        prefixed = [BGE_QUERY_PREFIX + q.strip() for q in queries]
        vectors  = self.model.encode(
            prefixed,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return vectors.tolist()


embedding_manager = EmbeddingManager()