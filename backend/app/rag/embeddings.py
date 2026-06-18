"""
NexusIQ -- rag/embeddings.py

Embedding layer using the Jina AI Embeddings API (jina-embeddings-v3).
100% free-tier compatible: no OpenAI, no local model, no torch.

MIGRATION NOTE (replaces local SentenceTransformer / BAAI/bge-small-en):
  - No torch, no transformers, no local model download.
  - Embeddings are generated via a plain HTTPS POST to api.jina.ai using
    httpx (already a project dependency) -- no extra SDK required.
  - Dimension changed: 384 (bge-small) -> 1024 (jina-embeddings-v3 default).
    Any existing ChromaDB collection built with the old model MUST be
    reset/recreated -- old and new vectors are not comparable. Mixing
    dimensions in one collection raises a ChromaDB dimension-mismatch error.
  - Jina v3 is asymmetric like BGE was: documents use task="retrieval.passage",
    queries use task="retrieval.query". This class handles that distinction
    internally so callers don't need to know about it.
  - Memory footprint: near-zero. No model in process RAM at any point.

IMPORTANT -- Jina free tier is a fixed token allowance per API key (not an
unlimited-forever free plan). If you exhaust it, requests will start
returning 401/429 errors. Get a key at https://jina.ai/embeddings/ -- the
signup flow issues a free key with a starting token allowance, no card
required for that initial allowance.
"""

from __future__ import annotations

import logging
import os
from typing import List, Literal

import httpx

from app.config import settings

logger = logging.getLogger("nexusiq.embeddings")

JINA_API_URL = "https://api.jina.ai/v1/embeddings"

# jina-embeddings-v3 default output dimension (Matryoshka-capable: can be
# reduced via the `dimensions` request field, but we keep the default here
# for simplicity and best retrieval quality).
EMBEDDING_DIM = 1024

_REQUEST_TIMEOUT = 30.0  # seconds, per HTTP call


class EmbeddingManager:
    """
    Thin wrapper around the Jina AI Embeddings API.

    No local model, no singleton-loading pattern needed -- this is a plain
    HTTP client. Kept as a class so call sites elsewhere in the codebase
    (`embedding_manager.embed_query(...)`, etc.) do not need to change.
    """

    @property
    def api_key(self) -> str:
        key = getattr(settings, "jina_api_key", None) or os.environ.get("JINA_API_KEY")
        if not key:
            raise RuntimeError(
                "JINA_API_KEY is not set. Add it to your .env / Render "
                "environment variables to use Jina embeddings. Get a free "
                "key at https://jina.ai/embeddings/"
            )
        return key

    @property
    def model_name(self) -> str:
        return getattr(settings, "embedding_model", None) or "jina-embeddings-v3"

    # -- Core API call ---------------------------------------------------

    def _embed_batch(
        self,
        texts: List[str],
        task: Literal["retrieval.passage", "retrieval.query"],
    ) -> List[List[float]]:
        """Single API call for a batch of texts."""
        if not texts:
            return []
        # Jina rejects empty strings -- guard against that.
        safe_texts = [t if t.strip() else " " for t in texts]

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "model": self.model_name,
            "input": safe_texts,
            "task": task,
            "dimensions": EMBEDDING_DIM,
        }

        try:
            response = httpx.post(
                JINA_API_URL, headers=headers, json=payload, timeout=_REQUEST_TIMEOUT
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Jina embeddings API returned %s: %s",
                exc.response.status_code, exc.response.text[:300],
            )
            raise RuntimeError(
                f"Jina embeddings API error ({exc.response.status_code}). "
                "Check JINA_API_KEY validity and remaining free-tier quota."
            ) from exc
        except httpx.RequestError as exc:
            logger.error("Jina embeddings API request failed: %s", exc)
            raise RuntimeError(f"Could not reach Jina embeddings API: {exc}") from exc

        data = response.json()
        # Jina returns {"data": [{"embedding": [...], "index": 0}, ...]}
        # sorted by index -- sort defensively in case the API ever returns
        # them out of order.
        items = sorted(data["data"], key=lambda d: d["index"])
        return [item["embedding"] for item in items]

    # -- Public API (matches the previous SentenceTransformer-based interface) --

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embed document chunks using the retrieval.passage task adapter."""
        if not texts:
            return []
        vectors = self._embed_batch(texts, task="retrieval.passage")
        logger.debug("Document embeddings: count=%d dim=%d", len(vectors), EMBEDDING_DIM)
        return vectors

    def embed_documents_batched(self, texts: List[str], batch_size: int = 50) -> List[List[float]]:
        """
        Embed document chunks in batches of `batch_size`.
        Jina has no hard per-request item limit, but keeping batches modest
        avoids large single HTTP payloads and keeps retry/timeout blast
        radius small.
        """
        if not texts:
            return []
        all_vectors: List[List[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            logger.info(
                "embed_documents_batched: requesting embeddings for batch %d-%d of %d",
                i, i + len(batch), len(texts),
            )
            all_vectors.extend(self._embed_batch(batch, task="retrieval.passage"))
        logger.info(
            "embed_documents_batched: finished -- count=%d batch_size=%d dim=%d",
            len(all_vectors), batch_size, EMBEDDING_DIM,
        )
        return all_vectors

    def embed_query(self, query: str) -> List[float]:
        """Embed a single search query using the retrieval.query task adapter."""
        vectors = self._embed_batch([query.strip()], task="retrieval.query")
        return vectors[0] if vectors else [0.0] * EMBEDDING_DIM

    def embed_queries(self, queries: List[str]) -> List[List[float]]:
        """Embed multiple queries in one batch."""
        if not queries:
            return []
        return self._embed_batch([q.strip() for q in queries], task="retrieval.query")


embedding_manager = EmbeddingManager()