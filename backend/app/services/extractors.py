"""Document extractors for converting raw bytes (PDF, Markdown, Text, FAQ) into normalized text."""

import io
import json
from pathlib import Path
from typing import Any
from pypdf import PdfReader

from backend.app.models.knowledge import SourceType


class ExtractionError(Exception):
    """Raised when document extraction fails due to formatting or corruption."""

    pass


def detect_source_type(filename: str, explicit_type: SourceType | None = None) -> SourceType:
    """Infer the SourceType from file extension if not explicitly specified."""
    if explicit_type is not None:
        return explicit_type

    ext = Path(filename).suffix.lower()
    mapping = {
        ".pdf": SourceType.PDF,
        ".md": SourceType.MARKDOWN,
        ".markdown": SourceType.MARKDOWN,
        ".txt": SourceType.TEXT,
        ".text": SourceType.TEXT,
        ".json": SourceType.FAQ,
    }
    source_type = mapping.get(ext)
    if source_type is None:
        raise ExtractionError(
            f"Unsupported file format '{ext}'. Supported formats: .pdf, .md, .txt, .json"
        )
    return source_type


def extract_text(
    content_bytes: bytes,
    source_type: SourceType,
    filename: str = "document",
) -> tuple[str, dict[str, Any]]:
    """Extract plain text and structural metadata from raw document bytes.

    Returns:
        tuple[str, dict[str, Any]]: (normalized_extracted_text, metadata_dict)

    Raises:
        ExtractionError: If content is corrupted or violates parsing constraints.
    """
    if not content_bytes:
        raise ExtractionError("Document content cannot be empty.")

    if source_type in (SourceType.TEXT, SourceType.MARKDOWN):
        return _extract_plain_or_markdown(content_bytes, source_type, filename)
    elif source_type == SourceType.FAQ:
        return _extract_faq(content_bytes, filename)
    elif source_type == SourceType.PDF:
        return _extract_pdf(content_bytes, filename)
    else:
        raise ExtractionError(f"Unsupported source type: {source_type}")


def _extract_plain_or_markdown(
    content_bytes: bytes,
    source_type: SourceType,
    filename: str,
) -> tuple[str, dict[str, Any]]:
    """Extract plain text or markdown from UTF-8 bytes."""
    try:
        text = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        try:
            # Fallback to latin-1 if non-strict UTF-8
            text = content_bytes.decode("latin-1")
        except Exception as exc:
            raise ExtractionError(f"Unable to decode text file '{filename}': {exc}") from exc

    cleaned = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not cleaned:
        raise ExtractionError(f"Document '{filename}' contains no readable text.")

    metadata = {
        "filename": filename,
        "format": source_type.value.lower(),
        "total_chars": len(cleaned),
    }
    return cleaned, metadata


def _extract_faq(content_bytes: bytes, filename: str) -> tuple[str, dict[str, Any]]:
    """Extract FAQ question-answer pairs from JSON formatted bytes."""
    try:
        raw_str = content_bytes.decode("utf-8")
        data = json.loads(raw_str)
    except Exception as exc:
        raise ExtractionError(f"Failed to parse FAQ JSON '{filename}': {exc}") from exc

    items: list[dict[str, Any]]
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict) and "faqs" in data and isinstance(data["faqs"], list):
        items = data["faqs"]
    else:
        raise ExtractionError(
            "FAQ JSON must be a list of {'question', 'answer'} or an object with a 'faqs' array."
        )

    if not items:
        raise ExtractionError("FAQ document contains no question-answer pairs.")

    formatted_sections: list[str] = []
    for idx, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        q = item.get("question") or item.get("q")
        a = item.get("answer") or item.get("a")
        if not q or not a:
            continue
        formatted_sections.append(f"Q: {str(q).strip()}\nA: {str(a).strip()}")

    if not formatted_sections:
        raise ExtractionError("No valid question-answer pairs found in FAQ JSON.")

    combined_text = "\n\n".join(formatted_sections)
    metadata = {
        "filename": filename,
        "format": "faq",
        "faq_count": len(formatted_sections),
        "total_chars": len(combined_text),
    }
    return combined_text, metadata


def _extract_pdf(content_bytes: bytes, filename: str) -> tuple[str, dict[str, Any]]:
    """Extract text from a PDF document using pypdf."""
    try:
        stream = io.BytesIO(content_bytes)
        reader = PdfReader(stream)
    except Exception as exc:
        raise ExtractionError(f"Failed to read PDF file '{filename}': {exc}") from exc

    page_texts: list[str] = []
    total_pages = len(reader.pages)
    if total_pages == 0:
        raise ExtractionError(f"PDF file '{filename}' has no pages.")

    for page_num, page in enumerate(reader.pages, start=1):
        try:
            page_content = page.extract_text() or ""
            cleaned_page = page_content.strip()
            if cleaned_page:
                page_texts.append(cleaned_page)
        except Exception as exc:
            # If an individual page fails to extract, continue with remaining pages
            continue

    if not page_texts:
        raise ExtractionError(f"No readable text could be extracted from PDF '{filename}'.")

    combined_text = "\n\n".join(page_texts)
    metadata = {
        "filename": filename,
        "format": "pdf",
        "page_count": total_pages,
        "extracted_pages": len(page_texts),
        "total_chars": len(combined_text),
    }
    return combined_text, metadata
