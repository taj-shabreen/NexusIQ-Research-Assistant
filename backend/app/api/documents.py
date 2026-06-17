"""
documents.py — PDF upload, listing, deletion.

CRITICAL FIX: No circular import from app.main.
Duplicate detection via SHA-256 content hash.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from app.config import settings

logger = logging.getLogger("nexusiq.api.documents")
router = APIRouter()

UPLOAD_DIR = Path(settings.upload_dir)  # mkdir deferred to request time


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    from app.rag.ingestion import ingest_document  # deferred — avoids startup import
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)   # deferred — ensures disk is mounted
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    file_hash  = _sha256(content)
    dest_path  = UPLOAD_DIR / file.filename
    hash_file  = UPLOAD_DIR / f".{file.filename}.sha256"

    # Duplicate detection
    if dest_path.exists() and hash_file.exists():
        if hash_file.read_text().strip() == file_hash:
            try:
                from app.rag.vectorstore import get_or_create_collection
                collection  = get_or_create_collection()
                result      = collection.get(
                    where={"filename": file.filename}, include=["metadatas"]
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
    logger.info("Saved: %s (%d bytes)", file.filename, len(content))

    try:
        chunk_count = await ingest_document(str(dest_path), file.filename)
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
async def list_documents():
    try:
        from app.rag.vectorstore import get_or_create_collection
        collection = get_or_create_collection()
        result     = collection.get(include=["metadatas"])
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
async def delete_document(filename: str):
    try:
        from app.rag.vectorstore import get_or_create_collection
        collection = get_or_create_collection()
        result     = collection.get(where={"filename": filename}, include=["metadatas"])
        ids        = result.get("ids") or []
        if ids:
            collection.delete(ids=ids)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    (UPLOAD_DIR / filename).unlink(missing_ok=True)
    (UPLOAD_DIR / f".{filename}.sha256").unlink(missing_ok=True)
    return {"message": f"'{filename}' deleted.", "filename": filename}