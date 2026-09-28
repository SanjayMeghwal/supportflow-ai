"""Consolidated domain models export for SupportFlow AI."""

from backend.app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from backend.app.models.user import Customer, CustomerTier, User, UserRole
from backend.app.models.ticket import (
    SenderType,
    Ticket,
    TicketCategory,
    TicketMessage,
    TicketPriority,
    TicketStatus,
)
from backend.app.models.order import (
    Order,
    OrderStatus,
    Payment,
    PaymentMethod,
    PaymentStatus,
)
from backend.app.models.knowledge import (
    DocumentChunk,
    KnowledgeDocument,
    SourceType,
)
from backend.app.models.ai import (
    AIRun,
    AIRunStatus,
    AIToolInvocation,
    AuditLog,
    HumanReview,
    ReviewAction,
    ReviewStatus,
)

__all__ = [
    "Base",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "User",
    "UserRole",
    "Customer",
    "CustomerTier",
    "Ticket",
    "TicketCategory",
    "TicketPriority",
    "TicketStatus",
    "TicketMessage",
    "SenderType",
    "Order",
    "OrderStatus",
    "Payment",
    "PaymentMethod",
    "PaymentStatus",
    "KnowledgeDocument",
    "DocumentChunk",
    "SourceType",
    "AIRun",
    "AIRunStatus",
    "AIToolInvocation",
    "HumanReview",
    "ReviewAction",
    "ReviewStatus",
    "AuditLog",
]
