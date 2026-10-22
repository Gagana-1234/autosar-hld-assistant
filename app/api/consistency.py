"""
app/api/consistency.py
Consistency check router: trigger checks and list issues.
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
from app.db.models import IssueSeverity, IssueStatus

router = APIRouter(prefix="/api/consistency", tags=["consistency"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class IssueResponse(BaseModel):
    id: int
    document_id: int
    rule_id: str
    severity: IssueSeverity
    description: str
    evidence_json: str
    status: IssueStatus

    model_config = {"from_attributes": True}


class ConsistencyRunResult(BaseModel):
    document_id: int
    issues_found: int


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/run/{document_id}", response_model=ConsistencyRunResult)
def run_checks(
    document_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_permission("review_entity")),
):
    """Run consistency validation rules on extracted entities."""
    doc = crud.get_document(db, document_id)
    if not doc:
        raise NotFoundError("Document")
    if not crud.user_in_project(db, current_user.user_id, doc.project_id):
        raise AuthorizationError("Not a member of this project")

    from app.validation.consistency import run_consistency_checks
    issues = run_consistency_checks(db, document_id)

    log_action(
        db,
        user_id=current_user.user_id,
        project_id=doc.project_id,
        action="run_consistency_checks",
        resource_type="document",
        resource_id=document_id,
        detail={"issues_found": len(issues)},
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return ConsistencyRunResult(document_id=document_id, issues_found=len(issues))


@router.get("/{document_id}", response_model=list[IssueResponse])
def list_issues(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    """List all consistency issues for a document."""
    doc = crud.get_document(db, document_id)
    if not doc:
        raise NotFoundError("Document")
    if not crud.user_in_project(db, current_user.user_id, doc.project_id):
        raise AuthorizationError("Not a member of this project")
    return crud.list_issues(db, document_id)


@router.put("/issue/{issue_id}/status")
def update_issue_status(
    issue_id: int,
    new_status: IssueStatus,
    request: Request,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_permission("review_entity")),
):
    """Update the status of a consistency issue (confirm/dismiss)."""
    from app.db.models import ConsistencyIssue

    issue = db.query(ConsistencyIssue).filter(ConsistencyIssue.id == issue_id).first()
    if not issue:
        raise NotFoundError("ConsistencyIssue")
    issue.status = new_status
    db.commit()

    log_action(
        db,
        user_id=current_user.user_id,
        project_id=None,
        action="update_issue_status",
        resource_type="consistency_issue",
        resource_id=issue_id,
        detail={"new_status": new_status},
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return {"status": "updated", "issue_id": issue_id, "new_status": new_status}
