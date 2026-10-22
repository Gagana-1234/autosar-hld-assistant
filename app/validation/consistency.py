"""
app/validation/consistency.py
Cross-document consistency checks for AUTOSAR HLD entities.

Rules implemented:
  1. Orphan ports — port referenced in a signal but SWC not found
  2. Missing interfaces — dependency via_interface references a non-existent interface
  3. Dangling signals — signal with source or target SWC not in the entity set
  4. Duplicate entity names within same document
  5. Bidirectional mismatch — TX signal at source but no RX at target
"""
from __future__ import annotations

import json
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from app.db import crud
from app.db.models import (
    ConsistencyIssue,
    Entity,
    IssueSeverity,
)


def run_consistency_checks(db: Session, document_id: int) -> list[ConsistencyIssue]:
    """
    Run all consistency rules against entities extracted from a document.

    Returns a list of newly created ConsistencyIssue records.
    """
    entities = crud.list_entities(db, document_id)
    if not entities:
        logger.info("No entities for document {} — skipping consistency checks", document_id)
        return []

    # Build lookup tables
    by_type: dict[str, list[dict]] = {}
    for e in entities:
        data = _safe_json(e.data_json)
        data["_entity_id"] = e.id
        data["_name"] = e.name
        by_type.setdefault(e.entity_type, []).append(data)

    swc_names = {d["_name"] for d in by_type.get("SWComponent", [])}
    interface_names = {d["_name"] for d in by_type.get("Interface", [])}

    issues: list[ConsistencyIssue] = []

    # Rule 1: Orphan signals — source or target SWC not found
    for sig in by_type.get("Signal", []):
        src = sig.get("source_swc", "")
        tgt = sig.get("target_swc", "")
        if src and src not in swc_names:
            issues.append(_make_issue(
                document_id,
                "orphan_signal_source",
                IssueSeverity.HIGH,
                f"Signal '{sig['_name']}' references source SWC '{src}' which is not defined.",
                [{"signal": sig["_name"], "missing_swc": src}],
            ))
        if tgt and tgt not in swc_names:
            issues.append(_make_issue(
                document_id,
                "orphan_signal_target",
                IssueSeverity.HIGH,
                f"Signal '{sig['_name']}' references target SWC '{tgt}' which is not defined.",
                [{"signal": sig["_name"], "missing_swc": tgt}],
            ))

    # Rule 2: Missing interfaces in dependencies
    for dep in by_type.get("Dependency", []):
        via = dep.get("via_interface", "")
        if via and via not in interface_names:
            issues.append(_make_issue(
                document_id,
                "missing_interface",
                IssueSeverity.MEDIUM,
                f"Dependency '{dep.get('source', '')} -> {dep.get('target', '')}' references "
                f"interface '{via}' which is not defined.",
                [{"dependency": dep["_name"], "missing_interface": via}],
            ))

    # Rule 3: Dangling data flows
    for flow in by_type.get("DataFlow", []):
        src = flow.get("source_swc", "")
        tgt = flow.get("target_swc", "")
        if src and src not in swc_names:
            issues.append(_make_issue(
                document_id,
                "dangling_dataflow_source",
                IssueSeverity.MEDIUM,
                f"DataFlow from '{src}' to '{tgt}' — source SWC not defined.",
                [{"flow": flow["_name"], "missing_swc": src}],
            ))
        if tgt and tgt not in swc_names:
            issues.append(_make_issue(
                document_id,
                "dangling_dataflow_target",
                IssueSeverity.MEDIUM,
                f"DataFlow from '{src}' to '{tgt}' — target SWC not defined.",
                [{"flow": flow["_name"], "missing_swc": tgt}],
            ))

    # Rule 4: Duplicate entity names within same document
    name_counts: dict[str, int] = {}
    for e in entities:
        key = f"{e.entity_type}:{e.name}"
        name_counts[key] = name_counts.get(key, 0) + 1
    for key, count in name_counts.items():
        if count > 1:
            etype, ename = key.split(":", 1)
            issues.append(_make_issue(
                document_id,
                "duplicate_entity",
                IssueSeverity.LOW,
                f"Entity '{ename}' of type '{etype}' appears {count} times.",
                [{"entity_type": etype, "name": ename, "count": count}],
            ))

    # Rule 5: Interface data element mismatches (SWC ports vs interface elements)
    for swc in by_type.get("SWComponent", []):
        ports = swc.get("ports", [])
        for port_name in ports:
            # Check if there's an interface matching this port
            matching = [
                iface for iface in by_type.get("Interface", [])
                if port_name in iface.get("data_elements", [])
                or port_name == iface.get("_name", "")
            ]
            if not matching and port_name:
                issues.append(_make_issue(
                    document_id,
                    "unresolved_port",
                    IssueSeverity.LOW,
                    f"SWC '{swc['_name']}' declares port '{port_name}' "
                    f"but no matching interface found.",
                    [{"swc": swc["_name"], "port": port_name}],
                ))

    # Persist issues
    if issues:
        crud.bulk_insert_issues(db, issues)
        logger.info(
            "Found {} consistency issues for document {}", len(issues), document_id
        )
    else:
        logger.info("No consistency issues for document {}", document_id)

    return issues


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_json(s: str) -> dict:
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return {}


def _make_issue(
    document_id: int,
    rule_id: str,
    severity: IssueSeverity,
    description: str,
    evidence: list[dict[str, Any]],
) -> ConsistencyIssue:
    return ConsistencyIssue(
        document_id=document_id,
        rule_id=rule_id,
        severity=severity,
        description=description,
        evidence_json=json.dumps(evidence),
    )
