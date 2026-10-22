"""
app/rag/vector_store.py
ChromaDB vector store abstraction.

One persistent collection per project:
    collection name: "project_{project_id}"

Each chunk is stored with rich metadata for filtered retrieval:
    document_id, chunk_index, page_start, page_end,
    section_path, is_table, ocr_fallback, version_label

Public API:
    upsert_chunks(project_id, chunks, embeddings, doc_meta)
    query(project_id, query_vector, top_k, filters) -> list[SearchResult]
    delete_document(project_id, document_id)
    collection_exists(project_id) -> bool
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

try:
    import chromadb
    from chromadb.config import Settings as ChromaSettings
    _CHROMA_AVAILABLE = True
except ImportError:
    _CHROMA_AVAILABLE = False
    chromadb = None  # type: ignore[assignment]
    ChromaSettings = None  # type: ignore[assignment]
from loguru import logger

from app.core.config import get_settings
from app.ingestion.chunker import Chunk


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class SearchResult:
    chunk_index: int
    document_id: int
    text: str
    score: float                # cosine distance (lower = more similar)
    page_start: int
    page_end: int
    section_path: str
    is_table: bool
    version_label: str
    metadata: dict[str, Any]


# ── Client factory ────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _get_client() -> "chromadb.Client":
    if not _CHROMA_AVAILABLE:
        raise ImportError(
            "chromadb is not installed. Run: pip install chromadb"
        )
    settings = get_settings()
    persist_dir = Path(settings.chroma_persist_dir)
    persist_dir.mkdir(parents=True, exist_ok=True)
    logger.info("ChromaDB persist dir: {}", persist_dir.resolve())
    return chromadb.PersistentClient(
        path=str(persist_dir),
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def _collection_name(project_id: int) -> str:
    return f"project_{project_id}"


def _get_collection(project_id: int):
    client = _get_client()
    return client.get_or_create_collection(
        name=_collection_name(project_id),
        metadata={"hnsw:space": "cosine"},
    )


# ── Public functions ──────────────────────────────────────────────────────────

def upsert_chunks(
    project_id: int,
    chunks: list[Chunk],
    embeddings: list[list[float]],
    document_id: int,
    version_label: str,
) -> None:
    """
    Upsert chunk embeddings into the project collection.
    IDs are deterministic: "doc_{doc_id}_chunk_{chunk_index}".
    """
    if not chunks:
        return

    collection = _get_collection(project_id)
    ids = [f"doc_{document_id}_chunk_{c.chunk_index}" for c in chunks]
    documents = [c.text for c in chunks]
    metadatas = [
        {
            "document_id": document_id,
            "chunk_index": c.chunk_index,
            "page_start": c.page_start,
            "page_end": c.page_end,
            "section_path": c.section_path,
            "is_table": int(c.is_table),        # Chroma stores as int
            "ocr_fallback": int(c.ocr_fallback),
            "version_label": version_label,
            "token_count": c.token_count,
        }
        for c in chunks
    ]

    collection.upsert(
        ids=ids,
        embeddings=embeddings,
        documents=documents,
        metadatas=metadatas,
    )
    logger.info(
        "Upserted {} chunks for doc {} into collection project_{}",
        len(chunks), document_id, project_id,
    )


def query(
    project_id: int,
    query_vector: list[float],
    top_k: int = 5,
    filters: dict[str, Any] | None = None,
) -> list[SearchResult]:
    """
    Semantic search within a project collection.

    Parameters
    ----------
    project_id   : restricts search to this project's collection
    query_vector : embedding of the user's question
    top_k        : number of results to return
    filters      : Chroma where-clause dict, e.g. {"is_table": 1} or
                   {"document_id": 42}

    Returns
    -------
    list[SearchResult] sorted by score ascending (best first)
    """
    collection = _get_collection(project_id)

    kwargs: dict[str, Any] = {
        "query_embeddings": [query_vector],
        "n_results": min(top_k, collection.count() or 1),
        "include": ["documents", "metadatas", "distances"],
    }
    if filters:
        kwargs["where"] = filters

    try:
        results = collection.query(**kwargs)
    except Exception as exc:
        logger.error("ChromaDB query failed for project {}: {}", project_id, exc)
        return []

    search_results: list[SearchResult] = []
    ids_list = results.get("ids", [[]])[0]
    docs_list = results.get("documents", [[]])[0]
    metas_list = results.get("metadatas", [[]])[0]
    dists_list = results.get("distances", [[]])[0]

    for _id, doc, meta, dist in zip(ids_list, docs_list, metas_list, dists_list):
        search_results.append(SearchResult(
            chunk_index=meta.get("chunk_index", -1),
            document_id=meta.get("document_id", -1),
            text=doc,
            score=dist,
            page_start=meta.get("page_start", 0),
            page_end=meta.get("page_end", 0),
            section_path=meta.get("section_path", ""),
            is_table=bool(meta.get("is_table", 0)),
            version_label=meta.get("version_label", ""),
            metadata=meta,
        ))

    return search_results


def delete_document(project_id: int, document_id: int) -> None:
    """Remove all chunks belonging to a document from the project collection."""
    collection = _get_collection(project_id)
    collection.delete(where={"document_id": document_id})
    logger.info(
        "Deleted all chunks for doc {} from collection project_{}",
        document_id, project_id,
    )


def collection_exists(project_id: int) -> bool:
    """Check whether a collection exists for the given project."""
    client = _get_client()
    names = [c.name for c in client.list_collections()]
    return _collection_name(project_id) in names
