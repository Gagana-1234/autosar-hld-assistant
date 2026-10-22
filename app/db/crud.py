"""
app/db/crud.py
Database helper functions - thin wrappers over SQLAlchemy queries.
All functions take a Session and return ORM objects (not raw rows).

TODO: add pagination to list functions - will be needed once projects
      have hundreds of documents
TODO: might want to add soft delete instead of hard delete at some point
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.models import (
    AuditLog,
    ConsistencyIssue,
    Document,
    DocumentChunk,
    DocumentStatus,
    Entity,
    Project,
    ProjectMember,
    QueryLog,
    ReviewItem,
    ReviewStatus,
    RevisionDiff,
    User,
    UserRole,
)


# ── Users ─────────────────────────────────────────────────────────────────────

def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.query(User).filter(User.id == user_id).first()


def get_user_by_username(db: Session, username: str) -> User | None:
    return db.query(User).filter(User.username == username).first()


def create_user(db: Session, username: str, email: str, plain_password: str, role: UserRole = UserRole.VIEWER) -> User:
    user = User(
        username=username,
        email=email,
        hashed_password=hash_password(plain_password),
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def list_users(db: Session, skip: int = 0, limit: int = 100) -> list[User]:
    return db.query(User).offset(skip).limit(limit).all()


def deactivate_user(db: Session, user_id: int) -> User | None:
    user = get_user_by_id(db, user_id)
    if user:
        user.is_active = False
        db.commit()
    return user


# ── Projects ──────────────────────────────────────────────────────────────────

def create_project(db: Session, name: str, description: str, created_by: int) -> Project:
    project = Project(name=name, description=description, created_by=created_by)
    db.add(project)
    db.commit()
    db.refresh(project)
    # Auto-add creator as admin member
    add_project_member(db, project.id, created_by, UserRole.ADMIN)
    return project


def get_project(db: Session, project_id: int) -> Project | None:
    return db.query(Project).filter(Project.id == project_id).first()


def list_projects_for_user(db: Session, user_id: int) -> list[Project]:
    return (
        db.query(Project)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .filter(ProjectMember.user_id == user_id)
        .all()
    )


def add_project_member(db: Session, project_id: int, user_id: int, role: UserRole) -> ProjectMember:
    member = ProjectMember(project_id=project_id, user_id=user_id, role=role)
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


def user_in_project(db: Session, user_id: int, project_id: int) -> bool:
    return (
        db.query(ProjectMember)
        .filter(ProjectMember.user_id == user_id, ProjectMember.project_id == project_id)
        .first()
    ) is not None


# ── Documents ─────────────────────────────────────────────────────────────────

def create_document(
    db: Session,
    project_id: int,
    filename: str,
    version_label: str,
    uploaded_by: int,
    sha256: str,
    storage_path: str,
) -> Document:
    doc = Document(
        project_id=project_id,
        filename=filename,
        version_label=version_label,
        uploaded_by=uploaded_by,
        sha256=sha256,
        storage_path=storage_path,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def get_document(db: Session, doc_id: int) -> Document | None:
    return db.query(Document).filter(Document.id == doc_id).first()


def list_documents(db: Session, project_id: int) -> list[Document]:
    return db.query(Document).filter(Document.project_id == project_id).all()


def approve_document(db: Session, doc_id: int, approved_by: int) -> Document | None:
    doc = get_document(db, doc_id)
    if doc:
        doc.status = DocumentStatus.APPROVED
        doc.approved_by = approved_by
        doc.approved_at = datetime.now(timezone.utc)
        db.commit()
    return doc


def update_document_meta(db: Session, doc_id: int, **kwargs: Any) -> Document | None:
    doc = get_document(db, doc_id)
    if doc:
        for k, v in kwargs.items():
            setattr(doc, k, v)
        db.commit()
    return doc


# ── Chunks ────────────────────────────────────────────────────────────────────

def bulk_insert_chunks(db: Session, chunks: list[DocumentChunk]) -> None:
    db.bulk_save_objects(chunks)
    db.commit()


def get_chunks_for_document(db: Session, doc_id: int) -> list[DocumentChunk]:
    return db.query(DocumentChunk).filter(DocumentChunk.document_id == doc_id).order_by(DocumentChunk.chunk_index).all()


# ── Entities ──────────────────────────────────────────────────────────────────

def create_entity(
    db: Session,
    document_id: int,
    entity_type: str,
    name: str,
    data_json: str,
    confidence: float,
    page: int | None,
    section: str | None,
) -> Entity:
    entity = Entity(
        document_id=document_id,
        entity_type=entity_type,
        name=name,
        data_json=data_json,
        confidence=confidence,
        page=page,
        section=section,
    )
    db.add(entity)
    db.commit()
    db.refresh(entity)
    return entity


def list_entities(db: Session, document_id: int, entity_type: str | None = None) -> list[Entity]:
    q = db.query(Entity).filter(Entity.document_id == document_id)
    if entity_type:
        q = q.filter(Entity.entity_type == entity_type)
    return q.all()


def update_entity_review(
    db: Session,
    entity_id: int,
    reviewer_id: int,
    status: ReviewStatus,
    comment: str | None = None,
    new_data_json: str | None = None,
) -> Entity | None:
    entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if entity:
        entity.review_status = status
        entity.reviewed_by = reviewer_id
        entity.reviewed_at = datetime.now(timezone.utc)
        entity.requires_human_review = False
        if comment:
            entity.reviewer_comment = comment
        if new_data_json:
            entity.data_json = new_data_json
        db.commit()
    return entity


# ── Review Queue ──────────────────────────────────────────────────────────────

def create_review_item(db: Session, entity_id: int, reason: str, assigned_to: int | None = None) -> ReviewItem:
    item = ReviewItem(entity_id=entity_id, queue_reason=reason, assigned_to=assigned_to)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def list_pending_review_items(db: Session, project_id: int) -> list[ReviewItem]:
    return (
        db.query(ReviewItem)
        .join(Entity, Entity.id == ReviewItem.entity_id)
        .join(Document, Document.id == Entity.document_id)
        .filter(Document.project_id == project_id, ReviewItem.status == ReviewStatus.PENDING)
        .all()
    )


# ── Consistency Issues ────────────────────────────────────────────────────────

def bulk_insert_issues(db: Session, issues: list[ConsistencyIssue]) -> None:
    db.bulk_save_objects(issues)
    db.commit()


def list_issues(db: Session, document_id: int) -> list[ConsistencyIssue]:
    return db.query(ConsistencyIssue).filter(ConsistencyIssue.document_id == document_id).all()


# ── Query Logs ────────────────────────────────────────────────────────────────

def log_query(
    db: Session,
    user_id: int,
    project_id: int,
    question: str,
    answer: str,
    citations_json: str,
    confidence: float,
    has_valid_citation: bool,
    document_id: int | None = None,
) -> QueryLog:
    entry = QueryLog(
        user_id=user_id,
        project_id=project_id,
        document_id=document_id,
        question=question,
        answer=answer,
        citations_json=citations_json,
        confidence=confidence,
        has_valid_citation=has_valid_citation,
    )
    db.add(entry)
    db.commit()
    return entry


# ── Audit Log ─────────────────────────────────────────────────────────────────

def list_audit_log(
    db: Session,
    project_id: int | None = None,
    user_id: int | None = None,
    skip: int = 0,
    limit: int = 200,
) -> list[AuditLog]:
    q = db.query(AuditLog)
    if project_id:
        q = q.filter(AuditLog.project_id == project_id)
    if user_id:
        q = q.filter(AuditLog.user_id == user_id)
    return q.order_by(AuditLog.timestamp.desc()).offset(skip).limit(limit).all()


# ── Revision Diffs ────────────────────────────────────────────────────────────

def create_revision_diff(
    db: Session, doc_id_a: int, doc_id_b: int, diff_json: str, created_by: int
) -> RevisionDiff:
    diff = RevisionDiff(
        doc_id_a=doc_id_a, doc_id_b=doc_id_b, diff_json=diff_json, created_by=created_by
    )
    db.add(diff)
    db.commit()
    db.refresh(diff)
    return diff
