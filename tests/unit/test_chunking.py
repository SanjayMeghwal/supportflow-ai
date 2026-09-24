"""Unit tests for RecursiveTextChunker and document extractors."""

import io
import json
import pytest
from pypdf import PdfWriter

from backend.app.models.knowledge import SourceType
from backend.app.services.chunking import RecursiveTextChunker
from backend.app.services.extractors import (
    ExtractionError,
    detect_source_type,
    extract_text,
)


def _create_mock_pdf_bytes(pages: list[str]) -> bytes:
    """Helper to generate in-memory PDF bytes with text content."""
    writer = PdfWriter()
    for page_text in pages:
        writer.add_blank_page(width=72 * 8.5, height=72 * 11)
    # pypdf PdfWriter can write pages; for extraction test, writer.pages exists
    # If blank page has no text, let's write to stream
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


# ---------------------------------------------------------------------------
# Chunker Validation & Core Splitting Tests
# ---------------------------------------------------------------------------


def test_chunker_parameter_validation():
    """Verify chunker rejects invalid chunk_size and chunk_overlap combinations."""
    with pytest.raises(ValueError, match="chunk_size must be positive"):
        RecursiveTextChunker(chunk_size=0)

    with pytest.raises(ValueError, match="chunk_size must be positive"):
        RecursiveTextChunker(chunk_size=-10)

    with pytest.raises(ValueError, match="chunk_overlap cannot be negative"):
        RecursiveTextChunker(chunk_size=100, chunk_overlap=-1)

    with pytest.raises(ValueError, match="strictly less than"):
        RecursiveTextChunker(chunk_size=100, chunk_overlap=100)

    with pytest.raises(ValueError, match="strictly less than"):
        RecursiveTextChunker(chunk_size=100, chunk_overlap=120)


def test_empty_or_whitespace_text():
    """Empty or whitespace text produces no chunks."""
    chunker = RecursiveTextChunker(chunk_size=200, chunk_overlap=20)
    assert chunker.split_text("") == []
    assert chunker.split_text("   \n\n\t   ") == []


def test_short_text_single_chunk():
    """Text smaller than chunk_size produces exactly 1 chunk."""
    chunker = RecursiveTextChunker(chunk_size=300, chunk_overlap=30)
    text = "SupportFlow AI provides enterprise-grade customer support."
    chunks = chunker.split_text(text, document_metadata={"doc_id": "123"})

    assert len(chunks) == 1
    assert chunks[0].chunk_index == 0
    assert chunks[0].text == text
    assert chunks[0].metadata["doc_id"] == "123"
    assert chunks[0].metadata["char_count"] == len(text)
    assert chunks[0].metadata["word_count"] == len(text.split())


def test_paragraph_splitting():
    """Paragraph breaks (double newline) are preferred split points."""
    chunker = RecursiveTextChunker(chunk_size=120, chunk_overlap=20)
    p1 = "Paragraph 1: Customers can request refunds within 30 days of initial purchase."
    p2 = "Paragraph 2: Items must be in their original packaging with all tags attached."
    p3 = "Paragraph 3: Shipping fees are non-refundable except for damaged items."
    text = f"{p1}\n\n{p2}\n\n{p3}"

    chunks = chunker.split_text(text)
    assert len(chunks) >= 3
    # Verify sequential indexing
    for i, c in enumerate(chunks):
        assert c.chunk_index == i
        assert len(c.text) > 0


def test_sentence_splitting():
    """Sentences are preserved without breaking mid-word when paragraphs exceed size."""
    chunker = RecursiveTextChunker(chunk_size=100, chunk_overlap=20)
    text = (
        "SupportFlow AI is built for reliability. "
        "It uses pgvector for search. "
        "It uses Groq for high-speed inference. "
        "All customer tickets are strictly isolated."
    )
    chunks = chunker.split_text(text)
    assert len(chunks) >= 2
    for chunk in chunks:
        # None of the chunks should have empty text
        assert len(chunk.text) > 0
        # Words should remain intact
        assert not chunk.text.endswith("pgvec")


def test_metadata_propagation():
    """Document-level metadata is included in all output chunks."""
    chunker = RecursiveTextChunker(chunk_size=40, chunk_overlap=10)
    text = "Section A covers billing rules.\n\nSection B covers delivery timelines."
    chunks = chunker.split_text(text, document_metadata={"title": "Policy", "tier": "enterprise"})

    assert len(chunks) >= 2
    for chunk in chunks:
        assert chunk.metadata["title"] == "Policy"
        assert chunk.metadata["tier"] == "enterprise"
        assert "char_count" in chunk.metadata
        assert "word_count" in chunk.metadata


# ---------------------------------------------------------------------------
# Extractor Tests
# ---------------------------------------------------------------------------


def test_detect_source_type():
    """detect_source_type resolves standard file extensions correctly."""
    assert detect_source_type("policy.pdf") == SourceType.PDF
    assert detect_source_type("readme.md") == SourceType.MARKDOWN
    assert detect_source_type("notes.markdown") == SourceType.MARKDOWN
    assert detect_source_type("info.txt") == SourceType.TEXT
    assert detect_source_type("log.text") == SourceType.TEXT
    assert detect_source_type("faq.json") == SourceType.FAQ

    # Explicit override takes precedence
    assert detect_source_type("test.txt", explicit_type=SourceType.FAQ) == SourceType.FAQ

    with pytest.raises(ExtractionError, match="Unsupported file format"):
        detect_source_type("image.png")


def test_extract_text_markdown_and_plain():
    """Plain text and markdown bytes are properly decoded and normalized."""
    raw_md = b"# Policy\n\n- Free returns\n- 30 day window\r\n"
    text, meta = extract_text(raw_md, SourceType.MARKDOWN, filename="policy.md")
    assert "# Policy" in text
    assert "30 day window" in text
    assert meta["format"] == "markdown"
    assert meta["filename"] == "policy.md"


def test_extract_text_faq_json():
    """FAQ JSON structures are formatted into clear Q&A text blocks."""
    faq_data = [
        {"question": "How do I cancel my order?", "answer": "Go to order history and click Cancel."},
        {"q": "How long does a refund take?", "a": "Refunds take 5-7 business days."},
    ]
    raw_json = json.dumps(faq_data).encode("utf-8")
    text, meta = extract_text(raw_json, SourceType.FAQ, filename="faq.json")

    assert "Q: How do I cancel my order?" in text
    assert "A: Go to order history and click Cancel." in text
    assert "Q: How long does a refund take?" in text
    assert "A: Refunds take 5-7 business days." in text
    assert meta["format"] == "faq"
    assert meta["faq_count"] == 2


def test_extract_faq_invalid_format():
    """Malformed or invalid FAQ JSON raises ExtractionError."""
    with pytest.raises(ExtractionError, match="Failed to parse FAQ JSON"):
        extract_text(b"not json", SourceType.FAQ, filename="bad.json")

    with pytest.raises(ExtractionError, match="must be a list of"):
        extract_text(json.dumps({"number": 42}).encode("utf-8"), SourceType.FAQ)

    with pytest.raises(ExtractionError, match="no question-answer pairs"):
        extract_text(json.dumps([]).encode("utf-8"), SourceType.FAQ)


def test_extract_empty_bytes_raises_error():
    """Empty bytes fail extraction immediately."""
    with pytest.raises(ExtractionError, match="cannot be empty"):
        extract_text(b"", SourceType.TEXT)
