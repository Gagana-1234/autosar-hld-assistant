"""
tests/test_extraction.py
Unit tests for entity extraction module (regex-based).
"""
from __future__ import annotations

import json
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, Document, DocumentChunk, UserRole
from app.db.crud import create_user, create_project, create_document, bulk_insert_chunks
from app.extraction.entity_extractor import (
    extract_entities_from_chunk,
    extract_entities_for_document,
    _extract_with_regex,
    _parse_llm_response,
)
from app.extraction.schemas import (
    ENTITY_SCHEMAS,
    SWComponent,
    Interface,
    Signal,
    Dependency,
    DataFlow,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def seeded_db(db):
    """DB with a user, project, document, and sample chunks."""
    user = create_user(db, "extractor_user", "ext@test.com", "pass123", UserRole.ADMIN)
    project = create_project(db, "ExtractProject", "Test", user.id)
    doc = create_document(
        db,
        project_id=project.id,
        filename="test.pdf",
        version_label="v1",
        uploaded_by=user.id,
        sha256="abc123",
        storage_path="/tmp/test.pdf",
    )
    # Insert sample chunks with AUTOSAR-like content
    chunks = [
        DocumentChunk(
            document_id=doc.id,
            chunk_index=0,
            text="The EngineControlSWC is responsible for managing engine torque. "
                 "It communicates with TransmissionSWC via SR_EngineInterface. "
                 "The signal S_EngineSpeed carries the current RPM value.",
            page_start=1,
            page_end=1,
            section_path="Components > Engine Control",
            token_count=30,
            is_table=False,
            ocr_fallback=False,
        ),
        DocumentChunk(
            document_id=doc.id,
            chunk_index=1,
            text="The BrakingComponent handles ABS logic. "
                 "It receives Sig_BrakePressure from the sensor interface.",
            page_start=2,
            page_end=2,
            section_path="Components > Braking",
            token_count=20,
            is_table=False,
            ocr_fallback=False,
        ),
        DocumentChunk(
            document_id=doc.id,
            chunk_index=2,
            text="No AUTOSAR-specific entities here. Just plain text description "
                 "about system requirements and safety standards.",
            page_start=3,
            page_end=3,
            section_path="Requirements",
            token_count=15,
            is_table=False,
            ocr_fallback=False,
        ),
    ]
    bulk_insert_chunks(db, chunks)
    return db, doc


# ── Schema tests ──────────────────────────────────────────────────────────────

class TestSchemas:
    def test_swc_schema_valid(self):
        swc = SWComponent(name="TestSWC")
        assert swc.name == "TestSWC"
        assert swc.swc_type == "ApplicationSwComponentType"

    def test_interface_schema(self):
        iface = Interface(name="SR_TestIF", interface_type="SenderReceiverInterface")
        assert iface.name == "SR_TestIF"

    def test_signal_schema(self):
        sig = Signal(name="S_Speed", direction="TX", data_type="uint16")
        assert sig.direction == "TX"

    def test_dependency_schema(self):
        dep = Dependency(source="A", target="B", dependency_type="uses")
        assert dep.source == "A"

    def test_dataflow_schema(self):
        flow = DataFlow(source_swc="SWC_A", target_swc="SWC_B")
        assert flow.direction == "unidirectional"

    def test_entity_schemas_mapping(self):
        assert "SWComponent" in ENTITY_SCHEMAS
        assert "Interface" in ENTITY_SCHEMAS
        assert "Signal" in ENTITY_SCHEMAS
        assert "Dependency" in ENTITY_SCHEMAS
        assert "DataFlow" in ENTITY_SCHEMAS


# ── Regex extraction tests ───────────────────────────────────────────────────

class TestRegexExtraction:
    def test_swc_detected_in_chunk(self, seeded_db):
        db, doc = seeded_db
        chunks = db.query(DocumentChunk).filter(
            DocumentChunk.document_id == doc.id,
            DocumentChunk.chunk_index == 0,
        ).all()
        entities = _extract_with_regex(chunks[0], db)
        swc_names = [e.name for e in entities if e.entity_type == "SWComponent"]
        assert "EngineControlSWC" in swc_names
        assert "TransmissionSWC" in swc_names

    def test_signal_detected(self, seeded_db):
        db, doc = seeded_db
        chunk = db.query(DocumentChunk).filter(
            DocumentChunk.document_id == doc.id,
            DocumentChunk.chunk_index == 0,
        ).first()
        entities = _extract_with_regex(chunk, db)
        signal_names = [e.name for e in entities if e.entity_type == "Signal"]
        assert "S_EngineSpeed" in signal_names

    def test_interface_detected(self, seeded_db):
        db, doc = seeded_db
        chunk = db.query(DocumentChunk).filter(
            DocumentChunk.document_id == doc.id,
            DocumentChunk.chunk_index == 0,
        ).first()
        entities = _extract_with_regex(chunk, db)
        iface_names = [e.name for e in entities if e.entity_type == "Interface"]
        assert "SR_EngineInterface" in iface_names

    def test_no_entities_in_plain_text(self, seeded_db):
        db, doc = seeded_db
        chunk = db.query(DocumentChunk).filter(
            DocumentChunk.document_id == doc.id,
            DocumentChunk.chunk_index == 2,
        ).first()
        entities = _extract_with_regex(chunk, db)
        assert len(entities) == 0

    def test_sig_prefix_detected(self, seeded_db):
        db, doc = seeded_db
        chunk = db.query(DocumentChunk).filter(
            DocumentChunk.document_id == doc.id,
            DocumentChunk.chunk_index == 1,
        ).first()
        entities = _extract_with_regex(chunk, db)
        signal_names = [e.name for e in entities if e.entity_type == "Signal"]
        assert "Sig_BrakePressure" in signal_names


# ── Full document extraction ─────────────────────────────────────────────────

class TestDocumentExtraction:
    def test_extract_entities_for_document(self, seeded_db):
        db, doc = seeded_db
        count = extract_entities_for_document(db, doc.id, use_llm=False)
        assert count > 0

    def test_extract_entities_empty_doc(self, db):
        """No chunks → 0 entities."""
        count = extract_entities_for_document(db, document_id=999, use_llm=False)
        assert count == 0


# ── LLM response parser ──────────────────────────────────────────────────────

class TestLLMParser:
    def test_parse_valid_json(self, seeded_db):
        db, doc = seeded_db
        chunk = db.query(DocumentChunk).filter(
            DocumentChunk.document_id == doc.id,
        ).first()

        raw = json.dumps([{
            "entity_type": "SWComponent",
            "name": "ParsedSWC",
            "confidence": 0.9,
            "data": {"name": "ParsedSWC", "swc_type": "ApplicationSwComponentType"}
        }])
        entities = _parse_llm_response(raw, chunk, db)
        assert len(entities) == 1
        assert entities[0].name == "ParsedSWC"

    def test_parse_empty_array(self, seeded_db):
        db, doc = seeded_db
        chunk = db.query(DocumentChunk).first()
        entities = _parse_llm_response("[]", chunk, db)
        assert entities == []

    def test_parse_invalid_json(self, seeded_db):
        db, doc = seeded_db
        chunk = db.query(DocumentChunk).first()
        entities = _parse_llm_response("not json at all", chunk, db)
        assert entities == []

    def test_parse_markdown_fenced_json(self, seeded_db):
        db, doc = seeded_db
        chunk = db.query(DocumentChunk).first()
        raw = '```json\n[{"entity_type": "Signal", "name": "S_Test", "confidence": 0.7, "data": {"name": "S_Test"}}]\n```'
        entities = _parse_llm_response(raw, chunk, db)
        assert len(entities) == 1
        assert entities[0].name == "S_Test"
