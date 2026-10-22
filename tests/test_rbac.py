"""
tests/test_rbac.py
RBAC and authentication tests for Phase 1.
Covers: password hashing, JWT round-trip, role enforcement on all permissions.
"""
from __future__ import annotations

import pytest
from jose import jwt

from app.core.config import get_settings
from app.core.security import (
    PERMISSIONS,
    Role,
    TokenData,
    check_permission,
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.core.exceptions import AuthenticationError, AuthorizationError
from tests.conftest import auth_headers, get_token


# ── Password hashing ──────────────────────────────────────────────────────────

class TestPasswordHashing:
    def test_hash_is_not_plaintext(self):
        hashed = hash_password("secret123")
        assert hashed != "secret123"

    def test_verify_correct_password(self):
        hashed = hash_password("secret123")
        assert verify_password("secret123", hashed) is True

    def test_verify_wrong_password(self):
        hashed = hash_password("secret123")
        assert verify_password("wrongpassword", hashed) is False

    def test_two_hashes_differ(self):
        """bcrypt uses a random salt — same input, different hash."""
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2


# ── JWT ───────────────────────────────────────────────────────────────────────

class TestJWT:
    def test_token_roundtrip(self):
        token = create_access_token({"sub": "1", "username": "alice", "role": "admin"})
        payload = decode_token(token)
        assert payload["sub"] == "1"
        assert payload["username"] == "alice"
        assert payload["role"] == "admin"

    def test_tampered_token_raises(self):
        token = create_access_token({"sub": "1", "username": "alice", "role": "admin"})
        tampered = token[:-4] + "XXXX"
        with pytest.raises(AuthenticationError):
            decode_token(tampered)

    def test_wrong_secret_raises(self):
        token = jwt.encode({"sub": "1"}, "wrong-secret", algorithm="HS256")
        with pytest.raises(AuthenticationError):
            decode_token(token)


# ── Permission checks ─────────────────────────────────────────────────────────

class TestPermissions:
    def _make_user(self, role: Role) -> TokenData:
        return TokenData(user_id=1, username="test", role=role)

    # Admin can do everything
    def test_admin_can_create_project(self):
        check_permission(self._make_user(Role.ADMIN), "create_project")  # no raise

    def test_admin_can_create_user(self):
        check_permission(self._make_user(Role.ADMIN), "create_user")

    def test_admin_can_view_audit_log(self):
        check_permission(self._make_user(Role.ADMIN), "view_audit_log")

    # Viewer restrictions
    def test_viewer_cannot_create_project(self):
        with pytest.raises(AuthorizationError):
            check_permission(self._make_user(Role.VIEWER), "create_project")

    def test_viewer_cannot_upload_document(self):
        with pytest.raises(AuthorizationError):
            check_permission(self._make_user(Role.VIEWER), "upload_document")

    def test_viewer_cannot_approve_document(self):
        with pytest.raises(AuthorizationError):
            check_permission(self._make_user(Role.VIEWER), "approve_document")

    def test_viewer_cannot_export(self):
        with pytest.raises(AuthorizationError):
            check_permission(self._make_user(Role.VIEWER), "export")

    def test_viewer_can_run_query(self):
        check_permission(self._make_user(Role.VIEWER), "run_query")  # no raise

    # Architect
    def test_architect_can_upload(self):
        check_permission(self._make_user(Role.ARCHITECT), "upload_document")

    def test_architect_can_approve_document(self):
        check_permission(self._make_user(Role.ARCHITECT), "approve_document")

    def test_architect_cannot_create_user(self):
        with pytest.raises(AuthorizationError):
            check_permission(self._make_user(Role.ARCHITECT), "create_user")

    # Developer
    def test_developer_can_upload(self):
        check_permission(self._make_user(Role.DEVELOPER), "upload_document")

    def test_developer_cannot_approve_document(self):
        with pytest.raises(AuthorizationError):
            check_permission(self._make_user(Role.DEVELOPER), "approve_document")

    # Tester
    def test_tester_can_review_entity(self):
        check_permission(self._make_user(Role.TESTER), "review_entity")

    def test_tester_cannot_approve_entity(self):
        with pytest.raises(AuthorizationError):
            check_permission(self._make_user(Role.TESTER), "approve_entity")

    def test_tester_cannot_upload_document(self):
        with pytest.raises(AuthorizationError):
            check_permission(self._make_user(Role.TESTER), "upload_document")

    # Manager
    def test_manager_can_view_audit_log(self):
        check_permission(self._make_user(Role.MANAGER), "view_audit_log")

    def test_manager_cannot_approve_document(self):
        with pytest.raises(AuthorizationError):
            check_permission(self._make_user(Role.MANAGER), "approve_document")

    def test_manager_cannot_create_user(self):
        with pytest.raises(AuthorizationError):
            check_permission(self._make_user(Role.MANAGER), "create_user")


# ── API-level auth tests ──────────────────────────────────────────────────────

class TestAuthAPI:
    @pytest.mark.asyncio
    async def test_login_success(self, client, admin_user):
        resp = await client.post(
            "/api/auth/token",
            data={"username": "test_admin", "password": "password123"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["role"] == "admin"

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client, admin_user):
        resp = await client.post(
            "/api/auth/token",
            data={"username": "test_admin", "password": "wrongpassword"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_login_unknown_user(self, client):
        resp = await client.post(
            "/api/auth/token",
            data={"username": "nobody", "password": "x"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_me_returns_current_user(self, client, admin_user):
        from tests.conftest import get_token, auth_headers
        token = await get_token(client, "test_admin")
        resp = await client.get("/api/auth/me", headers=auth_headers(token))
        assert resp.status_code == 200
        assert resp.json()["username"] == "test_admin"

    @pytest.mark.asyncio
    async def test_me_without_token_is_401(self, client):
        resp = await client.get("/api/auth/me")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_register_user_as_admin(self, client, admin_user):
        from tests.conftest import get_token, auth_headers
        token = await get_token(client, "test_admin")
        resp = await client.post(
            "/api/auth/register",
            json={"username": "newdev", "email": "dev@test.com", "password": "pass", "role": "developer"},
            headers=auth_headers(token),
        )
        assert resp.status_code == 201
        assert resp.json()["role"] == "developer"

    @pytest.mark.asyncio
    async def test_register_user_as_viewer_is_403(self, client, viewer_user):
        from tests.conftest import get_token, auth_headers
        token = await get_token(client, "test_viewer")
        resp = await client.post(
            "/api/auth/register",
            json={"username": "hacker", "email": "h@h.com", "password": "x"},
            headers=auth_headers(token),
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_list_users_as_admin(self, client, admin_user):
        from tests.conftest import get_token, auth_headers
        token = await get_token(client, "test_admin")
        resp = await client.get("/api/auth/users", headers=auth_headers(token))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_list_users_as_viewer_is_403(self, client, viewer_user):
        from tests.conftest import get_token, auth_headers
        token = await get_token(client, "test_viewer")
        resp = await client.get("/api/auth/users", headers=auth_headers(token))
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_health_endpoint(self, client):
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
