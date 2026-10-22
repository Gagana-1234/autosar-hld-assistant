"""
app/api/documents.py
Document upload, ingestion, approval, and listing endpoints.
"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.audit import log_action
from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.security import TokenData, get_current_user, require_permission
from app.db import crud
from app.db.database import get_db
from app.db.models import DocumentStatus
from app.ingestion.pipeline import run_ingestion, save_upload
from app.ingestion.validator import validate_upload

router = APIRouter(prefix="/api/documents", tags=["documents"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class DocumentResponse(BaseModel):
    id: int
    project_id: int
    filename: str
    version_label: str
    status: DocumentStatus
    page_count: int | None
    sha256: str | None
    ocr_used: bool
    uploaded_by: int

    model_config = {"from_attributes": True}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "/upload",
    response_model=DocumentResponse,
    status_code=201,
    summary="Upload and ingest a PDF document",
)
async def upload_document(
    request: Request,
    background_tasks: BackgroundTasks,
    project_id: int = Form(...),
    version_label: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_permission("upload_document")),
):
    # Project membership check
    if not crud.user_in_project(db, current_user.user_id, project_id):
        raise AuthorizationError("You are not a member of this project")

    # Read file bytes
    content = await file.read()

    # Validate
    sha256 = validate_upload(file, project_id, version_label, db, content)

    # Save raw file
    storage_path = save_upload(content, file.filename or "upload.pdf", project_id)

    # Create DB record
    doc = crud.create_document(
        db,
        project_id=project_id,
        filename=file.filename or "upload.pdf",
        version_label=version_label,
        uploaded_by=current_user.user_id,
        sha256=sha256,
        storage_path=storage_path,
    )

    # Log upload
    log_action(
        db,
        user_id=current_user.user_id,
        project_id=project_id,
        action="upload_document",
        resource_type="document",
        resource_id=doc.id,
        detail={"filename": doc.filename, "version": version_label},
        ip_address=request.client.host if request.client else None,
    )
    db.commit()

    # Run ingestion in background
    background_tasks.add_task(_ingest_background, doc.id, content)

    return doc


def _ingest_background(doc_id: int, content: bytes) -> None:
    """Background task: runs ingestion pipeline outside the request session."""
    from app.db.database import SessionLocal
    db = SessionLocal()
    try:
        doc = crud.get_document(db, doc_id)
        if doc:
            run_ingestion(db, doc, content)
    except Exception as exc:
        from loguru import logger
        logger.error("Background ingestion failed for doc {}: {}", doc_id, exc)
    finally:
        db.close()


@router.post("/{doc_id}/approve", response_model=DocumentResponse)
def approve_document(
    doc_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_permission("approve_document")),
):
    doc = crud.get_document(db, doc_id)
    if not doc:
        raise NotFoundError("Document")
    if not crud.user_in_project(db, current_user.user_id, doc.project_id):
        raise AuthorizationError("Not a member of this project")

    doc = crud.approve_document(db, doc_id, current_user.user_id)
    log_action(
        db,
        user_id=current_user.user_id,
        project_id=doc.project_id,
        action="approve_document",
        resource_type="document",
        resource_id=doc_id,
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return doc


@router.get("/{project_id}", response_model=list[DocumentResponse])
def list_documents(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    if not crud.user_in_project(db, current_user.user_id, project_id):
        raise AuthorizationError("Not a member of this project")
    return crud.list_documents(db, project_id)


@router.get("/doc/{doc_id}", response_model=DocumentResponse)
def get_document(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    doc = crud.get_document(db, doc_id)
    if not doc:
        raise NotFoundError("Document")
    if not crud.user_in_project(db, current_user.user_id, doc.project_id):
        raise AuthorizationError("Not a member of this project")
    return doc
