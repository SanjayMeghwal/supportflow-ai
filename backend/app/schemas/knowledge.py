"""Pydantic schemas for Knowledge Base ingestion and document management."""

from datetime import datetime
from typing import Any
import uuid
from pydantic import BaseModel, ConfigDict, Field

from backend.app.models.knowledge import SourceType


# ---------------------------------------------------------------------------
# Request Schemas
# ---------------------------------------------------------------------------


class TextDocumentCreateRequest(BaseModel):
    """Schema for direct raw text or markdown document ingestion."""

    model_config = ConfigDict(from_attributes=True)

    title: str = Field(
        ...,
        min_length=3,
        max_length=255,
        description="Descriptive title of the knowledge document.",
        examples=["Return and Refund Policy 2026"],
    )
    content: str = Field(
        ...,
        min_length=10,
        max_length=500_000,
        description="Full text or markdown content of the document.",
    )
    source_type: SourceType = Field(
        default=SourceType.TEXT,
        description="Format of the provided content: TEXT or MARKDOWN.",
    )
    source_uri: str | None = Field(
        default=None,
        max_length=512,
        description="Optional origin URL or reference identifier.",
        examples=["https://company.example.com/policies/refunds"],
    )


class FAQItem(BaseModel):
    """Single question-and-answer pair."""

    question: str = Field(
        ...,
        min_length=3,
        max_length=1000,
        description="Frequently asked customer question.",
    )
    answer: str = Field(
        ...,
        min_length=3,
        max_length=10000,
        description="Authoritative verified answer.",
    )


class FAQDocumentCreateRequest(BaseModel):
    """Schema for structured FAQ ingestion."""

    model_config = ConfigDict(from_attributes=True)

    title: str = Field(
        ...,
        min_length=3,
        max_length=255,
        description="Title of the FAQ category or collection.",
        examples=["Order & Shipping FAQs"],
    )
    faqs: list[FAQItem] = Field(
        ...,
        min_length=1,
        description="List of question-answer pairs to ingest.",
    )
    source_uri: str | None = Field(
        default=None,
        max_length=512,
        description="Optional source link or documentation reference.",
    )


# ---------------------------------------------------------------------------
# Response Schemas
# ---------------------------------------------------------------------------


class DocumentChunkResponse(BaseModel):
    """Schema representing an individual chunk of a document."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    chunk_index: int
    chunk_text: str
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class KnowledgeDocumentResponse(BaseModel):
    """Summary schema for an ingested knowledge document."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    source_type: SourceType
    source_uri: str | None
    checksum_sha256: str
    is_active: bool
    chunk_count: int = 0
    created_at: datetime
    updated_at: datetime


class KnowledgeDocumentDetailResponse(KnowledgeDocumentResponse):
    """Detailed knowledge document view including its constituent chunks."""

    chunks: list[DocumentChunkResponse] = Field(default_factory=list)


class KnowledgeDocumentListResponse(BaseModel):
    """Paginated list of knowledge documents."""

    model_config = ConfigDict(from_attributes=True)

    documents: list[KnowledgeDocumentResponse]
    total: int
    offset: int
    limit: int
