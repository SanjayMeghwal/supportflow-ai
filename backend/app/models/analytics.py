"""Database model for persistent LLM call analytics and token tracking."""

from typing import Any, Dict, Optional
from sqlalchemy import Boolean, DateTime, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class LLMAnalyticsRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Durable record of an LLM completion call, capturing tokens and latency without private data."""

    __tablename__ = "llm_analytics"

    request_id: Mapped[str] = mapped_column(
        String(64),
        index=True,
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(
        String(32),
        default="groq",
        nullable=False,
    )
    model: Mapped[str] = mapped_column(
        String(128),
        index=True,
        nullable=False,
    )
    operation: Mapped[str] = mapped_column(
        String(64),
        default="rag_synthesis",
        index=True,
        nullable=False,
    )
    prompt_tokens: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    completion_tokens: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    total_tokens: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    is_estimated: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    latency_ms: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    success: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        index=True,
        nullable=False,
    )
    error_type: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )
    metadata_json: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
