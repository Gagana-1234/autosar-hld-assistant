"""
app/db/database.py
SQLAlchemy engine and session factory.
Tables are created automatically on startup (no Alembic migration needed for dev).
"""
from __future__ import annotations

import os
from pathlib import Path

from loguru import logger
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def _get_engine():
    settings = get_settings()
    db_path = Path(settings.sqlite_db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{db_path.as_posix()}"
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False},
        echo=False,
    )
    # Enable WAL mode for better concurrent read performance
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


engine = _get_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """Create all tables if they don't exist. Called once at startup."""
    from app.db.models import Base  # noqa: PLC0415
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables initialised at {}", engine.url)


def get_db():
    """FastAPI dependency: yields a DB session and ensures it is closed."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
