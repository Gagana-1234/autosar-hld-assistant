"""
app/core/security.py
Password hashing, JWT creation/verification, and RBAC role enforcement.

Using python-jose for JWT and bcrypt for passwords.
Permissions dict is hardcoded here for simplicity - if requirements grow
we should move this to the database so admins can configure it.

FIXME: token expiry not being enforced properly on every request
TODO: add refresh token support so users don't get logged out mid-session
"""
from __future__ import annotations

import enum
from datetime import datetime, timedelta, timezone
from typing import Callable

import bcrypt as _bcrypt
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from app.core.config import get_settings
from app.core.exceptions import AuthenticationError, AuthorizationError

# ── Role definitions ──────────────────────────────────────────────────────────

class Role(str, enum.Enum):
    ADMIN = "admin"
    ARCHITECT = "architect"
    DEVELOPER = "developer"
    TESTER = "tester"
    MANAGER = "manager"
    VIEWER = "viewer"


# Role hierarchy: a role includes all roles to its right
ROLE_HIERARCHY: dict[Role, int] = {
    Role.ADMIN: 100,
    Role.ARCHITECT: 80,
    Role.DEVELOPER: 60,
    Role.TESTER: 50,
    Role.MANAGER: 40,
    Role.VIEWER: 10,
}

# Per-action permission sets
PERMISSIONS: dict[str, set[Role]] = {
    "create_project": {Role.ADMIN},
    "delete_project": {Role.ADMIN},
    "create_user": {Role.ADMIN},
    "delete_user": {Role.ADMIN},
    "upload_document": {Role.ADMIN, Role.ARCHITECT, Role.DEVELOPER},
    "approve_document": {Role.ADMIN, Role.ARCHITECT},
    "run_query": {Role.ADMIN, Role.ARCHITECT, Role.DEVELOPER, Role.TESTER, Role.MANAGER, Role.VIEWER},
    "review_entity": {Role.ADMIN, Role.ARCHITECT, Role.DEVELOPER, Role.TESTER},
    "approve_entity": {Role.ADMIN, Role.ARCHITECT},
    "export": {Role.ADMIN, Role.ARCHITECT, Role.DEVELOPER, Role.TESTER, Role.MANAGER},
    "view_audit_log": {Role.ADMIN, Role.MANAGER},
    "compare_revisions": {Role.ADMIN, Role.ARCHITECT, Role.DEVELOPER, Role.TESTER, Role.MANAGER, Role.VIEWER},
    "manage_users": {Role.ADMIN},
}

# ── Crypto ────────────────────────────────────────────────────────────────────

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")


def hash_password(plain: str) -> str:
    return _bcrypt.hashpw(plain.encode(), _bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return _bcrypt.checkpw(plain.encode(), hashed.encode())


# ── JWT ───────────────────────────────────────────────────────────────────────

def create_access_token(data: dict) -> str:
    settings = get_settings()
    payload = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload.update({"exp": expire})
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_token(token: str) -> dict:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except JWTError:
        raise AuthenticationError()


# ── Current user dependency ───────────────────────────────────────────────────

class TokenData:
    def __init__(self, user_id: int, username: str, role: Role):
        self.user_id = user_id
        self.username = username
        self.role = role


def get_current_user(token: str = Depends(oauth2_scheme)) -> TokenData:
    payload = decode_token(token)
    user_id: int | None = payload.get("sub")
    username: str | None = payload.get("username")
    role_str: str | None = payload.get("role")
    if not user_id or not username or not role_str:
        raise AuthenticationError()
    try:
        role = Role(role_str)
    except ValueError:
        raise AuthenticationError(detail="Invalid role in token")
    return TokenData(user_id=int(user_id), username=username, role=role)


# ── Permission check helpers ──────────────────────────────────────────────────

def check_permission(user: TokenData, action: str) -> None:
    allowed = PERMISSIONS.get(action, set())
    if user.role not in allowed:
        raise AuthorizationError(
            detail=f"Role '{user.role}' is not permitted to '{action}'"
        )


def require_permission(action: str) -> Callable:
    """FastAPI dependency factory for permission checks."""
    def dependency(current_user: TokenData = Depends(get_current_user)) -> TokenData:
        check_permission(current_user, action)
        return current_user
    return dependency


def require_role(*roles: Role) -> Callable:
    """FastAPI dependency factory for explicit role list."""
    def dependency(current_user: TokenData = Depends(get_current_user)) -> TokenData:
        if current_user.role not in roles:
            raise AuthorizationError()
        return current_user
    return dependency
