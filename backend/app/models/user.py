import uuid
from enum import Enum
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import Boolean, Enum as SQLEnum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from backend.app.models.ai import HumanReview
    from backend.app.models.order import Order
    from backend.app.models.ticket import Ticket


class UserRole(str, Enum):
    ADMIN = "ADMIN"
    SUPPORT_AGENT = "SUPPORT_AGENT"
    CUSTOMER = "CUSTOMER"


class CustomerTier(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"
    VIP = "VIP"


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Core user model handling authentication, identity, and authorization."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )
    hashed_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    role: Mapped[UserRole] = mapped_column(
        SQLEnum(UserRole, name="user_role_enum"),
        default=UserRole.CUSTOMER,
        index=True,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    # Relationships
    customer_profile: Mapped[Optional["Customer"]] = relationship(
        "Customer",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    assigned_tickets: Mapped[List["Ticket"]] = relationship(
        "Ticket",
        back_populates="assigned_agent",
        foreign_keys="[Ticket.assigned_agent_id]",
    )
    reviews_performed: Mapped[List["HumanReview"]] = relationship(
        "HumanReview",
        back_populates="reviewer",
    )


class Customer(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Customer profile containing commercial tier and CRM relationships."""

    __tablename__ = "customers"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    full_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    phone_number: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )
    tier: Mapped[CustomerTier] = mapped_column(
        SQLEnum(CustomerTier, name="customer_tier_enum"),
        default=CustomerTier.STANDARD,
        nullable=False,
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        back_populates="customer_profile",
    )
    tickets: Mapped[List["Ticket"]] = relationship(
        "Ticket",
        back_populates="customer",
        cascade="all, delete-orphan",
    )
    orders: Mapped[List["Order"]] = relationship(
        "Order",
        back_populates="customer",
        cascade="all, delete-orphan",
    )
