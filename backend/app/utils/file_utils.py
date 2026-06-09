"""
NexusIQ — utils/file_utils.py

File validation and safe upload utilities used by the documents API.

Provides:
  - validate_pdf()       — MIME type + size guard for UploadFile objects
  - safe_filename()      — sanitise user-supplied filenames
  - ensure_upload_dir()  — create the upload directory if absent
  - compute_file_hash()  — MD5 hash of an on-disk file (idempotency check)
"""

import hashlib
import logging
import re
import unicodedata
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.config import settings

logger = logging.getLogger("nexusiq.file_utils")

# ── Constants ──────────────────────────────────────────────────────

# FIX: was settings.MAX_UPLOAD_SIZE_MB — correct attr is max_file_size_mb (alias for max_upload_size_mb)
_MAX_BYTES      = settings.max_file_size_mb * 1024 * 1024
_ALLOWED_MIME   = {"application/pdf"}
_ALLOWED_SUFFIX = ".pdf"

# Characters not allowed in filenames
_UNSAFE_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


# ── Validators ─────────────────────────────────────────────────────

def validate_pdf(file: UploadFile) -> None:
    """
    Validate that an uploaded file is a safe, non-oversized PDF.

    Checks:
      1. File extension must be .pdf (case-insensitive).
      2. Content-Type header must be application/pdf.
      3. Reported file size (when available) must be within max_upload_size_mb.

    Args:
        file: FastAPI UploadFile object from a multipart/form-data request.

    Raises:
        HTTPException 400: Invalid extension or MIME type.
        HTTPException 413: File exceeds the configured size limit.
    """
    filename = file.filename or ""

    # 1. Extension check
    if not filename.lower().endswith(_ALLOWED_SUFFIX):
        raise HTTPException(
            status_code=400,
            detail=f"'{filename}' is not a PDF. Only .pdf files are accepted.",
        )

    # 2. MIME type check (content_type may be None for some clients)
    if file.content_type and file.content_type not in _ALLOWED_MIME:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid content-type '{file.content_type}' for '{filename}'. "
                "Expected application/pdf."
            ),
        )

    # 3. Size check (size is set by Starlette when Content-Length is provided)
    if file.size is not None and file.size > _MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"'{filename}' is {file.size / 1_048_576:.1f} MB, which exceeds the "
                f"{settings.max_file_size_mb} MB limit."  # FIX: correct attr name
            ),
        )

    logger.debug("File '%s' passed validation ✓", filename)


# ── Filename sanitisation ──────────────────────────────────────────

def safe_filename(name: str) -> str:
    """
    Sanitise a user-supplied filename for safe filesystem storage.

    Steps:
      1. NFC unicode normalisation.
      2. Replace path separators and control characters with underscores.
      3. Strip leading dots (hidden-file prevention).
      4. Collapse multiple consecutive underscores.
      5. Truncate to 200 characters (filesystem safety).
      6. Ensure the .pdf extension is preserved.

    Args:
        name: Raw filename string (e.g. from UploadFile.filename).

    Returns:
        Sanitised filename string.
    """
    # Normalise unicode
    name = unicodedata.normalize("NFC", name)

    # Replace unsafe characters with underscores
    name = _UNSAFE_CHARS_RE.sub("_", name)

    # Strip leading dots
    name = name.lstrip(".")

    # Collapse repeated underscores
    name = re.sub(r"_+", "_", name)

    # Ensure it ends with .pdf
    stem   = Path(name).stem[:190]      # leave room for extension
    suffix = ".pdf"
    name   = f"{stem}{suffix}"

    if not name or name == ".pdf":
        name = "upload.pdf"

    return name


# ── Directory helpers ──────────────────────────────────────────────

def ensure_upload_dir() -> Path:
    """
    Ensure the configured upload directory exists, creating it if needed.

    Returns:
        Resolved Path to the upload directory.
    """
    # FIX: was settings.UPLOAD_DIR — correct attr is settings.upload_dir
    upload_dir = Path(settings.upload_dir).resolve()
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir


# ── File hashing ───────────────────────────────────────────────────

def compute_file_hash(file_path: Path, algorithm: str = "md5") -> str:
    """
    Compute a hex digest hash of a file on disk.

    Used to generate stable document IDs and detect duplicate uploads.

    Args:
        file_path: Path to the file.
        algorithm: Hash algorithm name supported by hashlib (default "md5").

    Returns:
        Full hex digest string.

    Raises:
        FileNotFoundError: If file_path does not exist.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"Cannot hash non-existent file: {file_path}")

    h = hashlib.new(algorithm)
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)

    return h.hexdigest()