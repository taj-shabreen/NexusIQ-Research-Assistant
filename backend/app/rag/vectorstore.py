"""
NexusIQ — rag/vectorstore.py

ChromaDB collection factory.

FIX: settings.chroma_path → settings.chroma_persist_dir
  The original project used settings.chroma_path.
  The deployment config.py rewrite renamed the attribute to
  settings.chroma_persist_dir (matching the env var CHROMA_PERSIST_DIR).
  This file now uses the correct attribute name.

MIGRATION NOTE (OpenAI embeddings, 1536-dim):
  ChromaDB itself is embedding-agnostic — no code change is needed here.
  However, if CHROMA_PERSIST_DIR already contains a collection populated
  with the old 384-dim BGE vectors, the first collection.add() call with
  new 1536-dim OpenAI vectors WILL raise a dimension-mismatch error.
  Before deploying this migration, delete the old collection directory
  (or call collection.reset() once) so it's recreated fresh at the new
  dimension. On Render this means clearing the persistent disk path
  configured at CHROMA_PERSIST_DIR, or bumping CHROMA_COLLECTION to a
  new name so a fresh collection is created automatically.
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
            path=settings.chroma_persist_dir,
            settings=ChromaSettings(
                anonymized_telemetry=False,
                allow_reset=True,
            ),
        )

        collection = client.get_or_create_collection(
            name=settings.chroma_collection,
            metadata={"hnsw:space": "cosine"},
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