"""Phase 12: Human-In-The-Loop (HITL) Review and Escalation Service.

Core Principles:
- "AI may recommend. Human may approve. Application enforces."
- Concurrency protection: `with_for_update()` row locking prevents double-actions
  (e.g., competing agents attempting simultaneous approve/reject on the same review).
- The LLM can never approve, edit, or reject on its own.
- Deterministic escalation triggers: customer keyword requests, low confidence,
  missing knowledge base context, or failed/denied tools.
- Complete audit trail persisted via AuditLog for every review creation and action.
"""

from datetime import datetime, timezone
from typing import Any, Optional
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.models.ai import (
    AIRun,
    AIRunStatus,
    AuditLog,
    HumanReview,
    ReviewAction,
    ReviewStatus,
)
from backend.app.models.ticket import (
    SenderType,
    Ticket,
    TicketMessage,
    TicketStatus,
)
from backend.app.models.user import User, UserRole
from backend.app.schemas.ticket import is_valid_status_transition
from backend.app.schemas.tools import ToolResult


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ReviewNotFoundError(Exception):
    """Raised when a requested HumanReview does not exist."""


class ReviewAlreadyCompletedError(Exception):
    """Raised when an action is attempted on an already-resolved review."""


class InvalidReviewActionError(Exception):
    """Raised when an invalid action or transition is requested."""


# ---------------------------------------------------------------------------
# Deterministic Escalation Trigger Evaluation
# ---------------------------------------------------------------------------

# Explicit keywords/phrases indicating the customer wants human escalation or has high-risk concerns
ESCALATION_PHRASES: tuple[str, ...] = (
    "talk to an agent",
    "talk to agent",
    "speak to an agent",
    "speak to agent",
    "talk to a human",
    "speak to a human",
    "human agent",
    "human please",
    "connect me to a person",
    "connect to a person",
    "real person",
    "customer service representative",
    "speak to representative",
    "talk to representative",
    "manager",
    "speak to manager",
    "talk to manager",
    "lawyer",
    "legal action",
    "chargeback",
    "dispute charge",
    "dispute payment",
)

CONFIDENCE_THRESHOLD: float = 0.70


def check_escalation_triggers(
    query: str,
    *,
    context_available: bool,
    confidence_score: Optional[float] = None,
    tool_result: Optional[ToolResult] = None,
) -> tuple[bool, Optional[str], AIRunStatus]:
    """Deterministically evaluate whether an AI workflow run requires human review.

    Rules:
      1. Explicit human request or legal/chargeback keywords -> ESCALATED_GUARDRAIL
      2. Tool execution failed or access was denied -> ESCALATED_GUARDRAIL
      3. Missing knowledge base context -> ESCALATED_LOW_CONFIDENCE
      4. Grounding confidence score below threshold (0.70) -> ESCALATED_LOW_CONFIDENCE

    Returns
    -------
    tuple[bool, Optional[str], AIRunStatus]
        (should_escalate, escalation_reason, airun_status)
    """
    normalized_query = (query or "").lower().strip()

    # 1. Explicit human request or guardrail phrase
    for phrase in ESCALATION_PHRASES:
        if phrase in normalized_query:
            return (
                True,
                f"Customer explicitly requested human intervention or escalated concern: '{phrase}'",
                AIRunStatus.ESCALATED_GUARDRAIL,
            )

    # 2. Tool execution failure or denial
    if tool_result is not None and not tool_result.success:
        return (
            True,
            f"Tool '{tool_result.tool_name}' execution failed or denied: {tool_result.error}",
            AIRunStatus.ESCALATED_GUARDRAIL,
        )

    # 3. Missing knowledge base context
    if not context_available:
        return (
            True,
            "Insufficient knowledge base context to generate a reliable grounded answer",
            AIRunStatus.ESCALATED_LOW_CONFIDENCE,
        )

    # 4. Low confidence score
    if confidence_score is not None and confidence_score < CONFIDENCE_THRESHOLD:
        return (
            True,
            f"Grounding confidence score ({confidence_score:.2f}) is below acceptable threshold ({CONFIDENCE_THRESHOLD})",
            AIRunStatus.ESCALATED_LOW_CONFIDENCE,
        )

    return False, None, AIRunStatus.SUCCESS


# ---------------------------------------------------------------------------
# Review Lifecycle Operations
# ---------------------------------------------------------------------------


async def create_human_review(
    db: AsyncSession,
    *,
    ticket_id: uuid.UUID,
    ai_run_id: uuid.UUID,
    original_ai_draft: str,
    escalation_reason: str,
) -> HumanReview:
    """Create a pending HumanReview entity, update ticket state, and persist audit trace.

    Steps:
      1. Create HumanReview with status=PENDING.
      2. Transition Ticket status to PENDING_AGENT_REVIEW.
      3. Add an internal staff note indicating why AI execution paused.
      4. Persist AuditLog entry for the escalation.
    """
    ticket = await db.get(Ticket, ticket_id)
    if ticket is None:
        raise ValueError(f"Ticket {ticket_id} does not exist.")

    # 1. Create HumanReview
    review = HumanReview(
        ticket_id=ticket_id,
        ai_run_id=ai_run_id,
        status=ReviewStatus.PENDING,
        escalation_reason=escalation_reason,
        original_ai_draft=original_ai_draft,
        reviewer_id=None,
        action_taken=None,
        final_submitted_text=None,
        feedback_notes=None,
    )
    db.add(review)

    # 2. Update Ticket status if allowed
    if is_valid_status_transition(ticket.status, TicketStatus.PENDING_AGENT_REVIEW):
        ticket.status = TicketStatus.PENDING_AGENT_REVIEW
    elif ticket.status != TicketStatus.PENDING_AGENT_REVIEW:
        # Fallback for unexpected ticket states: set to PENDING_AGENT_REVIEW for safety
        ticket.status = TicketStatus.PENDING_AGENT_REVIEW

    # 3. Add internal note on the ticket thread
    note = TicketMessage(
        ticket_id=ticket.id,
        sender_id=None,
        sender_type=SenderType.AI_SYSTEM,
        content=f"[AI Escalation] Ticket paused for human review: {escalation_reason}",
        is_internal_note=True,
    )
    db.add(note)

    # 4. Audit Log
    audit = AuditLog(
        actor_id=None,
        actor_role="AI_SYSTEM",
        action="REVIEW_REQUESTED",
        entity_type="ticket",
        entity_id=ticket.id,
        change_details_json={
            "review_id": str(review.id),
            "ai_run_id": str(ai_run_id),
            "escalation_reason": escalation_reason,
        },
    )
    db.add(audit)

    await db.commit()
    await db.refresh(review)
    return review


async def list_pending_reviews(
    db: AsyncSession,
    *,
    skip: int = 0,
    limit: int = 50,
) -> tuple[int, list[HumanReview]]:
    """List pending reviews in FIFO order with eagerly loaded ticket context.

    Returns
    -------
    tuple[int, list[HumanReview]]
        (total_count, review_items)
    """
    count_stmt = select(func.count(HumanReview.id)).where(
        HumanReview.status == ReviewStatus.PENDING
    )
    total_result = await db.execute(count_stmt)
    total = total_result.scalar_one()

    stmt = (
        select(HumanReview)
        .options(selectinload(HumanReview.ticket))
        .where(HumanReview.status == ReviewStatus.PENDING)
        .order_by(HumanReview.created_at.asc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    items = list(result.scalars().all())
    return total, items


async def get_review_detail(
    db: AsyncSession,
    *,
    review_id: uuid.UUID,
) -> Optional[HumanReview]:
    """Fetch complete review detail including ticket, AI run, and tool invocations."""
    stmt = (
        select(HumanReview)
        .options(
            selectinload(HumanReview.ticket),
            selectinload(HumanReview.ai_run).selectinload(AIRun.tool_invocations),
        )
        .where(HumanReview.id == review_id)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def submit_review_action(
    db: AsyncSession,
    *,
    review_id: uuid.UUID,
    reviewer: User,
    action: ReviewAction,
    final_text: Optional[str] = None,
    notes: Optional[str] = None,
    resolve_ticket: bool = False,
    assign_to_agent_id: Optional[uuid.UUID] = None,
) -> HumanReview:
    """Execute a human review decision with atomic row-level locking.

    Concurrency Protection:
      Acquires a SELECT ... FOR UPDATE lock on the HumanReview row.
      If another reviewer acts concurrently, the second transaction sees
      status != PENDING and raises ReviewAlreadyCompletedError.

    Parameters
    ----------
    db : AsyncSession
        Active database session.
    review_id : uuid.UUID
        Identifier of the review to act upon.
    reviewer : User
        The authenticated SUPPORT_AGENT or ADMIN performing the action.
    action : ReviewAction
        APPROVED, EDITED, REJECTED, or ESCALATED.
    final_text : Optional[str]
        Required for EDITED action.
    notes : Optional[str]
        Mandatory for REJECTED and ESCALATED; optional for APPROVED and EDITED.
    resolve_ticket : bool
        If True, marks ticket as RESOLVED instead of PENDING_CUSTOMER on approval/edit.
    assign_to_agent_id : Optional[uuid.UUID]
        Optional agent ID to assign the ticket to on escalation.
    """
    # 1. Lock review row
    stmt = (
        select(HumanReview)
        .where(HumanReview.id == review_id)
        .with_for_update()
    )
    result = await db.execute(stmt)
    review = result.scalar_one_or_none()

    if review is None:
        raise ReviewNotFoundError(f"Human review '{review_id}' was not found.")

    # 2. Concurrency check — verify review is still pending
    if review.status != ReviewStatus.PENDING:
        raise ReviewAlreadyCompletedError(
            f"Review '{review_id}' has already been completed with action '{review.action_taken}' "
            f"by reviewer '{review.reviewer_id}'."
        )

    # 3. Lock ticket row
    ticket = await db.get(Ticket, review.ticket_id, with_for_update=True)
    if ticket is None:
        raise ReviewNotFoundError(f"Associated ticket '{review.ticket_id}' was not found.")

    now = datetime.now(timezone.utc)

    # 4. Apply action
    if action == ReviewAction.APPROVED:
        review.status = ReviewStatus.APPROVED
        review.action_taken = ReviewAction.APPROVED
        review.reviewer_id = reviewer.id
        review.final_submitted_text = review.original_ai_draft
        review.feedback_notes = notes
        review.resolved_at = now

        # Deliver message to customer from the human reviewer
        msg = TicketMessage(
            ticket_id=ticket.id,
            sender_id=reviewer.id,
            sender_type=SenderType.AGENT,
            content=review.final_submitted_text,
            is_internal_note=False,
        )
        db.add(msg)

        # Transition ticket status
        target_status = TicketStatus.RESOLVED if resolve_ticket else TicketStatus.PENDING_CUSTOMER
        if is_valid_status_transition(ticket.status, target_status):
            ticket.status = target_status
        if resolve_ticket:
            ticket.resolution_summary = "Resolved via approved AI-assisted response."

    elif action == ReviewAction.EDITED:
        if not final_text or not final_text.strip():
            raise InvalidReviewActionError("Edited action requires non-empty final_submitted_text.")

        review.status = ReviewStatus.EDITED
        review.action_taken = ReviewAction.EDITED
        review.reviewer_id = reviewer.id
        review.final_submitted_text = final_text.strip()
        review.feedback_notes = notes
        review.resolved_at = now

        # Deliver edited message to customer from the human reviewer
        msg = TicketMessage(
            ticket_id=ticket.id,
            sender_id=reviewer.id,
            sender_type=SenderType.AGENT,
            content=review.final_submitted_text,
            is_internal_note=False,
        )
        db.add(msg)

        # Transition ticket status
        target_status = TicketStatus.RESOLVED if resolve_ticket else TicketStatus.PENDING_CUSTOMER
        if is_valid_status_transition(ticket.status, target_status):
            ticket.status = target_status
        if resolve_ticket:
            ticket.resolution_summary = "Resolved via edited AI-assisted response."

    elif action == ReviewAction.REJECTED:
        if not notes or not notes.strip():
            raise InvalidReviewActionError("Rejected action requires mandatory feedback notes.")

        review.status = ReviewStatus.REJECTED
        review.action_taken = ReviewAction.REJECTED
        review.reviewer_id = reviewer.id
        review.final_submitted_text = None
        review.feedback_notes = notes.strip()
        review.resolved_at = now

        # Route to manual agent handling
        if is_valid_status_transition(ticket.status, TicketStatus.IN_PROGRESS):
            ticket.status = TicketStatus.IN_PROGRESS
        ticket.assigned_agent_id = reviewer.id  # Reviewer assumes ownership

        # Internal note explaining rejection
        note = TicketMessage(
            ticket_id=ticket.id,
            sender_id=reviewer.id,
            sender_type=SenderType.AGENT,
            content=f"[Review Rejected] Draft rejected by agent: {review.feedback_notes}",
            is_internal_note=True,
        )
        db.add(note)

    elif action == ReviewAction.ESCALATED:
        if not notes or not notes.strip():
            raise InvalidReviewActionError("Escalated action requires mandatory feedback notes.")

        review.status = ReviewStatus.ESCALATED
        review.action_taken = ReviewAction.ESCALATED
        review.reviewer_id = reviewer.id
        review.final_submitted_text = None
        review.feedback_notes = notes.strip()
        review.resolved_at = now

        # Route to higher tier agent or in progress
        if is_valid_status_transition(ticket.status, TicketStatus.IN_PROGRESS):
            ticket.status = TicketStatus.IN_PROGRESS
        if assign_to_agent_id:
            ticket.assigned_agent_id = assign_to_agent_id

        # Internal note documenting escalation
        note = TicketMessage(
            ticket_id=ticket.id,
            sender_id=reviewer.id,
            sender_type=SenderType.AGENT,
            content=f"[Higher-Tier Escalation] Escalated by agent: {review.feedback_notes}",
            is_internal_note=True,
        )
        db.add(note)

    else:
        raise InvalidReviewActionError(f"Unsupported review action: {action}")

    # 5. Persist AuditLog
    audit = AuditLog(
        actor_id=reviewer.id,
        actor_role=reviewer.role.value,
        action=f"HUMAN_REVIEW_{action.value}",
        entity_type="ticket",
        entity_id=ticket.id,
        change_details_json={
            "review_id": str(review.id),
            "action": action.value,
            "resulting_ticket_status": ticket.status.value,
            "resolved_at": review.resolved_at.isoformat(),
        },
    )
    db.add(audit)

    await db.commit()

    # Re-fetch with eagerly loaded ticket relationship to avoid
    # lazy-load MissingGreenlet errors in _review_to_item_response.
    refreshed = await db.execute(
        select(HumanReview)
        .options(selectinload(HumanReview.ticket))
        .where(HumanReview.id == review.id)
    )
    return refreshed.scalar_one()
