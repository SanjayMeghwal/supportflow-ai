"""Operational analytics endpoints for admin and support agent dashboards."""

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.deps import require_support_agent
from backend.app.core.database import get_db
from backend.app.models.ai import AIRun, HumanReview, ReviewStatus
from backend.app.models.ticket import Ticket, TicketCategory, TicketPriority, TicketStatus
from backend.app.models.user import User
from backend.app.schemas.analytics import AnalyticsSummaryResponse

router = APIRouter()


@router.get(
    "/summary",
    response_model=AnalyticsSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get operational analytics summary",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Forbidden — requires SUPPORT_AGENT or ADMIN role"},
    },
)
async def get_analytics_summary(
    current_user: User = Depends(require_support_agent),
    db: AsyncSession = Depends(get_db),
) -> AnalyticsSummaryResponse:
    """Compute aggregate operations metrics across tickets, reviews, and AI runs."""
    # Status aggregation
    status_q = await db.execute(
        select(Ticket.status, func.count(Ticket.id)).group_by(Ticket.status)
    )
    tickets_by_status = {
        row[0].value if hasattr(row[0], "value") else str(row[0]): row[1]
        for row in status_q.all()
    }

    # Category aggregation
    category_q = await db.execute(
        select(Ticket.category, func.count(Ticket.id)).group_by(Ticket.category)
    )
    tickets_by_category = {
        row[0].value if hasattr(row[0], "value") else str(row[0]): row[1]
        for row in category_q.all()
    }

    # Priority aggregation
    priority_q = await db.execute(
        select(Ticket.priority, func.count(Ticket.id)).group_by(Ticket.priority)
    )
    tickets_by_priority = {
        row[0].value if hasattr(row[0], "value") else str(row[0]): row[1]
        for row in priority_q.all()
    }

    # Human reviews aggregation
    review_q = await db.execute(
        select(HumanReview.status, func.count(HumanReview.id)).group_by(HumanReview.status)
    )
    reviews_by_status = {
        row[0].value if hasattr(row[0], "value") else str(row[0]): row[1]
        for row in review_q.all()
    }

    # AI runs count and average confidence
    ai_run_q = await db.execute(
        select(
            func.count(AIRun.id),
            func.avg(AIRun.confidence_score),
        )
    )
    ai_row = ai_run_q.one()
    total_ai_runs = ai_row[0] or 0
    avg_confidence = float(ai_row[1]) if ai_row[1] is not None else None

    # Derive headline counts
    total_tickets = sum(tickets_by_status.values())
    open_tickets = tickets_by_status.get(TicketStatus.OPEN.value, 0)
    resolved_tickets = tickets_by_status.get(TicketStatus.RESOLVED.value, 0)
    in_progress_tickets = tickets_by_status.get(TicketStatus.IN_PROGRESS.value, 0)
    pending_review_tickets = tickets_by_status.get(TicketStatus.PENDING_AGENT_REVIEW.value, 0)
    closed_tickets = tickets_by_status.get(TicketStatus.CLOSED.value, 0)

    total_reviews = sum(reviews_by_status.values())
    pending_reviews = reviews_by_status.get(ReviewStatus.PENDING.value, 0)
    completed_reviews = total_reviews - pending_reviews

    return AnalyticsSummaryResponse(
        total_tickets=total_tickets,
        open_tickets=open_tickets,
        resolved_tickets=resolved_tickets,
        in_progress_tickets=in_progress_tickets,
        pending_review_tickets=pending_review_tickets,
        closed_tickets=closed_tickets,
        total_reviews=total_reviews,
        pending_reviews=pending_reviews,
        completed_reviews=completed_reviews,
        total_ai_runs=total_ai_runs,
        average_confidence=avg_confidence,
        tickets_by_status=tickets_by_status,
        tickets_by_category=tickets_by_category,
        tickets_by_priority=tickets_by_priority,
        reviews_by_status=reviews_by_status,
    )
