"""Pydantic schemas for Knowledge Base ingestion and document management."""

from datetime import datetime
from enum import Enum
from typing import Any
import uuid
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.models.knowledge import SourceType


class SearchType(str, Enum):
    """Retrieval mode for the knowledge search endpoint.

    vector    — Dense semantic search using pgvector cosine similarity (Phase 7
                default, preserved for backward compatibility).
    full_text — PostgreSQL Full-Text Search using GIN-indexed tsvector with
                websearch_to_tsquery.  Best for exact terminology and keyword
                queries.
    hybrid    — Combines vector and FTS candidates via Reciprocal Rank Fusion.
                Generally the highest quality mode for mixed natural-language
                and technical-term queries.
    """

    VECTOR = "vector"
    FULL_TEXT = "full_text"
    HYBRID = "hybrid"


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


# ---------------------------------------------------------------------------
# Search Schemas (Phase 7)
# ---------------------------------------------------------------------------


class KnowledgeSearchRequest(BaseModel):
    """Knowledge search query request supporting vector, full-text, and hybrid modes."""

    model_config = ConfigDict(from_attributes=True)

    query: str = Field(
        ...,
        min_length=2,
        max_length=1000,
        description="Natural language query string for semantic retrieval.",
        examples=["What is the refund timeline for cancelled orders?"],
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Maximum number of relevant chunks to retrieve (1-50).",
    )
    search_type: SearchType = Field(
        default=SearchType.VECTOR,
        description=(
            "Retrieval mode: 'vector' (dense semantic, default), "
            "'full_text' (PostgreSQL FTS), or 'hybrid' (RRF fusion)."
        ),
    )

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str) -> str:
        stripped = v.strip()
        if len(stripped) < 2:
            raise ValueError("Query string must contain at least 2 non-whitespace characters.")
        return stripped



class KnowledgeSearchResultItem(BaseModel):
    """Single knowledge search result representing a matched chunk.

    The ``score`` field semantics vary by search_type:
    - vector:    cosine similarity (higher = more semantically similar)
    - full_text: ts_rank float    (higher = stronger keyword match)
    - hybrid:    RRF score        (higher = stronger combined signal)

    ``vector_rank`` and ``fts_rank`` are populated only for hybrid results
    and indicate the rank position in each system's candidate list (1=best).
    They are None when a chunk was not retrieved by that system.
    """

    model_config = ConfigDict(from_attributes=True)

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    chunk_index: int
    content: str
    score: float = Field(
        ...,
        description="Retrieval score (cosine similarity / ts_rank / RRF score depending on search_type).",
    )
    vector_rank: int | None = Field(
        default=None,
        description="Rank in vector search candidate list (hybrid mode only; None if not retrieved by vector search).",
    )
    fts_rank: int | None = Field(
        default=None,
        description="Rank in FTS candidate list (hybrid mode only; None if not retrieved by FTS).",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeSearchResponse(BaseModel):
    """Response containing matched knowledge chunks ordered by retrieval score."""

    model_config = ConfigDict(from_attributes=True)

    query: str
    search_type: SearchType = SearchType.VECTOR
    total_results: int
    results: list[KnowledgeSearchResultItem] = Field(default_factory=list)
