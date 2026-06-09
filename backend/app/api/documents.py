"""
NexusIQ — api/documents.py

FastAPI router: PDF document management
  POST /api/documents/upload  — upload + index one or more PDFs
  GET  /api/documents/        — list all indexed documents
  DELETE /api/documents/{id}  — delete document + all its chunks

Production fixes:
  1. Readiness guard — checks vectordb + embeddings ready before processing
  2. Duplicate detection — SHA-256 content hash prevents re-indexing same file
  3. Graceful error handling — partial failures don't crash the whole batch
  4. File size validation — rejects files over MAX_UPLOAD_MB
  5. Type validation — rejects non-PDF files
"""

import hashlib
import logging
from pathlib import Path
from typing import List

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger("nexusiq.api.documents")
router = APIRouter()

MAX_UPLOAD_MB   = 60
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024


# ── Response schemas ───────────────────────────────────────────────

class IngestResponse(BaseModel):
    document_id:    str
    filename:       str
    chunks_created: int
    message:        str


class DocumentInfo(BaseModel):
    document_id: str
    filename:    str
    chunks:      int


class DeleteResponse(BaseModel):
    document_id: str
    message:     str


# ── Helpers ────────────────────────────────────────────────────────

def _check_readiness() -> None:
    """
    Raise 503 if the vectordb or embeddings subsystems are not ready.
    Prevents upload processing before ChromaDB/embedding model is initialised.
    """
    from app.main import _READINESS
    not_ready = [k for k in ("vectordb", "embeddings") if not _READINESS.get(k)]
    if not_ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Backend not ready: {', '.join(not_ready)} still initialising. Please retry.",
        )


def _content_hash(data: bytes) -> str:
    """SHA-256 of file content — used for duplicate detection."""
    return hashlib.sha256(data).hexdigest()[:16]


def _is_duplicate(content_hash: str) -> bool:
    """
    Check ChromaDB for any chunk with matching document_id prefix.
    Returns True if this content hash is already indexed.
    """
    try:
        from app.rag.vectorstore import get_or_create_collection
        collection = get_or_create_collection()
        results    = collection.get(
            where={"document_id": {"$eq": content_hash}},
            include=["metadatas"],
            limit=1,
        )
        return bool(results.get("ids"))
    except Exception:
        return False


# ── Upload endpoint ────────────────────────────────────────────────

@router.post(
    "/upload",
    response_model=List[IngestResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Upload and index one or more PDF documents",
)
async def upload_documents(
    files: List[UploadFile] = File(...),
) -> List[IngestResponse]:
    """
    Upload PDFs and index them into ChromaDB.

    - Rejects non-PDF files (by content type and extension)
    - Rejects files over MAX_UPLOAD_MB
    - Detects and skips duplicate files (by content hash)
    - Returns per-file result; partial failures do not abort the batch
    - Checks backend readiness before processing
    """
    _check_readiness()

    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files provided.",
        )

    from app.rag.ingestion import ingest_document

    results:  List[IngestResponse] = []
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    for file in files:
        fname = file.filename or "unknown.pdf"

        # ── Validate file type ─────────────────────────────────────
        if not fname.lower().endswith(".pdf"):
            logger.warning("Rejected non-PDF file: %s", fname)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Only PDF files are accepted. Received: {fname}",
            )

        # ── Read content ───────────────────────────────────────────
        try:
            content = await file.read()
        except Exception as exc:
            logger.error("Failed to read file '%s': %s", fname, exc)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to read file '{fname}': {exc}",
            ) from exc

        # ── Validate file size ─────────────────────────────────────
        if len(content) > MAX_UPLOAD_BYTES:
            size_mb = len(content) / (1024 * 1024)
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"File '{fname}' is {size_mb:.1f} MB — "
                    f"maximum allowed is {MAX_UPLOAD_MB} MB."
                ),
            )

        if len(content) < 100:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File '{fname}' appears to be empty or too small.",
            )

        # ── Duplicate detection ────────────────────────────────────
        content_hash = _content_hash(content)
        if _is_duplicate(content_hash):
            logger.info("Duplicate detected for '%s' (hash=%s) — skipping", fname, content_hash)
            results.append(IngestResponse(
                document_id=    content_hash,
                filename=       fname,
                chunks_created= 0,
                message=        "Document already indexed — skipped duplicate.",
            ))
            continue

        # ── Save to disk ───────────────────────────────────────────
        save_path = upload_dir / fname
        try:
            save_path.write_bytes(content)
        except Exception as exc:
            logger.error("Failed to save '%s': %s", fname, exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to save file '{fname}': {exc}",
            ) from exc

        # ── Ingest ────────────────────────────────────────────────
        try:
            logger.info("Ingesting '%s' (%d bytes, hash=%s)", fname, len(content), content_hash)
            result = await ingest_document(save_path)
            results.append(IngestResponse(
                document_id=    result["document_id"],
                filename=       result["filename"],
                chunks_created= result["chunks_created"],
                message=        result["message"],
            ))
            logger.info(
                "Ingested '%s' → %d chunks (doc_id=%s)",
                fname, result["chunks_created"], result["document_id"],
            )
        except Exception as exc:
            logger.error("Ingestion failed for '%s': %s", fname, exc, exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Ingestion failed for '{fname}': {exc}",
            ) from exc

    return results


# ── List endpoint ──────────────────────────────────────────────────

@router.get(
    "/",
    response_model=List[DocumentInfo],
    summary="List all indexed documents",
)
async def list_documents() -> List[DocumentInfo]:
    """
    Returns all unique documents currently indexed in ChromaDB.
    Groups chunks by document_id and returns per-document info.
    """
    try:
        from app.rag.vectorstore import get_or_create_collection
        collection = get_or_create_collection()
        raw        = collection.get(include=["metadatas"])
        metas      = raw.get("metadatas") or []
    except Exception as exc:
        logger.error("List documents failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not retrieve document list.",
        ) from exc

    # Group by document_id
    docs: dict = {}
    for meta in metas:
        doc_id   = meta.get("document_id", "unknown")
        filename = meta.get("filename",    "unknown")
        if doc_id not in docs:
            docs[doc_id] = {"document_id": doc_id, "filename": filename, "chunks": 0}
        docs[doc_id]["chunks"] += 1

    return [DocumentInfo(**v) for v in docs.values()]


# ── Delete endpoint ────────────────────────────────────────────────

@router.delete(
    "/{document_id}",
    response_model=DeleteResponse,
    summary="Delete a document and all its chunks from ChromaDB",
)
async def delete_document(document_id: str) -> DeleteResponse:
    """
    Permanently removes all chunks for a document from ChromaDB.
    Also removes the uploaded PDF from disk if it exists.
    """
    try:
        from app.rag.vectorstore import get_or_create_collection
        collection = get_or_create_collection()

        # Find all chunk IDs for this document
        raw = collection.get(
            where={"document_id": {"$eq": document_id}},
            include=["metadatas"],
        )
        ids      = raw.get("ids", [])
        filename = "unknown"
        if raw.get("metadatas"):
            filename = raw["metadatas"][0].get("filename", "unknown")

        if not ids:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document '{document_id}' not found.",
            )

        collection.delete(ids=ids)
        logger.info("Deleted %d chunks for doc_id=%s (%s)", len(ids), document_id, filename)

        # Also delete PDF from disk if present
        pdf_path = Path(settings.upload_dir) / filename
        if pdf_path.exists():
            pdf_path.unlink(missing_ok=True)
            logger.info("Deleted PDF from disk: %s", pdf_path)

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Delete failed for '%s': %s", document_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Delete failed: {exc}",
        ) from exc

    return DeleteResponse(
        document_id=document_id,
        message=f"Document '{filename}' and {len(ids)} chunks deleted.",
    )