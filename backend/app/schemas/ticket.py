"""Pydantic schemas for ticket management.

Design principles:
- ticket_number is NEVER accepted from the client — generated server-side.
- customer_id is resolved from JWT → DB, never from client input (prevents IDOR).
- sender_type on messages is set server-side based on authenticated user role.
- Internal notes (is_internal_note) are filtered server-side for CUSTOMER users.
- Status transitions are validated via an explicit allowlist.
"""

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from backend.app.models.ticket import (
    SenderType,
    TicketCategory,
    TicketPriority,
    TicketStatus,
)


# ---------------------------------------------------------------------------
# Status Transition Rules
# ---------------------------------------------------------------------------

# Explicit allowlist of valid status transitions.
# Key = current status, Value = set of allowed next statuses.
# CLOSED is terminal — no outgoing transitions.
VALID_STATUS_TRANSITIONS: dict[TicketStatus, set[TicketStatus]] = {
    TicketStatus.OPEN: {
        TicketStatus.AI_PROCESSING,
        TicketStatus.IN_PROGRESS,
        TicketStatus.CLOSED,
    },
    TicketStatus.AI_PROCESSING: {
        TicketStatus.PENDING_CUSTOMER,
        TicketStatus.PENDING_AGENT_REVIEW,
        TicketStatus.RESOLVED,
        TicketStatus.OPEN,  # fallback if AI processing fails
    },
    TicketStatus.PENDING_CUSTOMER: {
        TicketStatus.OPEN,
        TicketStatus.IN_PROGRESS,
        TicketStatus.CLOSED,
    },
    TicketStatus.PENDING_AGENT_REVIEW: {
        TicketStatus.IN_PROGRESS,
        TicketStatus.RESOLVED,
        TicketStatus.CLOSED,
    },
    TicketStatus.IN_PROGRESS: {
        TicketStatus.PENDING_CUSTOMER,
        TicketStatus.RESOLVED,
        TicketStatus.CLOSED,
    },
    TicketStatus.RESOLVED: {
        TicketStatus.CLOSED,
        TicketStatus.OPEN,  # customer reopens
    },
    TicketStatus.CLOSED: set(),  # terminal — no transitions allowed
}


def is_valid_status_transition(
    current: TicketStatus, target: TicketStatus
) -> bool:
    """Check whether a status transition is allowed by the lifecycle rules."""
    return target in VALID_STATUS_TRANSITIONS.get(current, set())


# ---------------------------------------------------------------------------
# Ticket Creation
# ---------------------------------------------------------------------------


class TicketCreateRequest(BaseModel):
    """Payload for POST /tickets — customer creates a new support ticket.

    - title and description are required.
    - category defaults to GENERAL if omitted.
    - priority is intentionally omitted — always defaults to MEDIUM on creation.
      Only agents/admins can escalate priority.
    - customer_id and ticket_number are NEVER accepted here.
    """

    title: str = Field(min_length=3, max_length=255)
    description: str = Field(min_length=10, max_length=10000)
    category: TicketCategory = TicketCategory.GENERAL

    @field_validator("title", mode="before")
    @classmethod
    def strip_title(cls, v: str) -> str:
        return v.strip()

    @field_validator("description", mode="before")
    @classmethod
    def strip_description(cls, v: str) -> str:
        return v.strip()


# ---------------------------------------------------------------------------
# Ticket Update (Agent / Admin only)
# ---------------------------------------------------------------------------


class TicketUpdateRequest(BaseModel):
    """Payload for PATCH /tickets/{ticket_id} — agent/admin updates ticket.

    All fields are optional — only provided fields are applied.
    Status transition is validated against the allowlist at the API layer.
    """

    status: Optional[TicketStatus] = None
    priority: Optional[TicketPriority] = None
    category: Optional[TicketCategory] = None
    resolution_summary: Optional[str] = Field(default=None, max_length=5000)


# ---------------------------------------------------------------------------
# Ticket Assignment
# ---------------------------------------------------------------------------


class TicketAssignRequest(BaseModel):
    """Payload for POST /tickets/{ticket_id}/assign."""

    agent_id: uuid.UUID


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


class TicketMessageCreateRequest(BaseModel):
    """Payload for POST /tickets/{ticket_id}/messages.

    - sender_type is set server-side based on the authenticated user's role.
    - is_internal_note defaults to False; only agents/admins can set it True.
    """

    content: str = Field(min_length=1, max_length=10000)
    is_internal_note: bool = False

    @field_validator("content", mode="before")
    @classmethod
    def strip_content(cls, v: str) -> str:
        return v.strip()


# ---------------------------------------------------------------------------
# Response Schemas
# ---------------------------------------------------------------------------


class TicketMessageResponse(BaseModel):
    """Wire representation of a single ticket message."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    ticket_id: uuid.UUID
    sender_id: Optional[uuid.UUID] = None
    sender_type: str
    content: str
    is_internal_note: bool
    created_at: datetime


class TicketResponse(BaseModel):
    """Full ticket representation returned to the client.

    Includes nested messages when fetching a single ticket detail.
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    ticket_number: str
    customer_id: uuid.UUID
    assigned_agent_id: Optional[uuid.UUID] = None
    title: str
    description: str
    category: str
    priority: str
    status: str
    resolution_summary: Optional[str] = None
    closed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    messages: Optional[List[TicketMessageResponse]] = None


class TicketListResponse(BaseModel):
    """Paginated list of tickets."""

    tickets: List[TicketResponse]
    total: int
    offset: int
    limit: int
