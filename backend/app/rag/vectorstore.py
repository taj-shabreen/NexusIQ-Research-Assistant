"""
NexusIQ — rag/vectorstore.py

ChromaDB collection factory.

FIX: settings.chroma_path → settings.chroma_persist_dir
  The original project used settings.chroma_path.
  The deployment config.py rewrite renamed the attribute to
  settings.chroma_persist_dir (matching the env var CHROMA_PERSIST_DIR).
  This file now uses the correct attribute name.
"""

import logging
from functools import lru_cache

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import settings

logger = logging.getLogger("nexusiq.vectorstore")


@lru_cache(maxsize=1)
def get_or_create_collection():
    """
    Return the singleton ChromaDB collection.
    Creates the persistent client and collection on first call.
    Cached — subsequent calls return the same collection instance.

    FIX: uses settings.chroma_persist_dir (was settings.chroma_path).
    """
    logger.info(
        "Initialising ChromaDB | persist_dir=%s | collection=%s",
        settings.chroma_persist_dir,
        settings.chroma_collection,
    )

    try:
        client = chromadb.PersistentClient(
            path=settings.chroma_persist_dir,          # FIX: was settings.chroma_path
            settings=ChromaSettings(
                anonymized_telemetry=False,
                allow_reset=True,
            ),
        )

        collection = client.get_or_create_collection(
            name=settings.chroma_collection,
            metadata={"hnsw:space": "cosine"},         # cosine distance for BGE embeddings
        )

        count = collection.count()
        logger.info(
            "ChromaDB ready ✓ | collection=%s | vectors=%d",
            settings.chroma_collection, count,
        )
        return collection

    except Exception as exc:
        logger.error("ChromaDB init failed: %s", exc, exc_info=True)
        raise