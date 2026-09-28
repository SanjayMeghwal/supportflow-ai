"""Human-In-The-Loop review router: queue management and human action endpoints.

Endpoints:
  GET   /api/v1/reviews/pending       — list pending human reviews in FIFO order
  GET   /api/v1/reviews/{review_id}   — get detailed review information
  POST  /api/v1/reviews/{review_id}/approve  — approve draft response as-is
  POST  /api/v1/reviews/{review_id}/edit     — modify draft and send edited response
  POST  /api/v1/reviews/{review_id}/reject   — reject draft and route to manual handling
  POST  /api/v1/reviews/{review_id}/escalate — escalate ticket to higher-tier agent

Security Invariants:
  1. Only authenticated users with SUPPORT_AGENT or ADMIN roles may access reviews.
  2. CUSTOMER role is rejected with 403 Forbidden.
  3. reviewer_id is derived server-side from the authenticated user token — never from client input.
  4. Concurrency protection prevents duplicate or competing reviews on the same entity.
  5. The LLM cannot call these endpoints or approve its own draft.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.deps import get_current_user, require_support_agent
from backend.app.core.database import get_db
from backend.app.models.ai import HumanReview, ReviewAction
from backend.app.models.user import User
from backend.app.schemas.review import (
    ReviewApproveRequest,
    ReviewDetailResponse,
    ReviewEditRequest,
    ReviewEscalateRequest,
    ReviewItemResponse,
    ReviewListResponse,
    ReviewRejectRequest,
)
from backend.app.services.review_service import (
    InvalidReviewActionError,
    ReviewAlreadyCompletedError,
    ReviewNotFoundError,
    get_review_detail,
    list_pending_reviews,
    submit_review_action,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helper: Review serialization
# ---------------------------------------------------------------------------


def _review_to_item_response(review: HumanReview) -> ReviewItemResponse:
    ticket = review.ticket
    return ReviewItemResponse(
        id=review.id,
        ticket_id=review.ticket_id,
        ai_run_id=review.ai_run_id,
        status=review.status,
        escalation_reason=review.escalation_reason,
        original_ai_draft=review.original_ai_draft,
        final_submitted_text=review.final_submitted_text,
        feedback_notes=review.feedback_notes,
        reviewer_id=review.reviewer_id,
        action_taken=review.action_taken,
        created_at=review.created_at,
        updated_at=review.updated_at,
        resolved_at=review.resolved_at,
        ticket_number=ticket.ticket_number if ticket else None,
        ticket_title=ticket.title if ticket else None,
        ticket_priority=ticket.priority.value if ticket else None,
        ticket_category=ticket.category.value if ticket else None,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/reviews/pending — List Pending Reviews (Review Queue)
# ---------------------------------------------------------------------------


@router.get(
    "/pending",
    response_model=ReviewListResponse,
    summary="List pending reviews in the human review queue",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Forbidden — requires SUPPORT_AGENT or ADMIN role"},
    },
)
async def get_pending_review_queue(
    skip: int = Query(0, ge=0, description="Offset for pagination"),
    limit: int = Query(50, ge=1, le=100, description="Page limit"),
    current_user: User = Depends(require_support_agent),
    db: AsyncSession = Depends(get_db),
) -> ReviewListResponse:
    """Retrieve pending HumanReview items ordered FIFO for triage."""
    total, reviews = await list_pending_reviews(db, skip=skip, limit=limit)
    items = [_review_to_item_response(r) for r in reviews]
    return ReviewListResponse(total=total, items=items)


# ---------------------------------------------------------------------------
# GET /api/v1/reviews/{review_id} — Get Review Detail
# ---------------------------------------------------------------------------


@router.get(
    "/{review_id}",
    response_model=ReviewDetailResponse,
    summary="Get complete details of a specific human review item",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Forbidden — requires SUPPORT_AGENT or ADMIN role"},
        404: {"description": "Review not found"},
    },
)
async def get_review(
    review_id: uuid.UUID,
    current_user: User = Depends(require_support_agent),
    db: AsyncSession = Depends(get_db),
) -> ReviewDetailResponse:
    """Fetch full review record including associated ticket and AI run metadata."""
    review = await get_review_detail(db, review_id=review_id)
    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Human review '{review_id}' was not found.",
        )

    item = _review_to_item_response(review)
    ai_run = review.ai_run
    tool_invocations = []
    if ai_run and ai_run.tool_invocations:
        tool_invocations = [
            {
                "id": str(t.id),
                "tool_name": t.tool_name,
                "input_parameters": t.input_parameters_json,
                "output_result": t.output_result_json,
                "is_success": t.is_success,
                "duration_ms": t.duration_ms,
            }
            for t in ai_run.tool_invocations
        ]

    return ReviewDetailResponse(
        **item.model_dump(),
        confidence_score=float(ai_run.confidence_score) if ai_run and ai_run.confidence_score is not None else None,
        intent_detected=ai_run.intent_detected if ai_run else None,
        model_name=ai_run.model_name if ai_run else None,
        tool_invocations=tool_invocations,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/reviews/{review_id}/approve — Approve AI Draft
# ---------------------------------------------------------------------------


@router.post(
    "/{review_id}/approve",
    response_model=ReviewItemResponse,
    summary="Approve the AI-generated draft response as-is",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Forbidden — requires SUPPORT_AGENT or ADMIN role"},
        404: {"description": "Review not found"},
        409: {"description": "Conflict — review has already been completed"},
    },
)
async def approve_review(
    review_id: uuid.UUID,
    payload: ReviewApproveRequest,
    current_user: User = Depends(require_support_agent),
    db: AsyncSession = Depends(get_db),
) -> ReviewItemResponse:
    """Approve the AI draft and dispatch it to the customer from the human reviewer."""
    try:
        review = await submit_review_action(
            db,
            review_id=review_id,
            reviewer=current_user,
            action=ReviewAction.APPROVED,
            notes=payload.notes,
            resolve_ticket=payload.resolve_ticket,
        )
    except ReviewNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ReviewAlreadyCompletedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InvalidReviewActionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return _review_to_item_response(review)


# ---------------------------------------------------------------------------
# POST /api/v1/reviews/{review_id}/edit — Modify Draft and Send
# ---------------------------------------------------------------------------


@router.post(
    "/{review_id}/edit",
    response_model=ReviewItemResponse,
    summary="Modify the AI-generated draft response before sending to customer",
    responses={
        400: {"description": "Invalid edit content"},
        401: {"description": "Not authenticated"},
        403: {"description": "Forbidden — requires SUPPORT_AGENT or ADMIN role"},
        404: {"description": "Review not found"},
        409: {"description": "Conflict — review has already been completed"},
    },
)
async def edit_review(
    review_id: uuid.UUID,
    payload: ReviewEditRequest,
    current_user: User = Depends(require_support_agent),
    db: AsyncSession = Depends(get_db),
) -> ReviewItemResponse:
    """Modify the draft response and deliver the human-edited text to the customer."""
    try:
        review = await submit_review_action(
            db,
            review_id=review_id,
            reviewer=current_user,
            action=ReviewAction.EDITED,
            final_text=payload.final_submitted_text,
            notes=payload.notes,
            resolve_ticket=payload.resolve_ticket,
        )
    except ReviewNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ReviewAlreadyCompletedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InvalidReviewActionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return _review_to_item_response(review)


# ---------------------------------------------------------------------------
# POST /api/v1/reviews/{review_id}/reject — Reject Draft
# ---------------------------------------------------------------------------


@router.post(
    "/{review_id}/reject",
    response_model=ReviewItemResponse,
    summary="Reject the AI draft and assign ticket to agent for manual handling",
    responses={
        400: {"description": "Missing feedback notes"},
        401: {"description": "Not authenticated"},
        403: {"description": "Forbidden — requires SUPPORT_AGENT or ADMIN role"},
        404: {"description": "Review not found"},
        409: {"description": "Conflict — review has already been completed"},
    },
)
async def reject_review(
    review_id: uuid.UUID,
    payload: ReviewRejectRequest,
    current_user: User = Depends(require_support_agent),
    db: AsyncSession = Depends(get_db),
) -> ReviewItemResponse:
    """Reject the draft response and transition the ticket to IN_PROGRESS for manual handling."""
    try:
        review = await submit_review_action(
            db,
            review_id=review_id,
            reviewer=current_user,
            action=ReviewAction.REJECTED,
            notes=payload.feedback_notes,
        )
    except ReviewNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ReviewAlreadyCompletedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InvalidReviewActionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return _review_to_item_response(review)


# ---------------------------------------------------------------------------
# POST /api/v1/reviews/{review_id}/escalate — Higher-Tier Escalation
# ---------------------------------------------------------------------------


@router.post(
    "/{review_id}/escalate",
    response_model=ReviewItemResponse,
    summary="Escalate the ticket to a higher-tier or specialized agent",
    responses={
        400: {"description": "Missing escalation feedback"},
        401: {"description": "Not authenticated"},
        403: {"description": "Forbidden — requires SUPPORT_AGENT or ADMIN role"},
        404: {"description": "Review not found"},
        409: {"description": "Conflict — review has already been completed"},
    },
)
async def escalate_review(
    review_id: uuid.UUID,
    payload: ReviewEscalateRequest,
    current_user: User = Depends(require_support_agent),
    db: AsyncSession = Depends(get_db),
) -> ReviewItemResponse:
    """Document escalation and assign ticket to higher tier agent."""
    try:
        review = await submit_review_action(
            db,
            review_id=review_id,
            reviewer=current_user,
            action=ReviewAction.ESCALATED,
            notes=payload.feedback_notes,
            assign_to_agent_id=payload.assign_to_agent_id,
        )
    except ReviewNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ReviewAlreadyCompletedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InvalidReviewActionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return _review_to_item_response(review)
