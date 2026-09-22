import uuid
from enum import Enum
from typing import Any, Dict, List, Optional
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Enum as SQLEnum,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.app.core.config import settings
from backend.app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SourceType(str, Enum):
    PDF = "PDF"
    MARKDOWN = "MARKDOWN"
    TEXT = "TEXT"
    FAQ = "FAQ"


class KnowledgeDocument(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Authoritative knowledge base document source record."""

    __tablename__ = "knowledge_documents"

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    source_type: Mapped[SourceType] = mapped_column(
        SQLEnum(SourceType, name="source_type_enum"),
        nullable=False,
    )
    source_uri: Mapped[Optional[str]] = mapped_column(
        String(512),
        nullable=True,
    )
    checksum_sha256: Mapped[str] = mapped_column(
        String(64),
        index=True,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    # Relationships
    chunks: Mapped[List["DocumentChunk"]] = relationship(
        "DocumentChunk",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentChunk.chunk_index",
    )


class DocumentChunk(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Text chunk and dense vector embedding for hybrid RAG search."""

    __tablename__ = "document_chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    chunk_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    metadata_json: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    # Dense vector representation with pgvector
    embedding = mapped_column(
        Vector(settings.EMBEDDING_DIMENSION),
        nullable=True,
    )

    # Relationships
    document: Mapped["KnowledgeDocument"] = relationship(
        "KnowledgeDocument",
        back_populates="chunks",
    )
