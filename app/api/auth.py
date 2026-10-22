"""
app/api/auth.py
Authentication router: login, token refresh, user registration (admin only).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.core.audit import log_action
from app.core.exceptions import AuthenticationError, AuthorizationError
from app.core.security import (
    Role,
    TokenData,
    create_access_token,
    get_current_user,
    require_permission,
    verify_password,
)
from app.db.crud import create_user, get_user_by_username, list_users
from app.db.database import get_db
from app.db.models import UserRole

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    username: str


class UserCreateRequest(BaseModel):
    username: str
    email: EmailStr
    password: str
    role: UserRole = UserRole.VIEWER


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    role: UserRole
    is_active: bool

    model_config = {"from_attributes": True}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/token", response_model=Token, summary="Login and obtain JWT")
def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = get_user_by_username(db, form_data.username)
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise AuthenticationError("Incorrect username or password")
    if not user.is_active:
        raise AuthorizationError("User account is disabled")

    # Eagerly read scalar fields before commit to prevent lazy-load
    # across session boundaries (especially in tests with in-memory DBs)
    user_id = user.id
    role_value = user.role.value
    username = user.username

    token = create_access_token(
        {"sub": str(user_id), "username": username, "role": role_value}
    )
    log_action(
        db,
        user_id=user_id,
        project_id=None,
        action="login",
        resource_type="user",
        resource_id=user_id,
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return Token(access_token=token, role=role_value, username=username)


@router.post(
    "/register",
    response_model=UserResponse,
    summary="Create a new user (Admin only)",
    status_code=201,
)
def register_user(
    body: UserCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_permission("create_user")),
):
    existing = get_user_by_username(db, body.username)
    if existing:
        from app.core.exceptions import ConflictError
        raise ConflictError("Username already taken")

    user = create_user(db, body.username, body.email, body.password, body.role)
    log_action(
        db,
        user_id=current_user.user_id,
        project_id=None,
        action="create_user",
        resource_type="user",
        resource_id=user.id,
        detail={"new_username": body.username, "role": body.role},
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return user


@router.get("/me", response_model=UserResponse, summary="Get current user info")
def me(
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.db.crud import get_user_by_id
    user = get_user_by_id(db, current_user.user_id)
    if not user:
        raise AuthenticationError()
    return user


@router.get("/users", response_model=list[UserResponse], summary="List all users (Admin only)")
def list_all_users(
    db: Session = Depends(get_db),
    _: TokenData = Depends(require_permission("manage_users")),
):
    return list_users(db)
