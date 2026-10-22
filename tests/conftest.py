"""
tests/conftest.py
Shared pytest fixtures: in-memory SQLite DB, async ASGI test client, seeded users.
"""
from __future__ import annotations

import os
import pytest
import pytest_asyncio
import httpx

os.environ["TESTING"] = "1"  # Disables lifespan init_db in app/api/main.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.main import create_app
from app.db.database import get_db
from app.db.models import Base, UserRole
from app.db.crud import create_user


# ── In-memory test database ───────────────────────────────────────────────────

TEST_DB_URL = "sqlite:///:memory:"


import uuid

@pytest.fixture(scope="function")
def engine():
    """Shared-cache named in-memory SQLite per test — visible to all threads."""
    db_name = f"test_{uuid.uuid4().hex}"
    url = f"file:{db_name}?mode=memory&cache=shared"
    eng = create_engine(
        f"sqlite:///{url}",
        connect_args={"check_same_thread": False, "uri": True},
    )
    Base.metadata.create_all(bind=eng)
    yield eng
    Base.metadata.drop_all(bind=eng)
    eng.dispose()


@pytest.fixture(scope="function")
def db(engine):
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestSession()
    yield session
    session.rollback()
    session.close()


# ── Async ASGI test client (works with any httpx version) ─────────────────────

@pytest_asyncio.fixture(scope="function")
async def client(db):
    from app.db.models import Base

    # Tables are already created by engine fixture; just wire up the override
    app = create_app()

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c


# ── Seeded users ──────────────────────────────────────────────────────────────

@pytest.fixture(scope="function")
def admin_user(db):
    return create_user(db, "test_admin", "admin@test.com", "password123", UserRole.ADMIN)


@pytest.fixture(scope="function")
def architect_user(db):
    return create_user(db, "test_architect", "arch@test.com", "password123", UserRole.ARCHITECT)


@pytest.fixture(scope="function")
def viewer_user(db):
    return create_user(db, "test_viewer", "viewer@test.com", "password123", UserRole.VIEWER)


@pytest.fixture(scope="function")
def tester_user(db):
    return create_user(db, "test_tester", "tester@test.com", "password123", UserRole.TESTER)


# ── Token helpers ─────────────────────────────────────────────────────────────

async def get_token(client: httpx.AsyncClient, username: str, password: str = "password123") -> str:
    resp = await client.post(
        "/api/auth/token",
        data={"username": username, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
