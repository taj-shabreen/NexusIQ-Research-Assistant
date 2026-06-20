"""
documents.py — PDF upload, listing, deletion.

CRITICAL FIX: No circular import from app.main.
Duplicate detection via SHA-256 content hash.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from fastapi import APIRouter, File, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from app.config import settings

logger = logging.getLogger("nexusiq.api.documents")
router = APIRouter()

UPLOAD_DIR = Path(settings.upload_dir)  # mkdir deferred to request time


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    x_session_id: str = Header(..., alias="X-Session-Id"),
):
    from app.rag.ingestion import ingest_document  # deferred — avoids startup import
    if not x_session_id or not x_session_id.strip():
        raise HTTPException(status_code=400, detail="X-Session-Id header is required.")
    session_id = x_session_id.strip()

    # Scope on-disk storage per session so two sessions uploading a
    # same-named file (e.g. "report.pdf") never overwrite each other.
    session_dir = UPLOAD_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)   # deferred — ensures disk is mounted

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    file_hash  = _sha256(content)
    dest_path  = session_dir / file.filename
    hash_file  = session_dir / f".{file.filename}.sha256"

    # Duplicate detection — scoped to this session only
    if dest_path.exists() and hash_file.exists():
        if hash_file.read_text().strip() == file_hash:
            try:
                from app.rag.vectorstore import get_or_create_collection
                collection  = get_or_create_collection()
                result      = collection.get(
                    where={"$and": [{"filename": file.filename}, {"session_id": session_id}]},
                    include=["metadatas"],
                )
                chunk_count = len(result.get("ids") or [])
            except Exception:
                chunk_count = 0
            return JSONResponse(content={
                "message":   f"'{file.filename}' is already indexed ({chunk_count} chunks).",
                "filename":  file.filename,
                "chunks":    chunk_count,
                "duplicate": True,
            })

    dest_path.write_bytes(content)
    hash_file.write_text(file_hash)
    logger.info("Saved: %s (%d bytes) [session=%s]", file.filename, len(content), session_id)

    try:
        chunk_count = await ingest_document(str(dest_path), file.filename, session_id)
    except Exception as exc:
        dest_path.unlink(missing_ok=True)
        hash_file.unlink(missing_ok=True)
        logger.exception("Ingestion failed for %s", file.filename)
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {exc}") from exc

    return JSONResponse(content={
        "message":   f"'{file.filename}' indexed successfully.",
        "filename":  file.filename,
        "chunks":    chunk_count,
        "duplicate": False,
    })


@router.get("/")
async def list_documents(x_session_id: str = Header(..., alias="X-Session-Id")):
    if not x_session_id or not x_session_id.strip():
        raise HTTPException(status_code=400, detail="X-Session-Id header is required.")
    session_id = x_session_id.strip()

    try:
        from app.rag.vectorstore import get_or_create_collection
        collection = get_or_create_collection()
        result     = collection.get(where={"session_id": session_id}, include=["metadatas"])
        metadatas  = result.get("metadatas") or []
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    doc_chunks: dict = {}
    for m in metadatas:
        fname = m.get("filename", "unknown")
        doc_chunks[fname] = doc_chunks.get(fname, 0) + 1

    return {
        "documents": [
            {"filename": k, "chunks": v}
            for k, v in sorted(doc_chunks.items())
        ],
        "total": len(doc_chunks),
    }


@router.delete("/{filename}")
async def delete_document(filename: str, x_session_id: str = Header(..., alias="X-Session-Id")):
    if not x_session_id or not x_session_id.strip():
        raise HTTPException(status_code=400, detail="X-Session-Id header is required.")
    session_id = x_session_id.strip()

    try:
        from app.rag.vectorstore import get_or_create_collection
        collection = get_or_create_collection()
        result     = collection.get(
            where={"$and": [{"filename": filename}, {"session_id": session_id}]},
            include=["metadatas"],
        )
        ids        = result.get("ids") or []
        if ids:
            collection.delete(ids=ids)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    session_dir  = UPLOAD_DIR / session_id
    file_existed = (session_dir / filename).exists()
    (session_dir / filename).unlink(missing_ok=True)
    (session_dir / f".{filename}.sha256").unlink(missing_ok=True)

    if not ids and not file_existed:
        # Nothing matched — likely a wrong/stale filename was sent.
        # Surface this clearly instead of returning a fake success message.
        raise HTTPException(
            status_code=404,
            detail=f"No document found with filename '{filename}' — 0 chunks and no file matched.",
        )

    return {
        "message":       f"'{filename}' deleted.",
        "filename":      filename,
        "chunks_deleted": len(ids),
    }