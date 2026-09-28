"""Pydantic schemas for Phase 12 Human-In-The-Loop review workflow.

Design principles:
- Actions are explicit command payloads (Approve, Edit, Reject, Escalate).
- Server-controlled fields (reviewer_id, timestamps, internal audit states)
  are NEVER accepted from the client.
- Strict Pydantic v2 validation with extra="forbid" on request commands.
- Sanitized responses excluding internal tokens or credentials.
"""

from datetime import datetime
from typing import Any, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field

from backend.app.models.ai import ReviewAction, ReviewStatus


# ---------------------------------------------------------------------------
# Command Requests (Inputs from Authenticated Reviewer)
# ---------------------------------------------------------------------------


class ReviewApproveRequest(BaseModel):
    """Command payload to approve the AI-generated draft as-is."""

    model_config = ConfigDict(extra="forbid")

    notes: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Optional internal reviewer notes regarding the approval",
    )
    resolve_ticket: bool = Field(
        default=False,
        description="If True, transitions ticket directly to RESOLVED instead of PENDING_CUSTOMER",
    )


class ReviewEditRequest(BaseModel):
    """Command payload to modify the AI draft before delivering to customer."""

    model_config = ConfigDict(extra="forbid")

    final_submitted_text: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="The human-edited response text to be sent to the customer",
    )
    notes: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Optional reviewer feedback explaining why the draft was modified",
    )
    resolve_ticket: bool = Field(
        default=False,
        description="If True, transitions ticket directly to RESOLVED instead of PENDING_CUSTOMER",
    )


class ReviewRejectRequest(BaseModel):
    """Command payload to reject the AI draft and route ticket to manual handling."""

    model_config = ConfigDict(extra="forbid")

    feedback_notes: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Mandatory explanation for why the AI draft was rejected",
    )


class ReviewEscalateRequest(BaseModel):
    """Command payload to escalate the ticket to a higher-tier or specialized agent."""

    model_config = ConfigDict(extra="forbid")

    feedback_notes: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Mandatory explanation for higher-tier escalation",
    )
    assign_to_agent_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Optional agent ID to assign the escalated ticket to",
    )


# ---------------------------------------------------------------------------
# Response Payloads
# ---------------------------------------------------------------------------


class ReviewItemResponse(BaseModel):
    """Summary of a HumanReview item in the pending queue or history."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticket_id: uuid.UUID
    ai_run_id: uuid.UUID
    status: ReviewStatus
    escalation_reason: str
    original_ai_draft: str
    final_submitted_text: Optional[str] = None
    feedback_notes: Optional[str] = None
    reviewer_id: Optional[uuid.UUID] = None
    action_taken: Optional[ReviewAction] = None
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime] = None

    # Contextual metadata populated for queue view
    ticket_number: Optional[str] = None
    ticket_title: Optional[str] = None
    ticket_priority: Optional[str] = None
    ticket_category: Optional[str] = None


class ReviewListResponse(BaseModel):
    """Paginated list of reviews in the review queue."""

    total: int
    items: list[ReviewItemResponse]


class ReviewDetailResponse(ReviewItemResponse):
    """Detailed view of a HumanReview item including ticket and AI run context."""

    confidence_score: Optional[float] = None
    intent_detected: Optional[str] = None
    model_name: Optional[str] = None
    tool_invocations: list[dict[str, Any]] = Field(default_factory=list)
