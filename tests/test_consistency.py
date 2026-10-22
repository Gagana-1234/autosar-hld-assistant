"""
tests/test_consistency.py
Unit tests for the AUTOSAR consistency validation rules.
"""
from __future__ import annotations

import json
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, UserRole
from app.db.crud import (
    create_user,
    create_project,
    create_document,
    create_entity,
    list_issues,
)
from app.validation.consistency import run_consistency_checks


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
def doc(db):
    """Create a user, project, and document for testing."""
    user = create_user(db, "consist_user", "c@test.com", "pass", UserRole.ADMIN)
    project = create_project(db, "ConsistencyProject", "Test", user.id)
    doc = create_document(
        db,
        project_id=project.id,
        filename="test.pdf",
        version_label="v1",
        uploaded_by=user.id,
        sha256="def456",
        storage_path="/tmp/test.pdf",
    )
    return doc


class TestConsistencyChecks:
    def test_no_entities_returns_no_issues(self, db, doc):
        issues = run_consistency_checks(db, doc.id)
        assert issues == []

    def test_orphan_signal_source_detected(self, db, doc):
        """Signal referencing a source SWC that doesn't exist."""
        # Create a signal with a non-existent source
        create_entity(
            db, doc.id, "Signal", "S_Speed",
            json.dumps({"name": "S_Speed", "source_swc": "NonExistentSWC", "target_swc": ""}),
            0.8, 1, "Signals",
        )
        issues = run_consistency_checks(db, doc.id)
        orphan_issues = [i for i in issues if i.rule_id == "orphan_signal_source"]
        assert len(orphan_issues) == 1
        assert "NonExistentSWC" in orphan_issues[0].description

    def test_orphan_signal_target_detected(self, db, doc):
        """Signal referencing a target SWC that doesn't exist."""
        create_entity(
            db, doc.id, "Signal", "S_Torque",
            json.dumps({"name": "S_Torque", "source_swc": "", "target_swc": "MissingSWC"}),
            0.8, 1, "Signals",
        )
        issues = run_consistency_checks(db, doc.id)
        orphan_issues = [i for i in issues if i.rule_id == "orphan_signal_target"]
        assert len(orphan_issues) == 1

    def test_no_orphan_when_swc_exists(self, db, doc):
        """Signal referencing SWCs that exist → no orphan issue."""
        create_entity(
            db, doc.id, "SWComponent", "EngineSWC",
            json.dumps({"name": "EngineSWC"}),
            0.9, 1, "Components",
        )
        create_entity(
            db, doc.id, "SWComponent", "TransSWC",
            json.dumps({"name": "TransSWC"}),
            0.9, 1, "Components",
        )
        create_entity(
            db, doc.id, "Signal", "S_RPM",
            json.dumps({"name": "S_RPM", "source_swc": "EngineSWC", "target_swc": "TransSWC"}),
            0.8, 1, "Signals",
        )
        issues = run_consistency_checks(db, doc.id)
        orphan_issues = [
            i for i in issues
            if i.rule_id in ("orphan_signal_source", "orphan_signal_target")
        ]
        assert len(orphan_issues) == 0

    def test_missing_interface_detected(self, db, doc):
        """Dependency referencing a non-existent interface."""
        create_entity(
            db, doc.id, "Dependency", "Dep_AB",
            json.dumps({"source": "A", "target": "B", "via_interface": "GhostInterface"}),
            0.7, 1, "Deps",
        )
        issues = run_consistency_checks(db, doc.id)
        missing = [i for i in issues if i.rule_id == "missing_interface"]
        assert len(missing) == 1
        assert "GhostInterface" in missing[0].description

    def test_no_missing_interface_when_exists(self, db, doc):
        """Dependency referencing an existing interface → no issue."""
        create_entity(
            db, doc.id, "Interface", "SR_CommIF",
            json.dumps({"name": "SR_CommIF"}),
            0.9, 1, "Interfaces",
        )
        create_entity(
            db, doc.id, "Dependency", "Dep_XY",
            json.dumps({"source": "X", "target": "Y", "via_interface": "SR_CommIF"}),
            0.7, 1, "Deps",
        )
        issues = run_consistency_checks(db, doc.id)
        missing = [i for i in issues if i.rule_id == "missing_interface"]
        assert len(missing) == 0

    def test_duplicate_entity_detected(self, db, doc):
        """Same entity name+type appearing multiple times."""
        for _ in range(3):
            create_entity(
                db, doc.id, "SWComponent", "DuplicateSWC",
                json.dumps({"name": "DuplicateSWC"}),
                0.8, 1, "Components",
            )
        issues = run_consistency_checks(db, doc.id)
        dups = [i for i in issues if i.rule_id == "duplicate_entity"]
        assert len(dups) == 1
        assert "3 times" in dups[0].description

    def test_dangling_dataflow_detected(self, db, doc):
        """DataFlow with a non-existent source SWC."""
        create_entity(
            db, doc.id, "DataFlow", "Flow_AB",
            json.dumps({"source_swc": "NoSuchSWC", "target_swc": "AlsoMissing"}),
            0.6, 1, "Flows",
        )
        issues = run_consistency_checks(db, doc.id)
        dangling = [i for i in issues if "dangling_dataflow" in i.rule_id]
        assert len(dangling) >= 1

    def test_unresolved_port_detected(self, db, doc):
        """SWC declares a port that doesn't match any interface."""
        create_entity(
            db, doc.id, "SWComponent", "TestSWC",
            json.dumps({"name": "TestSWC", "ports": ["UnmatchedPort"]}),
            0.9, 1, "Components",
        )
        issues = run_consistency_checks(db, doc.id)
        unresolved = [i for i in issues if i.rule_id == "unresolved_port"]
        assert len(unresolved) == 1
        assert "UnmatchedPort" in unresolved[0].description

    def test_issues_persisted_to_db(self, db, doc):
        """Verify that issues are saved in the database."""
        create_entity(
            db, doc.id, "Signal", "S_Orphan",
            json.dumps({"name": "S_Orphan", "source_swc": "Missing"}),
            0.5, 1, "Signals",
        )
        run_consistency_checks(db, doc.id)
        persisted = list_issues(db, doc.id)
        assert len(persisted) > 0
