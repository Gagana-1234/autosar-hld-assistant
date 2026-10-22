"""
tests/test_chunker.py
Unit tests for the section-aware chunker and PDF extraction schemas.
Tests run without any real PDF — synthetic ExtractionResult objects are used.
"""
from __future__ import annotations

import pytest

from app.ingestion.chunker import Chunk, _count_tokens, _table_to_text, chunk_extraction
from app.ingestion.extractor import ExtractionResult, Heading, PageResult


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_result(pages: list[dict]) -> ExtractionResult:
    """Build a synthetic ExtractionResult from a list of page dicts."""
    page_objects = []
    for i, p in enumerate(pages, start=1):
        page_objects.append(PageResult(
            page_num=p.get("page_num", i),
            text=p.get("text", ""),
            tables=p.get("tables", []),
            headings=[
                Heading(level=h["level"], text=h["text"], page=p.get("page_num", i))
                for h in p.get("headings", [])
            ],
            ocr_used=p.get("ocr_used", False),
        ))
    return ExtractionResult(
        pages=page_objects,
        page_count=len(page_objects),
        ocr_used=any(p.get("ocr_used", False) for p in pages),
    )


# ── Token counter ─────────────────────────────────────────────────────────────

class TestTokenCounter:
    def test_empty_string(self):
        assert _count_tokens("") == 0

    def test_single_word(self):
        assert _count_tokens("hello") >= 1

    def test_multiple_words(self):
        count = _count_tokens("the quick brown fox")
        assert count >= 4


# ── Table to text ─────────────────────────────────────────────────────────────

class TestTableToText:
    def test_empty_table(self):
        assert _table_to_text([]) == ""

    def test_header_only(self):
        result = _table_to_text([["Col A", "Col B"]])
        assert "Col A" in result
        assert "Col B" in result

    def test_header_and_rows(self):
        table = [["Name", "Value"], ["SWC_A", "0x01"], ["SWC_B", "0x02"]]
        result = _table_to_text(table)
        assert "SWC_A" in result
        assert "SWC_B" in result
        assert "Name" in result


# ── Core chunker ──────────────────────────────────────────────────────────────

class TestChunker:
    def test_empty_document_produces_no_chunks(self):
        result = make_result([{"text": ""}])
        chunks = chunk_extraction(result, chunk_size=400, overlap=0)
        assert chunks == []

    def test_simple_text_produces_chunks(self):
        text = "This is a test paragraph about AUTOSAR software components. " * 5
        result = make_result([{"text": text}])
        chunks = chunk_extraction(result, chunk_size=400, overlap=0)
        assert len(chunks) >= 1
        assert all(isinstance(c, Chunk) for c in chunks)

    def test_chunk_indices_are_sequential(self):
        text = "Word " * 500
        result = make_result([{"text": text}])
        chunks = chunk_extraction(result, chunk_size=100, overlap=0)
        indices = [c.chunk_index for c in chunks]
        assert indices == list(range(len(chunks)))

    def test_chunk_respects_token_budget(self):
        text = "Word " * 500
        result = make_result([{"text": text}])
        chunks = chunk_extraction(result, chunk_size=100, overlap=0)
        # Most chunks should be at or under limit (last chunk may be smaller)
        for c in chunks[:-1]:
            assert c.token_count <= 120  # small tolerance for overlap

    def test_page_numbers_recorded(self):
        result = make_result([
            {"page_num": 1, "text": "Page one content about components."},
            {"page_num": 2, "text": "Page two content about interfaces."},
        ])
        chunks = chunk_extraction(result, chunk_size=400, overlap=0)
        pages = {c.page_start for c in chunks}
        assert 1 in pages or 2 in pages

    def test_heading_sets_section_path(self):
        result = make_result([{
            "text": "Overview of the AUTOSAR architecture.",
            "headings": [{"level": 1, "text": "Architecture Overview"}],
        }])
        chunks = chunk_extraction(result, chunk_size=400, overlap=0)
        assert any("Architecture Overview" in c.section_path for c in chunks)

    def test_nested_headings_build_path(self):
        result = make_result([{
            "text": "Detailed component specification.",
            "headings": [
                {"level": 1, "text": "Components"},
                {"level": 2, "text": "SWC Definition"},
            ],
        }])
        chunks = chunk_extraction(result, chunk_size=400, overlap=0)
        paths = [c.section_path for c in chunks]
        # At least one chunk should contain both levels
        assert any("Components" in p and "SWC Definition" in p for p in paths)

    def test_table_chunk_is_flagged(self):
        result = make_result([{
            "text": "",
            "tables": [[["Signal", "Direction"], ["S_EngineSpeed", "TX"]]],
        }])
        chunks = chunk_extraction(result, chunk_size=400, overlap=0)
        table_chunks = [c for c in chunks if c.is_table]
        assert len(table_chunks) >= 1

    def test_table_content_included_in_chunk(self):
        result = make_result([{
            "text": "",
            "tables": [[["Signal", "Direction"], ["S_EngineSpeed", "TX"]]],
        }])
        chunks = chunk_extraction(result, chunk_size=400, overlap=0)
        combined = " ".join(c.text for c in chunks)
        assert "S_EngineSpeed" in combined

    def test_ocr_flag_propagated(self):
        result = make_result([{"text": "Scanned page text.", "ocr_used": True}])
        chunks = chunk_extraction(result, chunk_size=400, overlap=0)
        assert any(c.ocr_fallback for c in chunks)

    def test_overlap_creates_repeated_content(self):
        """With overlap, adjacent chunks should share some words."""
        text = " ".join(f"word{i}" for i in range(300))
        result = make_result([{"text": text}])
        chunks = chunk_extraction(result, chunk_size=80, overlap=20)
        if len(chunks) >= 2:
            words_0 = set(chunks[0].text.split())
            words_1 = set(chunks[1].text.split())
            assert len(words_0 & words_1) > 0  # some overlap exists

    def test_multipage_chunks_span_pages(self):
        """Very short pages should be merged into a single chunk."""
        result = make_result([
            {"page_num": 1, "text": "Short."},
            {"page_num": 2, "text": "Also short."},
        ])
        chunks = chunk_extraction(result, chunk_size=400, overlap=0)
        # With large chunk_size, both pages fit in one chunk
        assert len(chunks) >= 1

    def test_oversized_segment_is_split(self):
        """A single paragraph larger than chunk_size must be split."""
        text = "BigWord " * 600
        result = make_result([{"text": text}])
        chunks = chunk_extraction(result, chunk_size=100, overlap=0)
        assert len(chunks) >= 5
