"""
tests/test_rag.py
Unit tests for the RAG pipeline components:
  - StubEmbedder
  - StubLLMProvider
  - MMR re-ranking logic
  - run_rag end-to-end with stub backends
"""
from __future__ import annotations

import os
import pytest

# Force stub backends for all RAG tests
os.environ["TESTING"] = "1"
os.environ["EMBEDDING_MODEL"] = "stub"
os.environ["LLM_PROVIDER"] = "stub"


from app.rag.embedder import StubEmbedder
from app.rag.llm_provider import StubLLMProvider
from app.rag.retriever import _mmr_rerank, _text_overlap
from app.rag.vector_store import SearchResult


# ── StubEmbedder ──────────────────────────────────────────────────────────────

class TestStubEmbedder:
    def test_embed_returns_correct_dimension(self):
        emb = StubEmbedder(dimension=768)
        vecs = emb.embed_texts(["hello", "world"])
        assert len(vecs) == 2
        assert len(vecs[0]) == 768

    def test_embed_returns_zeros(self):
        emb = StubEmbedder(dimension=64)
        vec = emb.embed_query("test query")
        assert all(v == 0.0 for v in vec)

    def test_embed_empty_list(self):
        emb = StubEmbedder()
        assert emb.embed_texts([]) == []

    def test_custom_dimension(self):
        emb = StubEmbedder(dimension=1024)
        vec = emb.embed_query("x")
        assert len(vec) == 1024


# ── StubLLM ───────────────────────────────────────────────────────────────────

class TestStubLLM:
    def test_generate_returns_string(self):
        llm = StubLLMProvider()
        result = llm.generate("What is a SWC?")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_generate_with_system_prompt(self):
        llm = StubLLMProvider()
        result = llm.generate("hello", system="You are helpful")
        assert isinstance(result, str)


# ── Text overlap ──────────────────────────────────────────────────────────────

class TestTextOverlap:
    def test_identical_texts_overlap_is_1(self):
        assert _text_overlap("the cat sat", "the cat sat") == 1.0

    def test_no_overlap_is_0(self):
        assert _text_overlap("abc def", "xyz uvw") == 0.0

    def test_partial_overlap(self):
        score = _text_overlap("cat dog bird", "cat fish tree")
        assert 0.0 < score < 1.0

    def test_empty_strings(self):
        assert _text_overlap("", "") == 0.0


# ── MMR re-ranking ────────────────────────────────────────────────────────────

def make_result(doc_id: int, text: str, score: float = 0.2) -> SearchResult:
    return SearchResult(
        chunk_index=doc_id,
        document_id=doc_id,
        text=text,
        score=score,
        page_start=1,
        page_end=1,
        section_path="",
        is_table=False,
        version_label="v1",
        metadata={},
    )


class TestMMR:
    def test_returns_top_k_results(self):
        candidates = [
            make_result(i, f"unique content about topic {i}")
            for i in range(10)
        ]
        query_vec = [0.0] * 768
        result = _mmr_rerank(query_vec, candidates, top_k=3, lambda_=0.7)
        assert len(result) == 3

    def test_empty_candidates_returns_empty(self):
        result = _mmr_rerank([0.0] * 768, [], top_k=5, lambda_=0.7)
        assert result == []

    def test_fewer_candidates_than_top_k(self):
        candidates = [make_result(i, f"content {i}") for i in range(2)]
        result = _mmr_rerank([0.0] * 768, candidates, top_k=5, lambda_=0.7)
        assert len(result) == 2

    def test_diverse_texts_selected(self):
        """With lambda=0 (pure diversity), MMR should prefer dissimilar chunks."""
        candidates = [
            make_result(0, "SWC component interface port signal"),
            make_result(1, "SWC component interface port signal"),  # near duplicate
            make_result(2, "memory map EEPROM storage address layout"),
        ]
        query_vec = [0.0] * 768
        result = _mmr_rerank(query_vec, candidates, top_k=2, lambda_=0.0)
        texts = [r.text for r in result]
        # The memory map chunk should be selected (diversity)
        assert any("memory" in t or "EEPROM" in t for t in texts)

    def test_relevance_mode_returns_best_scoring(self):
        """With lambda=1 (pure relevance), first candidate (lowest distance) wins."""
        candidates = [
            make_result(0, "best match", score=0.05),
            make_result(1, "mediocre", score=0.30),
            make_result(2, "worst",    score=0.50),
        ]
        query_vec = [0.0] * 768
        result = _mmr_rerank(query_vec, candidates, top_k=1, lambda_=1.0)
        assert result[0].document_id == 0  # lowest distance = most relevant


# ── RAG pipeline (stub end-to-end) ────────────────────────────────────────────

class TestRAGPipeline:
    def test_run_rag_no_results_returns_no_info_message(self, monkeypatch):
        """When vector store returns nothing, pipeline returns graceful message."""
        from app.rag import pipeline as rag_pipeline
        monkeypatch.setattr(
            "app.rag.pipeline.retrieve",
            lambda **kw: [],
        )
        # Use an in-memory SQLite session
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.db.models import Base

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()

        result = rag_pipeline.run_rag("What is SWC?", project_id=1, db=db)
        assert "do not contain" in result.answer.lower() or "not contain" in result.answer.lower()
        assert result.retrieved_chunks == 0
        assert result.citations == []
        db.close()

    def test_run_rag_with_results_calls_llm(self, monkeypatch):
        """When chunks are found, LLM is called and answer is returned."""
        from app.rag import pipeline as rag_pipeline

        fake_results = [
            make_result(1, "SWC stands for Software Component in AUTOSAR.", 0.1),
        ]
        monkeypatch.setattr(
            "app.rag.pipeline.retrieve",
            lambda **kw: fake_results,
        )
        monkeypatch.setattr(
            "app.rag.pipeline.get_llm",
            lambda: StubLLMProvider(),
        )

        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.db.models import Base

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()

        result = rag_pipeline.run_rag("What is SWC?", project_id=1, db=db)
        assert isinstance(result.answer, str)
        assert len(result.answer) > 0
        assert result.retrieved_chunks == 1
        assert len(result.citations) == 1
        db.close()
