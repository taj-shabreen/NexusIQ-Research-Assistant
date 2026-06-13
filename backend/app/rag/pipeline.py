"""
vectorstore.py — ChromaDB client singleton.

Uses settings.chroma_persist_dir (NOT chroma_path — that was the old name
which caused 'Settings object has no attribute chroma_path' crash).
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import settings

logger = logging.getLogger("nexusiq.rag.vectorstore")


class VectorStore:
    def __init__(self) -> None:
        persist_dir = settings.chroma_persist_dir  # ← correct attribute
        Path(persist_dir).mkdir(parents=True, exist_ok=True)

        self._client = chromadb.PersistentClient(
            path=persist_dir,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self.collection = self._client.get_or_create_collection(
            name=settings.chroma_collection,
            metadata={"hnsw:space": "l2"},
        )
        logger.info(
            "ChromaDB initialised — collection='%s', path='%s', chunks=%d",
            settings.chroma_collection,
            persist_dir,
            self.collection.count(),
        )

    def reset(self) -> None:
        """Delete and recreate the collection (use with care)."""
        self._client.delete_collection(settings.chroma_collection)
        self.collection = self._client.get_or_create_collection(
            name=settings.chroma_collection,
            metadata={"hnsw:space": "l2"},
        )
        logger.warning("ChromaDB collection reset.")


@lru_cache(maxsize=1)
def get_vectorstore() -> VectorStore:
    return VectorStore()