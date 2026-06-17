"""
ingestion.py — PDF extraction, chunking, embedding, ChromaDB storage.
Uses settings.chunk_size / settings.chunk_overlap (defined in config.py).
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from pathlib import Path
from typing import List

from app.config import settings

logger = logging.getLogger("nexusiq.ingestion")


def _extract_text(pdf_path: str) -> str:
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise RuntimeError("Install PyMuPDF: pip install pymupdf") from exc

    doc   = fitz.open(pdf_path)
    pages = []
    for page in doc:
        text = page.get_text("text")
        if text.strip():
            pages.append(text)
    doc.close()

    full_text = "\n".join(pages)
    logger.debug("Extracted %d chars from %s (%d pages)", len(full_text), Path(pdf_path).name, len(pages))
    return full_text


def _clean_text(text: str) -> str:
    text = re.sub(r"[^\S\n]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _chunk_text(text: str, chunk_size: int, overlap: int) -> List[str]:
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: List[str] = []
    current = ""

    for para in paragraphs:
        if len(current) + len(para) + 2 <= chunk_size:
            current = (current + "\n\n" + para).lstrip()
        else:
            if current:
                chunks.append(current)
            if len(para) <= chunk_size:
                current = para
            else:
                sentences = re.split(r"(?<=[.!?])\s+", para)
                current = ""
                for sent in sentences:
                    if len(current) + len(sent) + 1 <= chunk_size:
                        current = (current + " " + sent).strip()
                    else:
                        if current:
                            chunks.append(current)
                        current = sent

    if current:
        chunks.append(current)

    if overlap > 0 and len(chunks) > 1:
        overlapped = [chunks[0]]
        for i in range(1, len(chunks)):
            tail = chunks[i - 1][-overlap:]
            overlapped.append((tail + " " + chunks[i]).strip())
        return overlapped

    return chunks


async def ingest_document(pdf_path: str, filename: str) -> int:
    loop     = asyncio.get_running_loop()
    raw_text = await loop.run_in_executor(None, _extract_text, pdf_path)

    if not raw_text.strip():
        raise ValueError(f"No text extracted from '{filename}'.")

    text       = _clean_text(raw_text)
    chunk_size = settings.chunk_size
    overlap    = settings.chunk_overlap
    chunks     = _chunk_text(text, chunk_size, overlap)

    logger.info("%s → %d chunks (size=%d, overlap=%d)", filename, len(chunks), chunk_size, overlap)
    if not chunks:
        raise ValueError(f"No chunks produced from '{filename}'.")

    from app.rag.vectorstore import get_or_create_collection
    from app.rag.embeddings  import embedding_manager

    collection = get_or_create_collection()

    # Delete stale chunks
    try:
        existing = collection.get(where={"filename": filename}, include=["metadatas"])
        old_ids  = existing.get("ids") or []
        if old_ids:
            collection.delete(ids=old_ids)
            logger.info("Deleted %d stale chunks for %s", len(old_ids), filename)
    except Exception:
        pass
    # Batch size 8 reduces peak RAM during encode on Render Free Tier (512MB)

    import functools

    _embed = functools.partial(
        embedding_manager.embed_documents_batched,
        chunks,
        batch_size=8
    )

    logger.info("Starting embeddings for %d chunks", len(chunks))

    embeddings = await loop.run_in_executor(None, _embed)

    logger.info("Embeddings completed")

    ids = [str(uuid.uuid4()) for _ in chunks]

    metadatas = [
        {
            "filename": filename,
            "chunk_index": i,
            "chunk_count": len(chunks),
            "page": i,
        }
        for i in range(len(chunks))
    ]

    logger.info("Adding chunks to Chroma")

    collection.add(
        ids=ids,
        documents=chunks,
        embeddings=embeddings,
        metadatas=metadatas,
    )

    logger.info("Chroma add completed")

    logger.info("Stored %d chunks for %s", len(chunks), filename)

    return len(chunks)