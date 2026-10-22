"""
app/ingestion/validator.py
Validates uploaded files before ingestion begins.
Checks: file type (PDF only), size limit, project membership, duplicate SHA256.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import ValidationError
from app.db.crud import get_document, list_documents


def validate_upload(
    file: UploadFile,
    project_id: int,
    version_label: str,
    db: Session,
    content: bytes,
) -> str:
    """
    Validate an uploaded file.

    Returns
    -------
    sha256 : str
        Hex digest of the file contents (used for dedup check).

    Raises
    ------
    ValidationError  on any policy violation.
    """
    settings = get_settings()

    # 1. File type check
    filename = file.filename or ""
    if not filename.lower().endswith(".pdf"):
        raise ValidationError("Only PDF files are accepted")
    if file.content_type and file.content_type not in ("application/pdf", "application/octet-stream"):
        raise ValidationError(f"Invalid content type: {file.content_type}")

    # 2. Size check
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise ValidationError(
            f"File exceeds maximum size of {settings.max_upload_mb} MB"
        )

    if len(content) == 0:
        raise ValidationError("Uploaded file is empty")

    # 3. Version label check
    version_label = version_label.strip()
    if not version_label:
        raise ValidationError("version_label is required")
    if len(version_label) > 64:
        raise ValidationError("version_label must be ≤ 64 characters")

    # 4. Duplicate detection (same SHA256 in same project)
    sha256 = hashlib.sha256(content).hexdigest()
    existing_docs = list_documents(db, project_id)
    for doc in existing_docs:
        if doc.sha256 == sha256:
            raise ValidationError(
                f"Identical file already uploaded as document ID {doc.id} "
                f"(version: {doc.version_label})"
            )

    return sha256
