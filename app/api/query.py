"""
app/api/query.py
RAG query endpoint: POST /api/query/ask
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.exceptions import AuthorizationError
from app.core.security import TokenData, require_permission
from app.db import crud
from app.db.database import get_db
from app.rag.pipeline import RAGResponse, Citation, run_rag

router = APIRouter(prefix="/api/query", tags=["query"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=2000)
    project_id: int
    top_k: int = Field(default=5, ge=1, le=20)
    filters: dict | None = None
    temperature: float = Field(default=0.1, ge=0.0, le=1.0)


class CitationOut(BaseModel):
    document_id: int
    version_label: str
    page_start: int
    page_end: int
    section_path: str
    chunk_text_snippet: str


class QueryResponse(BaseModel):
    answer: str
    citations: list[CitationOut]
    retrieved_chunks: int
    model_used: str
    query: str
    timestamp: str


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("/ask", response_model=QueryResponse)
def ask(
    body: QueryRequest,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_permission("run_query")),
):
    """Submit a natural-language question and receive an AI-assisted answer
    grounded in the project's ingested HLD documents."""

    if not crud.user_in_project(db, current_user.user_id, body.project_id):
        raise AuthorizationError("You are not a member of this project")

    rag_response: RAGResponse = run_rag(
        question=body.question,
        project_id=body.project_id,
        db=db,
        top_k=body.top_k,
        filters=body.filters,
        temperature=body.temperature,
    )

    return QueryResponse(
        answer=rag_response.answer,
        citations=[
            CitationOut(
                document_id=c.document_id,
                version_label=c.version_label,
                page_start=c.page_start,
                page_end=c.page_end,
                section_path=c.section_path,
                chunk_text_snippet=c.chunk_text_snippet,
            )
            for c in rag_response.citations
        ],
        retrieved_chunks=rag_response.retrieved_chunks,
        model_used=rag_response.model_used,
        query=rag_response.query,
        timestamp=rag_response.timestamp,
    )
