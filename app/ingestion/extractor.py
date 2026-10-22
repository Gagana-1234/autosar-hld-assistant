"""
app/ingestion/extractor.py
PDF text, table, and heading extraction.

Strategy (layered):
1. PyMuPDF  — native text + heading detection via font size heuristics
2. pdfplumber — structured table extraction
3. Tesseract OCR — fallback for pages with no extractable text (scanned)

Every page result carries:
  - page_num  : 1-indexed page number
  - text      : plain text (may be OCR output)
  - tables    : list of 2-D cell lists  [[row], [row], ...]
  - headings  : list of {level, text, page}
  - ocr_used  : bool
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

# ── Optional imports with graceful degradation ────────────────────────────────

try:
    import fitz  # PyMuPDF
    _FITZ_AVAILABLE = True
except ImportError:
    _FITZ_AVAILABLE = False
    logger.warning("PyMuPDF (fitz) not installed — text extraction will be limited")

try:
    import pdfplumber
    _PDFPLUMBER_AVAILABLE = True
except ImportError:
    _PDFPLUMBER_AVAILABLE = False
    logger.warning("pdfplumber not installed — table extraction disabled")

try:
    import pytesseract
    from PIL import Image
    _OCR_AVAILABLE = True
except ImportError:
    _OCR_AVAILABLE = False
    logger.warning("pytesseract/Pillow not installed — OCR fallback disabled")


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class Heading:
    level: int          # 1 = largest heading, 2, 3 …
    text: str
    page: int


@dataclass
class PageResult:
    page_num: int
    text: str
    tables: list[list[list[str]]] = field(default_factory=list)
    headings: list[Heading] = field(default_factory=list)
    ocr_used: bool = False


@dataclass
class ExtractionResult:
    pages: list[PageResult]
    page_count: int
    ocr_used: bool          # True if ANY page used OCR
    metadata: dict[str, Any] = field(default_factory=dict)


# ── Main extractor ────────────────────────────────────────────────────────────

def extract_pdf(content: bytes, ocr_dpi: int = 300) -> ExtractionResult:
    """
    Extract all content from a PDF byte string.

    Parameters
    ----------
    content  : raw PDF bytes
    ocr_dpi  : resolution for OCR rendering (higher = better quality, slower)

    Returns
    -------
    ExtractionResult
    """
    pages: list[PageResult] = []
    any_ocr = False
    metadata: dict[str, Any] = {}

    if not _FITZ_AVAILABLE:
        raise RuntimeError("PyMuPDF is required for PDF extraction")

    # Open with PyMuPDF
    fitz_doc = fitz.open(stream=content, filetype="pdf")
    page_count = len(fitz_doc)

    # Extract PDF metadata
    meta = fitz_doc.metadata or {}
    metadata = {
        "title": meta.get("title", ""),
        "author": meta.get("author", ""),
        "subject": meta.get("subject", ""),
        "creator": meta.get("creator", ""),
        "page_count": page_count,
    }

    # Open with pdfplumber for table extraction (if available)
    plumber_doc = None
    if _PDFPLUMBER_AVAILABLE:
        try:
            plumber_doc = pdfplumber.open(io.BytesIO(content))
        except Exception as exc:
            logger.warning("pdfplumber failed to open PDF: {}", exc)

    for page_idx in range(page_count):
        page_num = page_idx + 1
        fitz_page = fitz_doc[page_idx]

        # ── Native text extraction ─────────────────────────────────────────
        text = fitz_page.get_text("text").strip()
        ocr_used = False

        # ── Heading detection from font sizes ──────────────────────────────
        headings = _extract_headings(fitz_page, page_num)

        # ── Table extraction via pdfplumber ────────────────────────────────
        tables: list[list[list[str]]] = []
        if plumber_doc:
            try:
                plumber_page = plumber_doc.pages[page_idx]
                raw_tables = plumber_page.extract_tables()
                for raw_table in (raw_tables or []):
                    # Clean cells: replace None with ""
                    clean = [
                        [(cell or "").strip() for cell in row]
                        for row in raw_table
                        if row
                    ]
                    if clean:
                        tables.append(clean)
            except Exception as exc:
                logger.warning("Table extraction failed on page {}: {}", page_num, exc)

        # ── OCR fallback for scanned pages ─────────────────────────────────
        if not text and _OCR_AVAILABLE:
            logger.info("Page {} has no extractable text — falling back to OCR", page_num)
            try:
                text = _ocr_page(fitz_page, dpi=ocr_dpi)
                ocr_used = True
                any_ocr = True
            except Exception as exc:
                logger.error("OCR failed on page {}: {}", page_num, exc)
                text = ""

        pages.append(PageResult(
            page_num=page_num,
            text=text,
            tables=tables,
            headings=headings,
            ocr_used=ocr_used,
        ))

    fitz_doc.close()
    if plumber_doc:
        plumber_doc.close()

    return ExtractionResult(
        pages=pages,
        page_count=page_count,
        ocr_used=any_ocr,
        metadata=metadata,
    )


# ── Heading detection ─────────────────────────────────────────────────────────

def _extract_headings(page, page_num: int) -> list[Heading]:
    """
    Heuristic heading detection: text blocks with above-average font size
    are ranked as heading levels 1–3.
    """
    try:
        blocks = page.get_text("dict").get("blocks", [])
    except Exception:
        return []

    # Collect all font sizes
    all_sizes: list[float] = []
    spans_data: list[tuple[float, str]] = []

    for block in blocks:
        if block.get("type") != 0:  # 0 = text block
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                size = span.get("size", 0)
                text = span.get("text", "").strip()
                if text:
                    all_sizes.append(size)
                    spans_data.append((size, text))

    if not all_sizes:
        return []

    avg_size = sum(all_sizes) / len(all_sizes)
    max_size = max(all_sizes)

    headings: list[Heading] = []
    seen: set[str] = set()

    for size, text in spans_data:
        if size <= avg_size * 1.15:
            continue
        if text in seen or len(text) > 200:
            continue
        seen.add(text)

        # Assign heading level by relative size
        ratio = size / max_size
        if ratio >= 0.9:
            level = 1
        elif ratio >= 0.75:
            level = 2
        else:
            level = 3

        headings.append(Heading(level=level, text=text, page=page_num))

    return headings


# ── OCR helper ────────────────────────────────────────────────────────────────

def _ocr_page(fitz_page, dpi: int = 300) -> str:
    """Render a PDF page to image and run Tesseract OCR."""
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = fitz_page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
    img_bytes = pix.tobytes("png")
    image = Image.open(io.BytesIO(img_bytes))
    text = pytesseract.image_to_string(image, lang="eng")
    return text.strip()
