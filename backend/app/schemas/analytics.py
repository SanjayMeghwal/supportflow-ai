"""Pydantic schemas for SupportFlow AI operational analytics."""

from typing import Dict, Optional
from pydantic import BaseModel, ConfigDict


class AnalyticsSummaryResponse(BaseModel):
    """Aggregate metrics for admin and agent operational dashboard."""

    model_config = ConfigDict(from_attributes=True)

    total_tickets: int
    open_tickets: int
    resolved_tickets: int
    in_progress_tickets: int
    pending_review_tickets: int
    closed_tickets: int

    total_reviews: int
    pending_reviews: int
    completed_reviews: int

    total_ai_runs: int
    average_confidence: Optional[float] = None

    tickets_by_status: Dict[str, int]
    tickets_by_category: Dict[str, int]
    tickets_by_priority: Dict[str, int]
    reviews_by_status: Dict[str, int]
