"""
app/api/comparison.py
Revision comparison router: compare two versions of a document.
"""
from __future__ import annotations

import json
from difflib import unified_diff

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.audit import log_action
from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.security import TokenData, require_permission
from app.db import crud
from app.db.database import get_db

router = APIRouter(prefix="/api/comparison", tags=["comparison"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class CompareRequest(BaseModel):
    doc_id_a: int
    doc_id_b: int


class DiffChunk(BaseModel):
    chunk_index: int
    type: str  # "added", "removed", "modified", "unchanged"
    text_a: str
    text_b: str


class CompareResponse(BaseModel):
    id: int
    doc_id_a: int
    doc_id_b: int
    total_chunks_a: int
    total_chunks_b: int
    added: int
    removed: int
    modified: int
    diffs: list[DiffChunk]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/compare", response_model=CompareResponse, status_code=201)
def compare_revisions(
    body: CompareRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_permission("compare_revisions")),
):
    """Compare two document revisions and produce a diff."""
    doc_a = crud.get_document(db, body.doc_id_a)
    doc_b = crud.get_document(db, body.doc_id_b)
    if not doc_a:
        raise NotFoundError("Document A")
    if not doc_b:
        raise NotFoundError("Document B")

    # Verify membership
    for doc in [doc_a, doc_b]:
        if not crud.user_in_project(db, current_user.user_id, doc.project_id):
            raise AuthorizationError("Not a member of this project")

    chunks_a = crud.get_chunks_for_document(db, body.doc_id_a)
    chunks_b = crud.get_chunks_for_document(db, body.doc_id_b)

    texts_a = {c.chunk_index: c.text for c in chunks_a}
    texts_b = {c.chunk_index: c.text for c in chunks_b}

    all_indices = sorted(set(texts_a.keys()) | set(texts_b.keys()))

    diffs: list[DiffChunk] = []
    added = removed = modified = 0

    for idx in all_indices:
        a = texts_a.get(idx, "")
        b = texts_b.get(idx, "")
        if a and not b:
            diffs.append(DiffChunk(chunk_index=idx, type="removed", text_a=a, text_b=""))
            removed += 1
        elif b and not a:
            diffs.append(DiffChunk(chunk_index=idx, type="added", text_a="", text_b=b))
            added += 1
        elif a != b:
            diffs.append(DiffChunk(chunk_index=idx, type="modified", text_a=a, text_b=b))
            modified += 1

    diff_json = json.dumps([d.model_dump() for d in diffs])
    diff_record = crud.create_revision_diff(
        db, body.doc_id_a, body.doc_id_b, diff_json, current_user.user_id
    )

    log_action(
        db,
        user_id=current_user.user_id,
        project_id=doc_a.project_id,
        action="compare_revisions",
        resource_type="revision_diff",
        resource_id=diff_record.id,
        detail={"doc_a": body.doc_id_a, "doc_b": body.doc_id_b},
        ip_address=request.client.host if request.client else None,
    )
    db.commit()

    return CompareResponse(
        id=diff_record.id,
        doc_id_a=body.doc_id_a,
        doc_id_b=body.doc_id_b,
        total_chunks_a=len(chunks_a),
        total_chunks_b=len(chunks_b),
        added=added,
        removed=removed,
        modified=modified,
        diffs=diffs,
    )
