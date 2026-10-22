"""
app/core/audit.py
Audit log writer — records every consequential action to the SQLite audit_log table.
Called from API route handlers, never from the LLM pipeline.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session


def log_action(
    db: Session,
    user_id: int,
    project_id: int | None,
    action: str,
    resource_type: str,
    resource_id: int | str | None = None,
    detail: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> None:
    """
    Persist an audit record.

    Parameters
    ----------
    db            : active SQLAlchemy session (caller must commit).
    user_id       : ID of the acting user.
    project_id    : project scope (None for admin-level actions).
    action        : verb, e.g. 'upload_document', 'run_query', 'approve_entity'.
    resource_type : e.g. 'document', 'entity', 'project', 'user'.
    resource_id   : PK of the affected resource.
    detail        : arbitrary JSON-serialisable context.
    ip_address    : caller IP (extracted from Request in route handlers).
    """
    # Import here to avoid circular imports at module load time
    from app.db.models import AuditLog  # noqa: PLC0415

    entry = AuditLog(
        user_id=user_id,
        project_id=project_id,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        detail_json=json.dumps(detail or {}),
        timestamp=datetime.now(timezone.utc),
        ip_address=ip_address,
    )
    db.add(entry)
    logger.info(
        "AUDIT | user={} project={} action={} resource={}:{}",
        user_id,
        project_id,
        action,
        resource_type,
        resource_id,
    )
