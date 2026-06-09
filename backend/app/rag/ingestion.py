"""
NexusIQ — rag/ingestion.py

PDF ingestion pipeline:
  PDF path → PyPDFLoader → text normalisation → RecursiveCharacterTextSplitter
  → metadata enrichment → ChromaDB via vectorstore

FIXES applied:
  1. chunk_size bumped from 512 → 800 characters
     Technical PDFs (algorithms, data structures) need larger chunks to keep
     concept explanations intact. A 512-char chunk cuts merge sort stability
     explanation in half.
  2. chunk_overlap bumped from 64 → 150 characters
     More overlap means a concept near a chunk boundary is still fully
     represented in at least one chunk.
  3. Minimum page content threshold lowered from >20 to >50 chars
     to skip truly blank pages but keep short content pages.
  4. Added detailed debug logs at every stage so you can trace exactly
     what is extracted, how many chunks are created, and sample content.
"""

import hashlib
import logging
import re
import unicodedata
from pathlib import Path
from typing import List, Tuple

from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import settings
from app.rag.vectorstore import get_or_create_collection
from app.rag.embeddings import embedding_manager

logger = logging.getLogger("nexusiq.ingestion")


# ── Text normalisation ─────────────────────────────────────────────

def _normalise(text: str) -> str:
    """
    Clean raw PDF-extracted text.
    - NFC unicode normalisation (fixes ligatures: ﬁ→fi, ﬀ→ff).
    - Strip non-printable control characters.
    - Collapse excessive whitespace while preserving paragraph breaks.
    - Remove PDF artefacts like form-feed characters.
    """
    # Unicode normalise
    text = unicodedata.normalize("NFC", text)
    # Strip control characters (keep \n, \t)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    # Collapse multiple spaces/tabs on one line
    text = re.sub(r"[ \t]+", " ", text)
    # Collapse 3+ newlines → 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Strip trailing whitespace per line
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return text.strip()


# ── Splitter factory ───────────────────────────────────────────────

# FIX: chunk_size 512 → 800, overlap 64 → 150
# Technical content (algorithms, proofs) needs larger chunks so a concept
# explanation is not split across two separate chunks.
_CHUNK_SIZE    = 800   # characters — overrides settings for quality reasons
_CHUNK_OVERLAP = 150  # characters — generous overlap keeps boundary concepts intact

def _make_splitter() -> RecursiveCharacterTextSplitter:
    """
    Build RecursiveCharacterTextSplitter with semantically ordered separators.
    Priority: paragraph → line → sentence → word → character.
    """
    # Use hardcoded improved values; settings.chunk_size (512) is too small
    chunk_size    = max(settings.chunk_size, _CHUNK_SIZE)
    chunk_overlap = max(settings.chunk_overlap, _CHUNK_OVERLAP)

    logger.info(
        "Splitter config: chunk_size=%d, chunk_overlap=%d",
        chunk_size, chunk_overlap,
    )

    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", "! ", "? ", "; ", ", ", " ", ""],
        length_function=len,
        is_separator_regex=False,
        keep_separator=False,
    )


# ── Core pipeline ──────────────────────────────────────────────────

def _load_and_chunk(pdf_path: Path) -> Tuple[List[Document], str]:
    """
    Load a PDF, normalise its text, chunk it, and attach provenance metadata.

    Returns:
        (chunks, doc_id)
    """
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found at path: {pdf_path}")

    # Stable content-hash ID
    doc_id = hashlib.md5(pdf_path.read_bytes()).hexdigest()[:12]

    logger.info("=" * 60)
    logger.info("INGESTION START: '%s' (doc_id=%s)", pdf_path.name, doc_id)
    logger.info("File size: %.1f KB", pdf_path.stat().st_size / 1024)
    logger.info("=" * 60)

    loader = PyPDFLoader(str(pdf_path))
    raw_pages: List[Document] = loader.load()

    if not raw_pages:
        raise ValueError(f"No pages could be extracted from '{pdf_path.name}'")

    logger.info("Loaded %d raw pages from PDF", len(raw_pages))

    # Normalise and filter near-blank pages
    cleaned: List[Document] = []
    total_raw_chars = 0
    for page in raw_pages:
        raw_len = len(page.page_content)
        total_raw_chars += raw_len
        page.page_content = _normalise(page.page_content)
        clean_len = len(page.page_content.strip())

        if clean_len > 50:  # skip truly blank pages (was 20, increased to 50)
            page.metadata.setdefault("page", 0)
            page.metadata["filename"]    = pdf_path.name
            page.metadata["document_id"] = doc_id
            cleaned.append(page)
            logger.debug(
                "  Page %d: %d raw chars → %d clean chars ✓",
                page.metadata.get("page", 0) + 1, raw_len, clean_len,
            )
        else:
            logger.debug(
                "  Page %d: SKIPPED (only %d chars after cleaning)",
                page.metadata.get("page", 0) + 1, clean_len,
            )

    if not cleaned:
        raise ValueError(f"All pages in '{pdf_path.name}' are blank after normalisation")

    total_clean_chars = sum(len(p.page_content) for p in cleaned)
    logger.info(
        "Pages after filtering: %d/%d | Total chars: %d raw → %d clean",
        len(cleaned), len(raw_pages), total_raw_chars, total_clean_chars,
    )

    # Log sample of first page content for verification
    logger.info(
        "Sample extracted text (page 1, first 300 chars):\n%s",
        cleaned[0].page_content[:300].replace("\n", " "),
    )

    # Chunk
    splitter = _make_splitter()
    chunks: List[Document] = splitter.split_documents(cleaned)

    if not chunks:
        raise ValueError(f"No chunks created from '{pdf_path.name}' — check content")

    # Enrich each chunk with positional metadata
    for idx, chunk in enumerate(chunks):
        chunk.metadata.update({
            "document_id": doc_id,
            "filename":    pdf_path.name,
            "chunk_index": idx,
            "char_count":  len(chunk.page_content),
        })
        chunk.metadata.setdefault("page", 0)

    char_counts  = [c.metadata["char_count"] for c in chunks]
    total_chars  = sum(char_counts)
    avg_chars    = total_chars // max(len(chunks), 1)
    min_chars    = min(char_counts)
    max_chars    = max(char_counts)

    logger.info(
        "Chunks created: %d | avg=%d chars | min=%d | max=%d | total=%d chars",
        len(chunks), avg_chars, min_chars, max_chars, total_chars,
    )

    # Log sample chunks for debugging
    for i in [0, len(chunks) // 2, len(chunks) - 1]:
        if i < len(chunks):
            logger.info(
                "  Sample chunk[%d] (page=%d, %d chars): %s…",
                i,
                chunks[i].metadata.get("page", 0) + 1,
                chunks[i].metadata["char_count"],
                chunks[i].page_content[:150].replace("\n", " "),
            )

    return chunks, doc_id


# ── Public async entry-point ───────────────────────────────────────

async def ingest_document(pdf_path: Path) -> dict:
    """
    Full ingestion pipeline: load → chunk → embed → persist in ChromaDB.
    """
    # 1. Load & chunk
    chunks, doc_id = _load_and_chunk(pdf_path)

    # 2. Get collection
    collection = get_or_create_collection()

    try:
        texts     = [c.page_content for c in chunks]
        metadatas = [c.metadata     for c in chunks]
        ids       = [f"{doc_id}_{i}" for i in range(len(chunks))]

        # 3. Embed all chunks in one batched call
        logger.info("Generating embeddings for %d chunks…", len(chunks))
        embeddings = embedding_manager.embed_documents(texts)

        if len(embeddings) != len(texts):
            raise RuntimeError(
                f"Embedding count mismatch: {len(embeddings)} embeddings for {len(texts)} chunks"
            )

        logger.info(
            "Embeddings generated: count=%d, dim=%d",
            len(embeddings), len(embeddings[0]) if embeddings else 0,
        )

        # 4. Upsert into ChromaDB (idempotent)
        collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=metadatas,
        )

        # 5. Verify
        new_count = collection.count()
        logger.info(
            "Ingestion complete ✓ | doc_id=%s | chunks=%d | collection_total=%d",
            doc_id, len(chunks), new_count,
        )

    except Exception as exc:
        logger.error("ChromaDB write failed for '%s': %s", pdf_path.name, exc)
        raise RuntimeError(f"Failed to store embeddings: {exc}") from exc

    return {
        "document_id":    doc_id,
        "filename":       pdf_path.name,
        "chunks_created": len(chunks),
        "message":        "Ingestion complete",
    }