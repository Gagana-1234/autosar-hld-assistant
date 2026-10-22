"""
app/ingestion/chunker.py
Section-aware chunking of extracted PDF pages.

Goals:
- Keep chunks within token budget (configurable, default 400 tokens)
- Preserve heading hierarchy as section_path ("1 > 1.2 > 1.2.3")
- Keep table rows in the same chunk as the table heading
- Record page_start, page_end for every chunk (citation support)
- Overlap between adjacent chunks (default 80 tokens) for context continuity

Output: list of Chunk dataclasses ready for DB + vector store insertion.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from loguru import logger

from app.ingestion.extractor import ExtractionResult, Heading, PageResult

# ── Tokenisation (simple word-count proxy; swap for tiktoken if needed) ────────

try:
    import tiktoken
    _enc = tiktoken.get_encoding("cl100k_base")

    def _count_tokens(text: str) -> int:
        return len(_enc.encode(text))

except ImportError:
    def _count_tokens(text: str) -> int:  # type: ignore[misc]
        return len(text.split())


# ── Data class ────────────────────────────────────────────────────────────────

@dataclass
class Chunk:
    chunk_index: int
    text: str
    page_start: int
    page_end: int
    section_path: str       # e.g. "2 > 2.3 > 2.3.1 Component X"
    token_count: int
    is_table: bool = False
    ocr_fallback: bool = False


# ── Public API ────────────────────────────────────────────────────────────────

def chunk_extraction(
    result: ExtractionResult,
    chunk_size: int = 400,
    overlap: int = 80,
) -> list[Chunk]:
    """
    Chunk an ExtractionResult into overlapping, section-aware chunks.

    Parameters
    ----------
    result      : output of extractor.extract_pdf()
    chunk_size  : maximum tokens per chunk
    overlap     : token overlap between consecutive chunks

    Returns
    -------
    list[Chunk] ordered by document position
    """
    chunks: list[Chunk] = []
    chunk_idx = 0

    # Build a flat list of segments (text blocks + table blocks) with metadata
    segments = _build_segments(result)

    buffer_text = ""
    buffer_pages: list[int] = []
    buffer_section = ""
    buffer_is_table = False
    buffer_ocr = False

    def flush(force: bool = False) -> None:
        nonlocal buffer_text, buffer_pages, buffer_is_table, buffer_ocr, chunk_idx
        text = buffer_text.strip()
        if not text:
            return
        tc = _count_tokens(text)
        if tc == 0:
            return
        chunks.append(Chunk(
            chunk_index=chunk_idx,
            text=text,
            page_start=min(buffer_pages) if buffer_pages else 0,
            page_end=max(buffer_pages) if buffer_pages else 0,
            section_path=buffer_section,
            token_count=tc,
            is_table=buffer_is_table,
            ocr_fallback=buffer_ocr,
        ))
        chunk_idx += 1

        # Carry overlap into the next buffer
        if not force:
            overlap_words = text.split()[-overlap:] if overlap > 0 else []
            buffer_text = " ".join(overlap_words)
            buffer_pages = [buffer_pages[-1]] if buffer_pages else []
        else:
            buffer_text = ""
            buffer_pages = []
        buffer_is_table = False
        buffer_ocr = False

    for seg in segments:
        seg_tokens = _count_tokens(seg["text"])

        # If segment alone exceeds chunk_size, flush current buffer then split segment
        if seg_tokens > chunk_size:
            flush()
            # Hard-split with overlap stride so adjacent pieces share content
            words = seg["text"].split()
            step = max(1, chunk_size - overlap)
            for i in range(0, len(words), step):
                piece = " ".join(words[i: i + chunk_size])
                if not piece.strip():
                    continue
                tc = _count_tokens(piece)
                chunks.append(Chunk(
                    chunk_index=chunk_idx,
                    text=piece,
                    page_start=seg["page"],
                    page_end=seg["page"],
                    section_path=seg["section"],
                    token_count=tc,
                    is_table=seg["is_table"],
                    ocr_fallback=seg["ocr"],
                ))
                chunk_idx += 1
            continue

        # Would adding this segment overflow the buffer?
        current_tokens = _count_tokens(buffer_text)
        if current_tokens + seg_tokens > chunk_size and buffer_text:
            flush()

        # Update section path when a new heading is encountered
        if seg.get("is_heading"):
            buffer_section = seg["section"]

        buffer_text = (buffer_text + "\n\n" + seg["text"]).strip()
        buffer_pages.append(seg["page"])
        if seg["is_table"]:
            buffer_is_table = True
        if seg["ocr"]:
            buffer_ocr = True

    flush(force=True)
    logger.info("Chunking complete: {} chunks produced", len(chunks))
    return chunks


# ── Segment builder ───────────────────────────────────────────────────────────

def _build_segments(result: ExtractionResult) -> list[dict]:
    """
    Convert ExtractionResult pages into a flat list of labelled segments.
    Each segment: {text, page, section, is_table, is_heading, ocr}
    """
    segments: list[dict] = []
    section_stack: list[str] = []   # heading texts by level index

    for page in result.pages:
        # Interleave headings and text paragraphs from the page
        heading_map: dict[str, Heading] = {h.text: h for h in page.headings}

        # Emit heading segments first, then body text paragraphs
        for h in page.headings:
            _update_stack(section_stack, h)
            segments.append({
                "text": h.text,
                "page": page.page_num,
                "section": _stack_path(section_stack),
                "is_table": False,
                "is_heading": True,
                "ocr": page.ocr_used,
            })

        # Split body text into paragraphs
        body = page.text
        # Remove heading texts from body to avoid duplication
        for h in page.headings:
            body = body.replace(h.text, "", 1)

        paragraphs = [p.strip() for p in re.split(r"\n{2,}", body) if p.strip()]
        for para in paragraphs:
            segments.append({
                "text": para,
                "page": page.page_num,
                "section": _stack_path(section_stack),
                "is_table": False,
                "is_heading": False,
                "ocr": page.ocr_used,
            })

        # Emit table segments with heading context prepended
        for table in page.tables:
            table_text = _table_to_text(table)
            segments.append({
                "text": f"[TABLE | {_stack_path(section_stack)}]\n{table_text}",
                "page": page.page_num,
                "section": _stack_path(section_stack),
                "is_table": True,
                "is_heading": False,
                "ocr": page.ocr_used,
            })

    return segments


def _update_stack(stack: list[str], heading: Heading) -> None:
    """Update the running heading stack based on heading level."""
    level = heading.level - 1  # 0-indexed
    while len(stack) > level:
        stack.pop()
    while len(stack) < level:
        stack.append("")
    stack.append(heading.text)


def _stack_path(stack: list[str]) -> str:
    return " > ".join(s for s in stack if s)


def _table_to_text(table: list[list[str]]) -> str:
    """Convert a 2-D table to a readable markdown-ish text representation."""
    if not table:
        return ""
    lines: list[str] = []
    if table:
        header = " | ".join(table[0])
        lines.append(header)
        lines.append("-" * len(header))
        for row in table[1:]:
            lines.append(" | ".join(row))
    return "\n".join(lines)
