"""
app/api/main.py
FastAPI application factory: registers all routers, startup hooks, CORS, and error handlers.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.api import admin, auth, projects
from app.core.config import get_settings
from app.db.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup tasks before the app serves requests."""
    import os
    if not os.environ.get("TESTING"):
        logger.info("Starting AUTOSAR HLD Assistant API...")
        init_db()
        _seed_default_admin()
        logger.info("Startup complete.")
    yield
    logger.info("Shutting down.")


def _seed_default_admin() -> None:
    """Create a default admin user on first run if no users exist."""
    from app.db.crud import create_user, get_user_by_username
    from app.db.database import SessionLocal
    from app.db.models import UserRole

    db = SessionLocal()
    try:
        if not get_user_by_username(db, "admin"):
            create_user(db, "admin", "admin@local.dev", "admin123", UserRole.ADMIN)
            logger.warning(
                "Default admin user created (username=admin, password=admin123). "
                "Change this immediately in production!"
            )
    finally:
        db.close()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="AUTOSAR HLD Document Analysis Assistant",
        description=(
            "Secure, locally-hosted AI assistant for AUTOSAR High-Level Design documents. "
            "Engineers decide — AI assists. Nothing auto-approves."
        ),
        version="1.0.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        lifespan=lifespan,
    )

    # CORS — restrict to local UI in production
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:8501", "http://127.0.0.1:8501"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routers
    app.include_router(auth.router)
    app.include_router(projects.router)
    app.include_router(admin.router)

    # Document & query routers
    from app.api import documents  # noqa: PLC0415
    app.include_router(documents.router)
    from app.api import query  # noqa: PLC0415
    app.include_router(query.router)

    # Entity extraction, review, comparison, consistency, export
    from app.api import extraction, review, comparison, consistency  # noqa: PLC0415
    from app.api import export as export_router  # noqa: PLC0415
    app.include_router(extraction.router)
    app.include_router(review.router)
    app.include_router(comparison.router)
    app.include_router(consistency.router)
    app.include_router(export_router.router)

    @app.get("/api/health", tags=["health"])
    def health():
        return {"status": "ok", "version": "1.0.0"}

    return app


app = create_app()
