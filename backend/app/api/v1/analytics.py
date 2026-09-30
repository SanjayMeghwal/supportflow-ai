"""Operational and observability analytics endpoints for admin and support agent dashboards."""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.deps import require_support_agent
from backend.app.core.database import get_db
from backend.app.core.metrics import metrics_collector
from backend.app.core.tracing import trace_buffer
from backend.app.models.ai import AIRun, HumanReview, ReviewStatus
from backend.app.models.ticket import Ticket, TicketCategory, TicketPriority, TicketStatus
from backend.app.models.user import User
from backend.app.schemas.analytics import AnalyticsSummaryResponse
from backend.app.schemas.observability import (
    LLMAnalyticsSummaryResponse,
    ObservabilityOverviewResponse,
    PipelineTraceResponse,
    RequestMetricsResponse,
)
from backend.app.services.llm_analytics import llm_analytics_service

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


# ---------------------------------------------------------------------------
# Phase 17: Observability, Latency & Token Analytics Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/observability/overview",
    response_model=ObservabilityOverviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Unified system observability and AI metrics overview",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Forbidden — requires SUPPORT_AGENT or ADMIN role"},
    },
)
async def get_observability_overview(
    current_user: User = Depends(require_support_agent),
) -> ObservabilityOverviewResponse:
    """Retrieve combined HTTP throughput, error rates, and in-memory LLM analytics."""
    req_snapshot = metrics_collector.get_snapshot()
    llm_snapshot = llm_analytics_service.get_in_memory_summary()
    recent_traces = trace_buffer.get_traces(limit=10)

    return ObservabilityOverviewResponse(
        system_status="healthy",
        requests=RequestMetricsResponse(
            total_requests=req_snapshot["total_requests"],
            error_count=req_snapshot["error_count"],
            error_rate=req_snapshot["error_rate"],
            avg_latency_ms=req_snapshot["avg_latency_ms"],
            p50_latency_ms=req_snapshot["p50_latency_ms"],
            p95_latency_ms=req_snapshot["p95_latency_ms"],
            p99_latency_ms=req_snapshot["p99_latency_ms"],
            status_codes={str(k): v for k, v in req_snapshot["status_codes"].items()},
            endpoint_count=req_snapshot["endpoint_count"],
            endpoints=req_snapshot["endpoints"],
        ),
        llm=llm_snapshot,
        recent_traces_count=len(recent_traces),
    )


@router.get(
    "/observability/requests",
    response_model=RequestMetricsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get HTTP request latency percentiles and throughput",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Forbidden — requires SUPPORT_AGENT or ADMIN role"},
    },
)
async def get_request_metrics(
    current_user: User = Depends(require_support_agent),
) -> RequestMetricsResponse:
    """Get HTTP latency distributions (p50, p95, p99) and status code distributions."""
    req_snapshot = metrics_collector.get_snapshot()
    return RequestMetricsResponse(
        total_requests=req_snapshot["total_requests"],
        error_count=req_snapshot["error_count"],
        error_rate=req_snapshot["error_rate"],
        avg_latency_ms=req_snapshot["avg_latency_ms"],
        p50_latency_ms=req_snapshot["p50_latency_ms"],
        p95_latency_ms=req_snapshot["p95_latency_ms"],
        p99_latency_ms=req_snapshot["p99_latency_ms"],
        status_codes={str(k): v for k, v in req_snapshot["status_codes"].items()},
        endpoint_count=req_snapshot["endpoint_count"],
        endpoints=req_snapshot["endpoints"],
    )


@router.get(
    "/observability/llm",
    response_model=LLMAnalyticsSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get LLM token consumption and model latency analytics",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Forbidden — requires SUPPORT_AGENT or ADMIN role"},
    },
)
async def get_llm_analytics(
    period: Optional[str] = Query(
        default="24h",
        description="Aggregation time window: 1h, 24h, 7d, or 30d",
        pattern="^(1h|24h|7d|30d)$",
    ),
    current_user: User = Depends(require_support_agent),
    db: AsyncSession = Depends(get_db),
) -> LLMAnalyticsSummaryResponse:
    """Query persistent LLM analytics with token breakdown by model and operation."""
    summary = await llm_analytics_service.get_db_summary(db=db, period=period)
    return LLMAnalyticsSummaryResponse(**summary)


@router.get(
    "/observability/traces",
    response_model=List[PipelineTraceResponse],
    status_code=status.HTTP_200_OK,
    summary="Get recent AI/RAG execution pipeline traces",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Forbidden — requires SUPPORT_AGENT or ADMIN role"},
    },
)
async def get_pipeline_traces(
    limit: int = Query(default=20, ge=1, le=100, description="Max traces to return"),
    current_user: User = Depends(require_support_agent),
) -> List[PipelineTraceResponse]:
    """Retrieve recent multi-span AI pipeline traces (retrieval, rerank, generation, tools)."""
    raw_traces = trace_buffer.get_traces(limit=limit)
    return [PipelineTraceResponse(**t) for t in raw_traces]
