"""
app/rag/embedder.py
Embedding provider abstraction.

Supports:
  - sentence-transformers (local, default — BGE-M3 or E5-large)
  - Stub provider for tests (returns deterministic zero vectors)

The active provider is selected by settings.embedding_model.
All providers expose the same interface:
    embed_texts(texts: list[str]) -> list[list[float]]
    embed_query(text: str)        -> list[float]
    dimension: int
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from functools import lru_cache
from typing import Any

from loguru import logger

from app.core.config import get_settings


# ── Abstract base ─────────────────────────────────────────────────────────────

class BaseEmbedder(ABC):
    dimension: int

    @abstractmethod
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts. Returns list of float vectors."""

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query string (same as embed_texts but unwrapped)."""
        return self.embed_texts([text])[0]


# ── Sentence-Transformers provider ────────────────────────────────────────────

class SentenceTransformerEmbedder(BaseEmbedder):
    """Local embedding via sentence-transformers (BAAI/bge-m3 by default)."""

    def __init__(self, model_name: str, batch_size: int = 32):
        from sentence_transformers import SentenceTransformer
        logger.info("Loading embedding model: {}", model_name)
        self._model = SentenceTransformer(model_name)
        self.dimension = self._model.get_sentence_embedding_dimension()
        self._batch_size = batch_size
        logger.info("Embedding model loaded. Dimension: {}", self.dimension)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        embeddings = self._model.encode(
            texts,
            batch_size=self._batch_size,
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        return [e.tolist() for e in embeddings]


# ── Stub provider (tests / offline mode) ──────────────────────────────────────

class StubEmbedder(BaseEmbedder):
    """Deterministic zero-vector embedder for unit tests."""

    def __init__(self, dimension: int = 768):
        self.dimension = dimension

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self.dimension for _ in texts]


# ── Factory with caching ──────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def get_embedder() -> BaseEmbedder:
    """Return a cached embedder instance (loaded once at startup)."""
    settings = get_settings()
    model = settings.embedding_model.lower()

    if model == "stub":
        logger.info("Using StubEmbedder (test/offline mode)")
        return StubEmbedder()

    try:
        return SentenceTransformerEmbedder(
            model_name=settings.embedding_model,
            batch_size=settings.embedding_batch_size,
        )
    except Exception as exc:
        logger.warning(
            "Failed to load embedding model '{}': {}. Falling back to StubEmbedder.",
            settings.embedding_model,
            exc,
        )
        return StubEmbedder()
