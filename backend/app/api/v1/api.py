"""Centralized API v1 router aggregator for SupportFlow AI.

Sub-routers are mounted here. Adding a new feature means:
  1. Create backend/app/api/v1/<feature>.py
  2. Add include_router() below
  3. No changes needed to main.py
"""

from fastapi import APIRouter

from backend.app.api.v1 import auth

api_router = APIRouter()

# Authentication & user identity
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])

# Future routers (uncomment when implemented):
# api_router.include_router(tickets.router, prefix="/tickets", tags=["Tickets"])
# api_router.include_router(reviews.router, prefix="/reviews", tags=["Human Review"])
# api_router.include_router(knowledge.router, prefix="/knowledge", tags=["Knowledge Base"])
# api_router.include_router(orders.router, prefix="/orders", tags=["Orders & Payments"])
# api_router.include_router(analytics.router, prefix="/analytics", tags=["Analytics"])
