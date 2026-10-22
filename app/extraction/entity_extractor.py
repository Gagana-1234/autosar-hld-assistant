"""
app/extraction/entity_extractor.py
LLM-based entity extraction from document chunks.

Tried a few approaches here - settled on prompting the LLM for structured
JSON output with a regex fallback for when the LLM isn't available.

The regex patterns are pretty naive right now, they'll miss things.
LLM mode is much better but requires Ollama running locally.

TODO: add a spaCy NER fallback as a middle ground between regex and LLM
TODO: confidence scoring for regex hits is basically made up (0.4/0.5)
      would be good to calibrate this against human-labeled examples
FIXME: seen_names set resets per chunk so same entity extracted multiple times
       across chunks - need deduplication at the document level
"""
from __future__ import annotations

import json
import re
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import crud
from app.db.models import DocumentChunk, Entity, ReviewStatus
from app.extraction.schemas import ENTITY_SCHEMAS


# ── Extraction prompt ────────────────────────────────────────────────────────

_EXTRACTION_PROMPT = """\
You are an AUTOSAR HLD document analysis engine.
Analyse the following text chunk and extract ALL structured entities you can find.

Return a JSON array of objects.  Each object must have exactly these keys:
  "entity_type": one of "SWComponent", "Interface", "Signal", "Dependency", "DataFlow"
  "name": a short unique name for the entity
  "confidence": a float between 0.0 and 1.0 indicating how certain you are
  "data": an object with additional fields depending on entity_type

For SWComponent data: {{name, swc_type, description, ports[], runnables[], layer}}
For Interface data:   {{name, interface_type, data_elements[], operations[], description}}
For Signal data:      {{name, direction, data_type, unit, source_swc, target_swc, description}}
For Dependency data:  {{source, target, dependency_type, via_interface, description}}
For DataFlow data:    {{source_swc, target_swc, signal_name, interface_name, direction, description}}

If no entities are found, return an empty array: []
Do NOT include markdown code fences — return raw JSON only.

CHUNK (page {page}, section: "{section}"):
---
{text}
---
"""


# ── Regex-based fallback patterns ────────────────────────────────────────────

# regex patterns for common AUTOSAR naming conventions
# NOTE: these are based on the AUTOSAR naming guidelines but real projects
# don't always follow them - might need project-specific overrides
_SWC_PATTERNS = [
    re.compile(r"\b([A-Z][a-zA-Z0-9_]*(?:SWC|Swc|SwComponent))\b"),
    re.compile(r"\b([A-Z][a-zA-Z0-9_]*(?:Component|Comp))\b"),
]

_INTERFACE_PATTERNS = [
    re.compile(r"\b([A-Z][a-zA-Z0-9_]*(?:Interface|IF|_If))\b"),
    re.compile(r"\b((?:SR|CS|ClientServer|SenderReceiver)_[A-Za-z0-9_]+)\b"),
]

_SIGNAL_PATTERNS = [
    re.compile(r"\b(S_[A-Za-z0-9_]+)\b"),
    re.compile(r"\b(Sig_[A-Za-z0-9_]+)\b"),
    re.compile(r"\b([A-Z][a-zA-Z0-9_]*Signal)\b"),
]


# ── Public API ────────────────────────────────────────────────────────────────

def extract_entities_from_chunk(
    chunk: DocumentChunk,
    db: Session,
    use_llm: bool = True,
) -> list[Entity]:
    """
    Extract entities from a single document chunk.

    Parameters
    ----------
    chunk   : DocumentChunk ORM object
    db      : active SQLAlchemy session
    use_llm : if True, call the LLM; if False, use regex fallback only

    Returns
    -------
    list[Entity] — newly created Entity records (already added to session)
    """
    entities: list[Entity] = []

    if use_llm:
        try:
            entities = _extract_with_llm(chunk, db)
        except Exception as exc:
            logger.warning(
                "LLM extraction failed for chunk {}: {}. Falling back to regex.",
                chunk.id, exc,
            )
            entities = _extract_with_regex(chunk, db)
    else:
        entities = _extract_with_regex(chunk, db)

    return entities


def extract_entities_for_document(
    db: Session,
    document_id: int,
    use_llm: bool = True,
) -> int:
    """
    Run entity extraction across all chunks of a document.

    Returns the total number of entities created.
    """
    chunks = crud.get_chunks_for_document(db, document_id)
    if not chunks:
        logger.warning("No chunks found for document {}", document_id)
        return 0

    total = 0
    settings = get_settings()

    for chunk in chunks:
        new_entities = extract_entities_from_chunk(chunk, db, use_llm=use_llm)

        # Auto-approve high-confidence entities; flag low-confidence for review
        for entity in new_entities:
            if entity.confidence >= settings.min_confidence_auto_approve:
                entity.review_status = ReviewStatus.ACCEPTED
                entity.requires_human_review = False
            elif entity.confidence < settings.low_confidence_threshold:
                entity.requires_human_review = True
                # Create a review queue item
                db.flush()  # ensure entity.id is assigned
                crud.create_review_item(
                    db,
                    entity_id=entity.id,
                    reason="low_confidence",
                )

        total += len(new_entities)

    db.commit()
    logger.info("Extracted {} entities for document {}", total, document_id)
    return total


# ── LLM-based extraction ─────────────────────────────────────────────────────

def _extract_with_llm(chunk: DocumentChunk, db: Session) -> list[Entity]:
    """Call the LLM to extract structured entities from chunk text."""
    from app.rag.llm_provider import get_llm

    llm = get_llm()
    prompt = _EXTRACTION_PROMPT.format(
        page=chunk.page_start or 0,
        section=chunk.section_path or "",
        text=chunk.text,
    )

    raw = llm.generate(
        prompt=prompt,
        system="You are a precise AUTOSAR document analysis engine. Return only valid JSON.",
        temperature=0.0,
        max_tokens=2048,  # might need to increase for very long chunks
    )

    return _parse_llm_response(raw, chunk, db)


def _parse_llm_response(
    raw: str,
    chunk: DocumentChunk,
    db: Session,
) -> list[Entity]:
    """Parse JSON array from LLM output into Entity ORM objects."""
    # Strip markdown fences if present
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        items = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("Failed to parse LLM JSON for chunk {}: {}", chunk.id, raw[:200])
        return []

    if not isinstance(items, list):
        items = [items]

    entities: list[Entity] = []
    for item in items:
        entity_type = item.get("entity_type", "")
        name = item.get("name", "")
        confidence = float(item.get("confidence", 0.5))
        data = item.get("data", {})

        if not entity_type or not name:
            continue

        # Validate against schema if possible
        schema_cls = ENTITY_SCHEMAS.get(entity_type)
        if schema_cls:
            try:
                validated = schema_cls(**data)
                data = validated.model_dump()
            except Exception:
                pass  # store raw data if validation fails

        entity = crud.create_entity(
            db,
            document_id=chunk.document_id,
            entity_type=entity_type,
            name=name,
            data_json=json.dumps(data),
            confidence=confidence,
            page=chunk.page_start,
            section=chunk.section_path,
        )
        entities.append(entity)

    return entities


# ── Regex-based extraction (fallback) ─────────────────────────────────────────

def _extract_with_regex(chunk: DocumentChunk, db: Session) -> list[Entity]:
    """Extract entities using simple regex pattern matching."""
    entities: list[Entity] = []
    text = chunk.text
    seen_names: set[str] = set()

    # SWC patterns
    for pattern in _SWC_PATTERNS:
        for match in pattern.finditer(text):
            name = match.group(1)
            if name in seen_names:
                continue
            seen_names.add(name)
            entity = crud.create_entity(
                db,
                document_id=chunk.document_id,
                entity_type="SWComponent",
                name=name,
                data_json=json.dumps({"name": name, "swc_type": "ApplicationSwComponentType", "description": "", "ports": [], "runnables": [], "layer": ""}),
                confidence=0.5,
                page=chunk.page_start,
                section=chunk.section_path,
            )
            entities.append(entity)

    # Interface patterns
    for pattern in _INTERFACE_PATTERNS:
        for match in pattern.finditer(text):
            name = match.group(1)
            if name in seen_names:
                continue
            seen_names.add(name)
            entity = crud.create_entity(
                db,
                document_id=chunk.document_id,
                entity_type="Interface",
                name=name,
                data_json=json.dumps({"name": name, "interface_type": "SenderReceiverInterface", "data_elements": [], "operations": [], "description": ""}),
                confidence=0.4,
                page=chunk.page_start,
                section=chunk.section_path,
            )
            entities.append(entity)

    # Signal patterns
    for pattern in _SIGNAL_PATTERNS:
        for match in pattern.finditer(text):
            name = match.group(1)
            if name in seen_names:
                continue
            seen_names.add(name)
            entity = crud.create_entity(
                db,
                document_id=chunk.document_id,
                entity_type="Signal",
                name=name,
                data_json=json.dumps({"name": name, "direction": "", "data_type": "", "unit": "", "source_swc": "", "target_swc": "", "description": ""}),
                confidence=0.4,
                page=chunk.page_start,
                section=chunk.section_path,
            )
            entities.append(entity)

    return entities
