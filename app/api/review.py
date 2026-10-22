"""
app/api/review.py
Review queue router: list pending reviews, resolve review items.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.audit import log_action
from app.core.exceptions import NotFoundError
from app.core.security import TokenData, require_permission
from app.db import crud
from app.db.database import get_db
from app.db.models import ReviewStatus

router = APIRouter(prefix="/api/review", tags=["review"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class ReviewItemResponse(BaseModel):
    id: int
    entity_id: int
    queue_reason: str
    assigned_to: int | None
    status: ReviewStatus
    comment: str | None
    created_at: str

    model_config = {"from_attributes": True}


class ResolveReviewRequest(BaseModel):
    status: ReviewStatus
    comment: str | None = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/{project_id}", response_model=list[ReviewItemResponse])
def list_pending_reviews(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_permission("review_entity")),
):
    """List all pending review items for a project."""
    if not crud.user_in_project(db, current_user.user_id, project_id):
        from app.core.exceptions import AuthorizationError
        raise AuthorizationError("Not a member of this project")

    items = crud.list_pending_review_items(db, project_id)
    return [
        ReviewItemResponse(
            id=item.id,
            entity_id=item.entity_id,
            queue_reason=item.queue_reason,
            assigned_to=item.assigned_to,
            status=item.status,
            comment=item.comment,
            created_at=item.created_at.isoformat(),
        )
        for item in items
    ]


@router.put("/{review_id}/resolve", response_model=ReviewItemResponse)
def resolve_review(
    review_id: int,
    body: ResolveReviewRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_permission("review_entity")),
):
    """Resolve a review queue item."""
    from datetime import datetime, timezone
    from app.db.models import ReviewItem

    item = db.query(ReviewItem).filter(ReviewItem.id == review_id).first()
    if not item:
        raise NotFoundError("ReviewItem")

    item.status = body.status
    item.comment = body.comment
    item.resolved_at = datetime.now(timezone.utc)
    db.commit()

    log_action(
        db,
        user_id=current_user.user_id,
        project_id=None,
        action="resolve_review",
        resource_type="review_item",
        resource_id=review_id,
        detail={"status": body.status, "comment": body.comment},
        ip_address=request.client.host if request.client else None,
    )
    db.commit()

    return ReviewItemResponse(
        id=item.id,
        entity_id=item.entity_id,
        queue_reason=item.queue_reason,
        assigned_to=item.assigned_to,
        status=item.status,
        comment=item.comment,
        created_at=item.created_at.isoformat(),
    )
