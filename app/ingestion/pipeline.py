"""
app/ingestion/pipeline.py
Orchestrates the full ingestion flow for a single document:
  validate → save to disk → extract → chunk → store chunks in DB

This module is called from the /api/documents upload endpoint.
It runs synchronously (FastAPI will dispatch it to a thread pool).
"""
from __future__ import annotations

import os
from pathlib import Path

from loguru import logger
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import crud
from app.db.models import Document, DocumentChunk
from app.ingestion.chunker import Chunk, chunk_extraction
from app.ingestion.extractor import ExtractionResult, extract_pdf


def run_ingestion(
    db: Session,
    doc: Document,
    content: bytes,
) -> int:
    """
    Run the full ingestion pipeline for an already-created Document record.

    Parameters
    ----------
    db      : active DB session
    doc     : Document ORM object (status=pending, storage_path set)
    content : raw PDF bytes

    Returns
    -------
    int : number of chunks created
    """
    settings = get_settings()
    logger.info("Ingestion started for document {}: {}", doc.id, doc.filename)

    # ── 1. Extract text / tables / headings ───────────────────────────────────
    try:
        extraction: ExtractionResult = extract_pdf(
            content, ocr_dpi=settings.ocr_dpi
        )
    except Exception as exc:
        logger.error("Extraction failed for doc {}: {}", doc.id, exc)
        raise

    # ── 2. Update document metadata ───────────────────────────────────────────
    crud.update_document_meta(
        db,
        doc.id,
        page_count=extraction.page_count,
        ocr_used=extraction.ocr_used,
    )

    # ── 3. Chunk ──────────────────────────────────────────────────────────────
    chunks: list[Chunk] = chunk_extraction(
        extraction,
        chunk_size=settings.chunk_size_tokens,
        overlap=settings.chunk_overlap_tokens,
    )

    if not chunks:
        logger.warning("No chunks produced for document {}", doc.id)
        return 0

    # ── 4. Store chunks in SQLite ─────────────────────────────────────────────
    db_chunks: list[DocumentChunk] = [
        DocumentChunk(
            document_id=doc.id,
            chunk_index=chunk.chunk_index,
            text=chunk.text,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            section_path=chunk.section_path,
            token_count=chunk.token_count,
            is_table=chunk.is_table,
            ocr_fallback=chunk.ocr_fallback,
        )
        for chunk in chunks
    ]
    crud.bulk_insert_chunks(db, db_chunks)

    # ── 5. Embed chunks and store in vector DB ────────────────────────────────
    try:
        from app.rag.embedder import get_embedder
        from app.rag.vector_store import upsert_chunks

        embedder = get_embedder()
        texts = [c.text for c in chunks]
        embeddings = embedder.embed_texts(texts)
        upsert_chunks(
            project_id=doc.project_id,
            chunks=chunks,
            embeddings=embeddings,
            document_id=doc.id,
            version_label=doc.version_label,
        )
        logger.info("Embedded and indexed {} chunks in vector store", len(chunks))
    except Exception as exc:
        logger.warning("Vector store indexing failed for doc {}: {}", doc.id, exc)

    # ── 6. Extract entities (regex fallback — LLM called separately) ──────────
    try:
        from app.extraction.entity_extractor import extract_entities_for_document
        entity_count = extract_entities_for_document(db, doc.id, use_llm=False)
        logger.info("Extracted {} entities (regex) for doc {}", entity_count, doc.id)
    except Exception as exc:
        logger.warning("Entity extraction failed for doc {}: {}", doc.id, exc)

    logger.info(
        "Ingestion complete for doc {}: {} pages, {} chunks, OCR={}",
        doc.id, extraction.page_count, len(chunks), extraction.ocr_used,
    )
    return len(chunks)


def save_upload(content: bytes, filename: str, project_id: int) -> str:
    """
    Save raw PDF bytes to the local uploads directory.

    Returns
    -------
    str : absolute storage path
    """
    upload_dir = Path("data") / "uploads" / str(project_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in filename)
    dest = upload_dir / safe_name
    # Avoid overwrite by appending a counter
    counter = 1
    while dest.exists():
        stem = Path(safe_name).stem
        suffix = Path(safe_name).suffix
        dest = upload_dir / f"{stem}_{counter}{suffix}"
        counter += 1
    dest.write_bytes(content)
    return str(dest.resolve())
