"""
tests/test_api_endpoints.py
Integration tests for the new API routers:
  - extraction, review, consistency, comparison, export
"""
from __future__ import annotations

import json
import os
import pytest
import httpx

os.environ["TESTING"] = "1"
os.environ["EMBEDDING_MODEL"] = "stub"
os.environ["LLM_PROVIDER"] = "stub"

from app.db.models import (
    Base,
    DocumentChunk,
    Entity,
    ReviewStatus,
    UserRole,
)
from app.db.crud import (
    bulk_insert_chunks,
    create_document,
    create_entity,
    create_project,
    create_user,
)
from tests.conftest import auth_headers, get_token


# ── Fixtures (reusing conftest engine/db/client) ──────────────────────────────

@pytest.fixture
def populated_project(db):
    """Create admin user + project + document + chunks + entities."""
    user = create_user(db, "api_admin", "api@test.com", "password123", UserRole.ADMIN)
    project = create_project(db, "API Test Project", "Testing", user.id)
    doc = create_document(
        db,
        project_id=project.id,
        filename="hld_spec.pdf",
        version_label="v1.0",
        uploaded_by=user.id,
        sha256="sha256_test_hash",
        storage_path="/tmp/hld_spec.pdf",
    )
    # Insert chunks
    chunks = [
        DocumentChunk(
            document_id=doc.id,
            chunk_index=0,
            text="The EngineControlSWC manages engine torque via SR_EngineIF. S_EngineSpeed.",
            page_start=1,
            page_end=1,
            section_path="Engine",
            token_count=15,
        ),
        DocumentChunk(
            document_id=doc.id,
            chunk_index=1,
            text="BrakingComponent receives Sig_BrakePressure from sensor interface.",
            page_start=2,
            page_end=2,
            section_path="Braking",
            token_count=10,
        ),
    ]
    bulk_insert_chunks(db, chunks)

    # Insert entities for review & consistency tests
    create_entity(
        db, doc.id, "SWComponent", "EngineControlSWC",
        json.dumps({"name": "EngineControlSWC", "ports": []}),
        0.9, 1, "Engine",
    )
    create_entity(
        db, doc.id, "Signal", "S_Speed",
        json.dumps({"name": "S_Speed", "source_swc": "MissingSWC"}),
        0.4, 1, "Signals",
    )

    return {"user": user, "project": project, "doc": doc}


# ── Extraction API ───────────────────────────────────────────────────────────

class TestExtractionAPI:
    @pytest.mark.asyncio
    async def test_trigger_extraction(self, client, populated_project):
        token = await get_token(client, "api_admin")
        resp = await client.post(
            "/api/extraction/run",
            json={"document_id": populated_project["doc"].id, "use_llm": False},
            headers=auth_headers(token),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["document_id"] == populated_project["doc"].id
        assert data["entities_extracted"] >= 0

    @pytest.mark.asyncio
    async def test_list_entities(self, client, populated_project):
        token = await get_token(client, "api_admin")
        resp = await client.get(
            f"/api/extraction/{populated_project['doc'].id}",
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        entities = resp.json()
        assert isinstance(entities, list)
        assert len(entities) >= 2  # seeded entities

    @pytest.mark.asyncio
    async def test_list_entities_filtered(self, client, populated_project):
        token = await get_token(client, "api_admin")
        resp = await client.get(
            f"/api/extraction/{populated_project['doc'].id}",
            params={"entity_type": "SWComponent"},
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        entities = resp.json()
        assert all(e["entity_type"] == "SWComponent" for e in entities)

    @pytest.mark.asyncio
    async def test_review_entity_accept(self, client, populated_project, db):
        token = await get_token(client, "api_admin")
        # Get entity IDs
        entities = db.query(Entity).filter(
            Entity.document_id == populated_project["doc"].id
        ).all()
        entity_id = entities[0].id

        resp = await client.put(
            f"/api/extraction/entity/{entity_id}/review",
            json={"status": "accepted", "comment": "Looks correct"},
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        assert resp.json()["review_status"] == "accepted"

    @pytest.mark.asyncio
    async def test_review_nonexistent_entity_404(self, client, populated_project):
        token = await get_token(client, "api_admin")
        resp = await client.put(
            "/api/extraction/entity/99999/review",
            json={"status": "accepted"},
            headers=auth_headers(token),
        )
        assert resp.status_code == 404


# ── Consistency API ──────────────────────────────────────────────────────────

class TestConsistencyAPI:
    @pytest.mark.asyncio
    async def test_run_consistency_checks(self, client, populated_project):
        token = await get_token(client, "api_admin")
        resp = await client.post(
            f"/api/consistency/run/{populated_project['doc'].id}",
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["document_id"] == populated_project["doc"].id
        assert data["issues_found"] >= 0

    @pytest.mark.asyncio
    async def test_list_issues(self, client, populated_project):
        token = await get_token(client, "api_admin")
        # Run checks first
        await client.post(
            f"/api/consistency/run/{populated_project['doc'].id}",
            headers=auth_headers(token),
        )
        resp = await client.get(
            f"/api/consistency/{populated_project['doc'].id}",
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ── Comparison API ───────────────────────────────────────────────────────────

class TestComparisonAPI:
    @pytest.mark.asyncio
    async def test_compare_two_documents(self, client, populated_project, db):
        # Create a second document
        doc2 = create_document(
            db,
            project_id=populated_project["project"].id,
            filename="hld_spec_v2.pdf",
            version_label="v2.0",
            uploaded_by=populated_project["user"].id,
            sha256="sha256_v2",
            storage_path="/tmp/v2.pdf",
        )
        chunks2 = [
            DocumentChunk(
                document_id=doc2.id,
                chunk_index=0,
                text="Updated EngineControlSWC with new torque logic.",
                page_start=1,
                page_end=1,
                section_path="Engine",
                token_count=10,
            ),
        ]
        bulk_insert_chunks(db, chunks2)

        token = await get_token(client, "api_admin")
        resp = await client.post(
            "/api/comparison/compare",
            json={
                "doc_id_a": populated_project["doc"].id,
                "doc_id_b": doc2.id,
            },
            headers=auth_headers(token),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "diffs" in data
        assert data["doc_id_a"] == populated_project["doc"].id
        assert data["doc_id_b"] == doc2.id


# ── Export API ───────────────────────────────────────────────────────────────

class TestExportAPI:
    @pytest.mark.asyncio
    async def test_export_csv(self, client, populated_project):
        token = await get_token(client, "api_admin")
        resp = await client.get(
            f"/api/export/entities/{populated_project['doc'].id}/csv",
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_export_markdown(self, client, populated_project):
        token = await get_token(client, "api_admin")
        resp = await client.get(
            f"/api/export/entities/{populated_project['doc'].id}/markdown",
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        content = resp.text
        assert "Entity Extraction Report" in content

    @pytest.mark.asyncio
    async def test_export_excel(self, client, populated_project):
        token = await get_token(client, "api_admin")
        resp = await client.get(
            f"/api/export/entities/{populated_project['doc'].id}/excel",
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        assert "spreadsheetml" in resp.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_export_issues_csv(self, client, populated_project):
        token = await get_token(client, "api_admin")
        resp = await client.get(
            f"/api/export/issues/{populated_project['doc'].id}/csv",
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
