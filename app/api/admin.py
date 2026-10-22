"""
app/api/admin.py
Admin router: audit log viewer, user deactivation, system stats.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.security import TokenData, require_permission
from app.db import crud
from app.db.database import get_db

router = APIRouter(prefix="/api/admin", tags=["admin"])


class AuditEntry(BaseModel):
    id: int
    user_id: int
    project_id: int | None
    action: str
    resource_type: str
    resource_id: str | None
    detail_json: str | None
    timestamp: str
    ip_address: str | None

    model_config = {"from_attributes": True}


@router.get("/audit-log", response_model=list[AuditEntry])
def get_audit_log(
    project_id: int | None = Query(None),
    user_id: int | None = Query(None),
    skip: int = 0,
    limit: int = 200,
    db: Session = Depends(get_db),
    _: TokenData = Depends(require_permission("view_audit_log")),
):
    entries = crud.list_audit_log(db, project_id=project_id, user_id=user_id, skip=skip, limit=limit)
    return [
        AuditEntry(
            id=e.id,
            user_id=e.user_id,
            project_id=e.project_id,
            action=e.action,
            resource_type=e.resource_type,
            resource_id=e.resource_id,
            detail_json=e.detail_json,
            timestamp=e.timestamp.isoformat(),
            ip_address=e.ip_address,
        )
        for e in entries
    ]


@router.delete("/users/{user_id}", summary="Deactivate a user (Admin only)")
def deactivate_user(
    user_id: int,
    db: Session = Depends(get_db),
    _: TokenData = Depends(require_permission("delete_user")),
):
    user = crud.deactivate_user(db, user_id)
    if not user:
        from app.core.exceptions import NotFoundError
        raise NotFoundError("User")
    return {"status": "deactivated", "user_id": user_id}
