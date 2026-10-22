"""
app/api/projects.py
Project CRUD router with membership management.
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
from app.db.models import UserRole

router = APIRouter(prefix="/api/projects", tags=["projects"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name: str
    description: str = ""


class ProjectResponse(BaseModel):
    id: int
    name: str
    description: str | None
    created_by: int

    model_config = {"from_attributes": True}


class MemberAdd(BaseModel):
    user_id: int
    role: UserRole = UserRole.VIEWER


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/", response_model=ProjectResponse, status_code=201)
def create_project(
    body: ProjectCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_permission("create_project")),
):
    project = crud.create_project(db, body.name, body.description, current_user.user_id)
    log_action(db, current_user.user_id, project.id, "create_project", "project", project.id,
               ip_address=request.client.host if request.client else None)
    db.commit()
    return project


@router.get("/", response_model=list[ProjectResponse])
def list_my_projects(
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    return crud.list_projects_for_user(db, current_user.user_id)


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    _assert_member(db, current_user.user_id, project_id)
    project = crud.get_project(db, project_id)
    if not project:
        raise NotFoundError("Project")
    return project


@router.post("/{project_id}/members", status_code=201)
def add_member(
    project_id: int,
    body: MemberAdd,
    request: Request,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_permission("create_project")),
):
    _assert_member(db, current_user.user_id, project_id)
    member = crud.add_project_member(db, project_id, body.user_id, body.role)
    log_action(db, current_user.user_id, project_id, "add_member", "project_member", member.id,
               detail={"user_id": body.user_id, "role": body.role},
               ip_address=request.client.host if request.client else None)
    db.commit()
    return {"status": "added", "member_id": member.id}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _assert_member(db: Session, user_id: int, project_id: int) -> None:
    if not crud.user_in_project(db, user_id, project_id):
        raise AuthorizationError("You are not a member of this project")
