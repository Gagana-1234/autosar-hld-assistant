"""
app/api/export.py
Export router: generate PDF, Excel, and Markdown reports.
"""
from __future__ import annotations

import io
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.security import TokenData, require_permission
from app.db import crud
from app.db.database import get_db

router = APIRouter(prefix="/api/export", tags=["export"])


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/entities/{document_id}/csv")
def export_entities_csv(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_permission("export")),
):
    """Export extracted entities as a CSV file."""
    doc = crud.get_document(db, document_id)
    if not doc:
        raise NotFoundError("Document")
    if not crud.user_in_project(db, current_user.user_id, doc.project_id):
        raise AuthorizationError("Not a member of this project")

    entities = crud.list_entities(db, document_id)

    import csv
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Type", "Name", "Confidence", "Page", "Section", "Review Status", "Data"])
    for e in entities:
        writer.writerow([
            e.id, e.entity_type, e.name, e.confidence,
            e.page, e.section, e.review_status.value if e.review_status else "",
            e.data_json,
        ])
    output.seek(0)

    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=entities_doc{document_id}.csv"},
    )


@router.get("/entities/{document_id}/excel")
def export_entities_excel(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_permission("export")),
):
    """Export extracted entities as an Excel file."""
    doc = crud.get_document(db, document_id)
    if not doc:
        raise NotFoundError("Document")
    if not crud.user_in_project(db, current_user.user_id, doc.project_id):
        raise AuthorizationError("Not a member of this project")

    entities = crud.list_entities(db, document_id)

    import pandas as pd
    rows = []
    for e in entities:
        data = {}
        try:
            data = json.loads(e.data_json)
        except (json.JSONDecodeError, TypeError):
            pass
        rows.append({
            "ID": e.id,
            "Type": e.entity_type,
            "Name": e.name,
            "Confidence": e.confidence,
            "Page": e.page,
            "Section": e.section,
            "Review Status": e.review_status.value if e.review_status else "",
            "Description": data.get("description", ""),
        })

    df = pd.DataFrame(rows)
    output = io.BytesIO()
    df.to_excel(output, index=False, engine="openpyxl")
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=entities_doc{document_id}.xlsx"},
    )


@router.get("/entities/{document_id}/markdown")
def export_entities_markdown(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_permission("export")),
):
    """Export extracted entities as a Markdown report."""
    doc = crud.get_document(db, document_id)
    if not doc:
        raise NotFoundError("Document")
    if not crud.user_in_project(db, current_user.user_id, doc.project_id):
        raise AuthorizationError("Not a member of this project")

    entities = crud.list_entities(db, document_id)
    issues = crud.list_issues(db, document_id)

    lines = [
        f"# Entity Extraction Report",
        f"",
        f"**Document:** {doc.filename}",
        f"**Version:** {doc.version_label}",
        f"**Generated:** {datetime.now(timezone.utc).isoformat()}",
        f"**Total Entities:** {len(entities)}",
        f"**Consistency Issues:** {len(issues)}",
        f"",
        f"---",
        f"",
    ]

    # Group entities by type
    by_type: dict[str, list] = {}
    for e in entities:
        by_type.setdefault(e.entity_type, []).append(e)

    for etype, ents in sorted(by_type.items()):
        lines.append(f"## {etype} ({len(ents)})")
        lines.append("")
        lines.append("| Name | Confidence | Page | Section | Status |")
        lines.append("|------|-----------|------|---------|--------|")
        for e in ents:
            status = e.review_status.value if e.review_status else "pending"
            conf = f"{e.confidence:.0%}"
            lines.append(f"| {e.name} | {conf} | {e.page or '-'} | {e.section or '-'} | {status} |")
        lines.append("")

    if issues:
        lines.append("## Consistency Issues")
        lines.append("")
        lines.append("| Rule | Severity | Description |")
        lines.append("|------|----------|-------------|")
        for issue in issues:
            lines.append(f"| {issue.rule_id} | {issue.severity.value} | {issue.description} |")
        lines.append("")

    content = "\n".join(lines)
    return StreamingResponse(
        io.BytesIO(content.encode("utf-8")),
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename=report_doc{document_id}.md"},
    )


@router.get("/issues/{document_id}/csv")
def export_issues_csv(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(require_permission("export")),
):
    """Export consistency issues as CSV."""
    doc = crud.get_document(db, document_id)
    if not doc:
        raise NotFoundError("Document")
    if not crud.user_in_project(db, current_user.user_id, doc.project_id):
        raise AuthorizationError("Not a member of this project")

    issues = crud.list_issues(db, document_id)

    import csv
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Rule", "Severity", "Description", "Status", "Evidence"])
    for issue in issues:
        writer.writerow([
            issue.id, issue.rule_id, issue.severity.value,
            issue.description, issue.status.value, issue.evidence_json,
        ])
    output.seek(0)

    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=issues_doc{document_id}.csv"},
    )
