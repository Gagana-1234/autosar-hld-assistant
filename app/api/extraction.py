"""
app/api/extraction.py
Entity extraction router: trigger extraction, list entities, update entity review.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.audit import log_action
from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.security import TokenData, get_current_user, require_permission
from app.db import crud
from app.db.database import get_db
from app.db.models import ReviewStatus

router = APIRouter(prefix="/api/extraction", tags=["extraction"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class EntityResponse(BaseModel):
    id: int
    document_id: int
    entity_type: str
    name: str
    data_json: str
    confidence: float
    page: int | None
    section: str | None
    review_status: ReviewStatus
    requires_human_review: bool

    model_config = {"from_attributes": True}


class EntityReviewRequest(BaseModel):
    status: ReviewStatus
    comment: str | None = None
    new_data_json: str | None = None


class ExtractionTriggerRequest(BaseModel):
    document_id: int
    use_llm: bool = True


class ExtractionResult(BaseModel):
    document_id: int
    entities_extracted: int


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/run", response_model=ExtractionResult, status_code=201)
def trigger_extraction(
    body: ExtractionTriggerRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_permission("upload_document")),
):
    """Trigger entity extraction on a document's chunks."""
    doc = crud.get_document(db, body.document_id)
    if not doc:
        raise NotFoundError("Document")
    if not crud.user_in_project(db, current_user.user_id, doc.project_id):
        raise AuthorizationError("Not a member of this project")

    from app.extraction.entity_extractor import extract_entities_for_document
    count = extract_entities_for_document(db, body.document_id, use_llm=body.use_llm)

    log_action(
        db,
        user_id=current_user.user_id,
        project_id=doc.project_id,
        action="run_extraction",
        resource_type="document",
        resource_id=doc.id,
        detail={"entities_extracted": count, "use_llm": body.use_llm},
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return ExtractionResult(document_id=body.document_id, entities_extracted=count)


@router.get("/{document_id}", response_model=list[EntityResponse])
def list_entities(
    document_id: int,
    entity_type: str | None = None,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    """List extracted entities for a document."""
    doc = crud.get_document(db, document_id)
    if not doc:
        raise NotFoundError("Document")
    if not crud.user_in_project(db, current_user.user_id, doc.project_id):
        raise AuthorizationError("Not a member of this project")
    return crud.list_entities(db, document_id, entity_type=entity_type)


@router.put("/entity/{entity_id}/review", response_model=EntityResponse)
def review_entity(
    entity_id: int,
    body: EntityReviewRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_permission("review_entity")),
):
    """Review (accept/reject/edit) an extracted entity."""
    entity = crud.update_entity_review(
        db,
        entity_id=entity_id,
        reviewer_id=current_user.user_id,
        status=body.status,
        comment=body.comment,
        new_data_json=body.new_data_json,
    )
    if not entity:
        raise NotFoundError("Entity")

    log_action(
        db,
        user_id=current_user.user_id,
        project_id=None,
        action="review_entity",
        resource_type="entity",
        resource_id=entity_id,
        detail={"status": body.status, "comment": body.comment},
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return entity
