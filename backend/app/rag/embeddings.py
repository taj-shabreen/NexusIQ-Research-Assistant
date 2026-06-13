"""
embeddings.py — SentenceTransformer wrapper with TRUE lazy loading.

CRITICAL: The model is NOT loaded at import time or at startup.
It loads only on the first call to embed_query() or embed_documents().
This prevents Render Free Tier OOM crashes during startup.

After the model loads, it calls main.mark_embeddings_ready() so the
/ready endpoint reflects the updated state.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from app.config import settings

logger = logging.getLogger("nexusiq.rag.embeddings")

_LOCK = threading.Lock()


class EmbeddingManager:
    def __init__(self) -> None:
        self._model = None  # NOT loaded yet
        self._dim: int = 384  # default for bge-small-en

    def _load(self) -> None:
        """Load SentenceTransformer — called once, on first use."""
        if self._model is not None:
            return
        with _LOCK:
            if self._model is not None:  # double-checked locking
                return
            logger.info(
                "Loading embedding model '%s' on device='cpu'",
                settings.embedding_model,
            )
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415

            cache_dir = Path(settings.model_cache_dir)
            cache_dir.mkdir(parents=True, exist_ok=True)

            model = SentenceTransformer(
                settings.embedding_model,
                cache_folder=str(cache_dir),
                device="cpu",
            )
            self._model = model

            # Get embedding dimension (compatible with both old and new ST versions)
            self._dim = self._get_dim(model)
            logger.info(
                "Embedding model '%s' loaded ✓ — dim=%d",
                settings.embedding_model,
                self._dim,
            )

            # Notify main that embeddings subsystem is ready
            try:
                from app.main import mark_embeddings_ready  # noqa: PLC0415
                mark_embeddings_ready()
            except Exception:
                pass  # Safe to ignore — main may not be imported yet in tests

    @staticmethod
    def _get_dim(model) -> int:
        """Get embedding dimension — compatible with sentence-transformers 2.x and 3.x."""
        try:
            return model.get_embedding_dimension()
        except AttributeError:
            pass
        try:
            return model.get_sentence_embedding_dimension()
        except AttributeError:
            pass
        # Fallback: run a tiny embed
        try:
            return len(model.encode("test"))
        except Exception:
            return 384

    @property
    def model(self):
        self._load()
        return self._model

    @property
    def dim(self) -> int:
        return self._dim

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query string (BGE uses a query prefix)."""
        self._load()
        # BGE models expect a query prefix for retrieval tasks
        prefixed = f"Represent this sentence for searching relevant passages: {text}"
        return self._model.encode(prefixed, normalize_embeddings=True).tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of document strings (no prefix for documents)."""
        self._load()
        return self._model.encode(
            texts, normalize_embeddings=True, batch_size=32, show_progress_bar=False
        ).tolist()


# Module-level singleton
embedding_manager = EmbeddingManager()