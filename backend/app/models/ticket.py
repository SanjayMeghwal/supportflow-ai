import uuid
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from backend.app.models.ai import AIRun, HumanReview
    from backend.app.models.user import Customer, User


class TicketCategory(str, Enum):
    BILLING = "BILLING"
    ORDER_STATUS = "ORDER_STATUS"
    TECHNICAL = "TECHNICAL"
    RETURNS = "RETURNS"
    GENERAL = "GENERAL"


class TicketPriority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    URGENT = "URGENT"


class TicketStatus(str, Enum):
    OPEN = "OPEN"
    AI_PROCESSING = "AI_PROCESSING"
    PENDING_CUSTOMER = "PENDING_CUSTOMER"
    PENDING_AGENT_REVIEW = "PENDING_AGENT_REVIEW"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class SenderType(str, Enum):
    CUSTOMER = "CUSTOMER"
    AGENT = "AGENT"
    AI_SYSTEM = "AI_SYSTEM"


class Ticket(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Core support ticket entity managing conversation lifecycle and assignment."""

    __tablename__ = "tickets"

    ticket_number: Mapped[str] = mapped_column(
        String(32),
        unique=True,
        index=True,
        nullable=False,
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    assigned_agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    category: Mapped[TicketCategory] = mapped_column(
        SQLEnum(TicketCategory, name="ticket_category_enum"),
        default=TicketCategory.GENERAL,
        index=True,
        nullable=False,
    )
    priority: Mapped[TicketPriority] = mapped_column(
        SQLEnum(TicketPriority, name="ticket_priority_enum"),
        default=TicketPriority.MEDIUM,
        index=True,
        nullable=False,
    )
    status: Mapped[TicketStatus] = mapped_column(
        SQLEnum(TicketStatus, name="ticket_status_enum"),
        default=TicketStatus.OPEN,
        index=True,
        nullable=False,
    )
    resolution_summary: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    customer: Mapped["Customer"] = relationship(
        "Customer",
        back_populates="tickets",
    )
    assigned_agent: Mapped[Optional["User"]] = relationship(
        "User",
        back_populates="assigned_tickets",
        foreign_keys=[assigned_agent_id],
    )
    messages: Mapped[List["TicketMessage"]] = relationship(
        "TicketMessage",
        back_populates="ticket",
        cascade="all, delete-orphan",
        order_by="TicketMessage.created_at",
    )
    ai_runs: Mapped[List["AIRun"]] = relationship(
        "AIRun",
        back_populates="ticket",
        cascade="all, delete-orphan",
    )
    human_reviews: Mapped[List["HumanReview"]] = relationship(
        "HumanReview",
        back_populates="ticket",
        cascade="all, delete-orphan",
    )


class TicketMessage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Threaded conversation message or internal staff note for a ticket."""

    __tablename__ = "ticket_messages"

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    sender_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    sender_type: Mapped[SenderType] = mapped_column(
        SQLEnum(SenderType, name="sender_type_enum"),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    is_internal_note: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # Relationships
    ticket: Mapped["Ticket"] = relationship(
        "Ticket",
        back_populates="messages",
    )
    sender: Mapped[Optional["User"]] = relationship(
        "User",
    )
