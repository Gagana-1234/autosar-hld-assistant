"""
app/rag/pipeline.py
End-to-end RAG for answering AUTOSAR HLD questions.

Kept intentionally simple for now. Don't over-engineer until we know
what query patterns are actually used in practice.

TODO: add query result caching - same questions get asked repeatedly
TODO: try HyDE (hypothetical document embeddings) for better recall

Flow:
  1. Retrieve relevant chunks (retriever.retrieve)
  2. Build a controlled, citeable prompt
  3. Call the LLM (llm_provider.generate)
  4. Parse and return a structured response

The pipeline NEVER fabricates citations — every answer sentence
points back to a specific chunk, page, and section.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


from loguru import logger
from sqlalchemy.orm import Session

from app.db import crud
from app.rag.embedder import get_embedder
from app.rag.llm_provider import get_llm
from app.rag.retriever import retrieve
from app.rag.vector_store import SearchResult


# ── Response schema ───────────────────────────────────────────────────────────

@dataclass
class Citation:
    document_id: int
    version_label: str
    page_start: int
    page_end: int
    section_path: str
    chunk_text_snippet: str     # first 200 chars of the source chunk


@dataclass
class RAGResponse:
    answer: str
    citations: list[Citation]
    retrieved_chunks: int
    model_used: str
    query: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ── Prompt templates ──────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are an expert AUTOSAR architect assistant helping engineers review \
High-Level Design (HLD) documents. Your role is to ASSIST engineers — \
never replace their judgment.

RULES:
1. Answer ONLY from the provided context chunks. Do NOT use external knowledge.
2. If the answer is not in the context, say: "The provided documents do not contain information about this topic."
3. Cite every factual claim using [Chunk N] notation.
4. Keep answers concise, structured, and technically precise.
5. For component/interface questions, include signal names, data types, and direction if present.
6. Use bullet points for lists of components, signals, or requirements.
"""

_USER_PROMPT_TEMPLATE = """\
CONTEXT CHUNKS:
{context}

---
QUESTION:
{question}

Provide a technically precise answer based solely on the context above.
Use [Chunk N] to cite the source for each claim.
"""


# ── Main pipeline function ────────────────────────────────────────────────────

def run_rag(
    question: str,
    project_id: int,
    db: Session,
    top_k: int = 5,
    filters: dict | None = None,
    temperature: float = 0.1,
    max_tokens: int = 1024,
) -> RAGResponse:
    """
    Run the full RAG pipeline for a user question.

    Parameters
    ----------
    question   : user's natural language question
    project_id : restricts retrieval to approved docs in this project
    db         : SQLAlchemy session (for query logging)
    top_k      : number of chunks to retrieve
    filters    : optional metadata filters (e.g. {"document_id": 5})
    temperature: LLM sampling temperature
    max_tokens : max LLM response length

    Returns
    -------
    RAGResponse with answer, citations, and metadata
    """
    logger.info("RAG query for project {}: '{}'", project_id, question[:80])

    # ── 1. Retrieve relevant chunks ───────────────────────────────────────────
    results: list[SearchResult] = retrieve(
        question=question,
        project_id=project_id,
        top_k=top_k,
        filters=filters,
    )

    if not results:
        return RAGResponse(
            answer="The provided documents do not contain information about this topic.",
            citations=[],
            retrieved_chunks=0,
            model_used="none",
            query=question,
        )

    # ── 2. Build context string ───────────────────────────────────────────────
    context_parts: list[str] = []
    citations: list[Citation] = []

    for i, r in enumerate(results, start=1):
        section_label = f" | Section: {r.section_path}" if r.section_path else ""
        table_label = " [TABLE]" if r.is_table else ""
        header = (
            f"[Chunk {i}] Doc ID: {r.document_id} | "
            f"Version: {r.version_label} | "
            f"Pages: {r.page_start}–{r.page_end}"
            f"{section_label}{table_label}"
        )
        context_parts.append(f"{header}\n{r.text}")
        citations.append(Citation(
            document_id=r.document_id,
            version_label=r.version_label,
            page_start=r.page_start,
            page_end=r.page_end,
            section_path=r.section_path,
            chunk_text_snippet=r.text[:200],
        ))

    context = "\n\n---\n\n".join(context_parts)
    prompt = _USER_PROMPT_TEMPLATE.format(context=context, question=question)

    # ── 3. Generate answer ────────────────────────────────────────────────────
    llm = get_llm()
    settings_ref = llm.__class__.__name__

    try:
        answer = llm.generate(
            prompt=prompt,
            system=_SYSTEM_PROMPT,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except RuntimeError as exc:
        answer = f"⚠️ LLM unavailable: {exc}"

    # ── 4. Log query to DB ────────────────────────────────────────────────────
    import json as _json
    try:
        citations_json = _json.dumps([
            {
                "document_id": c.document_id,
                "page_start": c.page_start,
                "page_end": c.page_end,
                "section_path": c.section_path,
            }
            for c in citations
        ])
        crud.log_query(
            db,
            user_id=0,           # 0 = system / unknown; override at call site if needed
            project_id=project_id,
            question=question,
            answer=answer,
            citations_json=citations_json,
            confidence=round(1.0 - (results[0].score if results else 1.0), 3),
            has_valid_citation=bool(citations),
        )
        db.commit()
    except Exception as exc:
        logger.warning("Failed to log RAG query: {}", exc)

    logger.info("RAG answer generated ({} chunks used)", len(results))
    return RAGResponse(
        answer=answer,
        citations=citations,
        retrieved_chunks=len(results),
        model_used=settings_ref,
        query=question,
    )
