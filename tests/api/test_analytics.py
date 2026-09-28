"""API test suite for Phase 14 — Operational Analytics."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_analytics_summary_requires_authentication(client: AsyncClient):
    """GET /api/v1/analytics/summary must reject unauthenticated requests with 401."""
    response = await client.get("/api/v1/analytics/summary")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_analytics_summary_forbidden_for_customer(
    client: AsyncClient, test_customer_user: dict
):
    """Customers must be rejected with 403 Forbidden when accessing analytics."""
    response = await client.get(
        "/api/v1/analytics/summary",
        headers=test_customer_user["headers"],
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_analytics_summary_accessible_by_agent_and_admin(
    client: AsyncClient, test_admin_user: dict, test_agent_user: dict
):
    """Admin and Support Agent must both be permitted to fetch analytics summary."""
    # Test Admin access
    admin_resp = await client.get(
        "/api/v1/analytics/summary",
        headers=test_admin_user["headers"],
    )
    assert admin_resp.status_code == 200
    data = admin_resp.json()
    assert "total_tickets" in data
    assert "open_tickets" in data
    assert "resolved_tickets" in data
    assert "in_progress_tickets" in data
    assert "total_reviews" in data
    assert "pending_reviews" in data
    assert "total_ai_runs" in data
    assert "tickets_by_status" in data
    assert "tickets_by_category" in data
    assert "tickets_by_priority" in data
    assert "reviews_by_status" in data

    # Test Agent access
    agent_resp = await client.get(
        "/api/v1/analytics/summary",
        headers=test_agent_user["headers"],
    )
    assert agent_resp.status_code == 200
    agent_data = agent_resp.json()
    assert agent_data["total_tickets"] >= 0
