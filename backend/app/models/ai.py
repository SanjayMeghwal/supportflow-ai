import uuid
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from sqlalchemy import (
    Boolean,
    Enum as SQLEnum,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from backend.app.models.ticket import Ticket
    from backend.app.models.user import User


class AIRunStatus(str, Enum):
    SUCCESS = "SUCCESS"
    ESCALATED_LOW_CONFIDENCE = "ESCALATED_LOW_CONFIDENCE"
    ESCALATED_GUARDRAIL = "ESCALATED_GUARDRAIL"
    FAILED = "FAILED"


class ReviewAction(str, Enum):
    APPROVED = "APPROVED"
    EDITED = "EDITED"
    REJECTED = "REJECTED"
    ESCALATED = "ESCALATED"


class AIRun(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Execution trace of an AI agent triage run for a ticket."""

    __tablename__ = "ai_runs"

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    model_name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    intent_detected: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )
    confidence_score: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(4, 3),
        nullable=True,
    )
    execution_status: Mapped[AIRunStatus] = mapped_column(
        SQLEnum(AIRunStatus, name="ai_run_status_enum"),
        default=AIRunStatus.SUCCESS,
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
    latency_ms: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    response_text: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )

    # Relationships
    ticket: Mapped["Ticket"] = relationship(
        "Ticket",
        back_populates="ai_runs",
    )
    tool_invocations: Mapped[List["AIToolInvocation"]] = relationship(
        "AIToolInvocation",
        back_populates="ai_run",
        cascade="all, delete-orphan",
    )
    human_reviews: Mapped[List["HumanReview"]] = relationship(
        "HumanReview",
        back_populates="ai_run",
    )


class AIToolInvocation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Audit record of a specific tool invoked by the AI agent during a run."""

    __tablename__ = "ai_tool_invocations"

    ai_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_runs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    tool_name: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    input_parameters_json: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    output_result_json: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    duration_ms: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    is_success: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    # Relationships
    ai_run: Mapped["AIRun"] = relationship(
        "AIRun",
        back_populates="tool_invocations",
    )


class HumanReview(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Human-In-The-Loop review record for an AI-generated draft response."""

    __tablename__ = "human_reviews"

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    ai_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_runs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    reviewer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    action_taken: Mapped[ReviewAction] = mapped_column(
        SQLEnum(ReviewAction, name="review_action_enum"),
        nullable=False,
    )
    original_ai_draft: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    final_submitted_text: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    feedback_notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )

    # Relationships
    ticket: Mapped["Ticket"] = relationship(
        "Ticket",
        back_populates="human_reviews",
    )
    ai_run: Mapped["AIRun"] = relationship(
        "AIRun",
        back_populates="human_reviews",
    )
    reviewer: Mapped["User"] = relationship(
        "User",
        back_populates="reviews_performed",
    )


class AuditLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Immutable system audit trail tracking sensitive operations and state changes."""

    __tablename__ = "audit_logs"

    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    actor_role: Mapped[Optional[str]] = mapped_column(
        String(32),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(
        String(128),
        index=True,
        nullable=False,
    )
    entity_type: Mapped[str] = mapped_column(
        String(64),
        index=True,
        nullable=False,
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        index=True,
        nullable=False,
    )
    change_details_json: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    ip_address: Mapped[Optional[str]] = mapped_column(
        String(45),
        nullable=True,
    )
