"""Centralized API v1 router aggregator for SupportFlow AI.

This module aggregates all sub-routers (auth, tickets, reviews, knowledge, orders, analytics)
under a single unified v1 router.
"""

from fastapi import APIRouter

api_router = APIRouter()

# Note: Sub-routers will be mounted here in subsequent phases:
# api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
# api_router.include_router(tickets.router, prefix="/tickets", tags=["Tickets"])
# api_router.include_router(reviews.router, prefix="/reviews", tags=["Human Review"])
# api_router.include_router(knowledge.router, prefix="/knowledge", tags=["Knowledge Base"])
# api_router.include_router(orders.router, prefix="/orders", tags=["Orders & Payments"])
# api_router.include_router(analytics.router, prefix="/analytics", tags=["Analytics"])
