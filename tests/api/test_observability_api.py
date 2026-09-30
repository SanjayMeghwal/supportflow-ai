"""API test suite for Phase 17 — Observability, Latency Tracing & Token Analytics."""

import uuid
import pytest
from httpx import AsyncClient

from backend.app.core.metrics import request_metrics
from backend.app.services.llm_analytics import llm_analytics_service


@pytest.mark.asyncio
async def test_request_id_middleware_generates_id(client: AsyncClient):
    """When X-Request-ID is not provided, the server generates and returns one."""
    response = await client.get("/health")
    assert response.status_code == 200
    request_id = response.headers.get("X-Request-ID")
    assert request_id is not None
    assert len(request_id) > 8
    assert "X-Response-Time-Ms" in response.headers


@pytest.mark.asyncio
async def test_request_id_middleware_propagates_existing_id(client: AsyncClient):
    """When X-Request-ID is provided in request headers, the server preserves and returns it."""
    custom_id = f"custom-trace-{uuid.uuid4()}"
    response = await client.get("/health", headers={"X-Request-ID": custom_id})
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID") == custom_id


@pytest.mark.asyncio
async def test_observability_endpoints_require_auth(client: AsyncClient):
    """All observability endpoints must require authentication."""
    endpoints = [
        "/api/v1/analytics/observability/overview",
        "/api/v1/analytics/observability/requests",
        "/api/v1/analytics/observability/llm",
        "/api/v1/analytics/observability/traces",
    ]
    for endpoint in endpoints:
        resp = await client.get(endpoint)
        assert resp.status_code == 401, f"{endpoint} should require authentication (401)"


@pytest.mark.asyncio
async def test_observability_endpoints_forbidden_for_customers(
    client: AsyncClient, test_customer_user: dict
):
    """Customers must not have access to internal observability metrics."""
    endpoints = [
        "/api/v1/analytics/observability/overview",
        "/api/v1/analytics/observability/requests",
        "/api/v1/analytics/observability/llm",
        "/api/v1/analytics/observability/traces",
    ]
    for endpoint in endpoints:
        resp = await client.get(endpoint, headers=test_customer_user["headers"])
        assert resp.status_code == 403, f"{endpoint} should be forbidden for customers (403)"


@pytest.mark.asyncio
async def test_observability_overview_accessible_by_agent_and_admin(
    client: AsyncClient, test_agent_user: dict, test_admin_user: dict
):
    """Agent and Admin roles should both be able to fetch observability overview."""
    for user_fixture in [test_agent_user, test_admin_user]:
        resp = await client.get(
            "/api/v1/analytics/observability/overview",
            headers=user_fixture["headers"],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["system_status"] == "healthy"
        assert "requests" in data
        assert "llm" in data
        assert "recent_traces_count" in data
        assert "total_requests" in data["requests"]
        assert "p50_latency_ms" in data["requests"]
        assert "total_tokens" in data["llm"]


@pytest.mark.asyncio
async def test_observability_requests_metrics_endpoint(
    client: AsyncClient, test_admin_user: dict
):
    """GET /api/v1/analytics/observability/requests returns detailed HTTP request metrics."""
    # Record a few requests through client first
    await client.get("/health")
    await client.get("/healthz")

    resp = await client.get(
        "/api/v1/analytics/observability/requests",
        headers=test_admin_user["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_requests"] >= 2
    assert "error_count" in data
    assert "error_rate" in data
    assert "p50_latency_ms" in data
    assert "p95_latency_ms" in data
    assert "p99_latency_ms" in data
    assert "endpoints" in data
    assert "status_codes" in data


@pytest.mark.asyncio
async def test_observability_llm_analytics_endpoint(
    client: AsyncClient, test_admin_user: dict, db_session
):
    """GET /api/v1/analytics/observability/llm returns LLM token & latency analytics."""
    # Seed an LLM event persisted in database
    await llm_analytics_service.persist_call(
        db=db_session,
        model="llama-3.3-70b-versatile",
        provider="groq",
        operation="test_api_call",
        prompt_tokens=500,
        completion_tokens=150,
        latency_ms=320,
        success=True,
    )
    await db_session.commit()

    resp = await client.get(
        "/api/v1/analytics/observability/llm?period=24h",
        headers=test_admin_user["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_calls"] >= 1
    assert data["tokens"]["total"] >= 650
    assert data["tokens"]["prompt"] >= 500
    assert data["tokens"]["completion"] >= 150
    assert "models" in data
    assert "llama-3.3-70b-versatile" in data["models"]


@pytest.mark.asyncio
async def test_observability_traces_endpoint(
    client: AsyncClient, test_admin_user: dict
):
    """GET /api/v1/analytics/observability/traces returns recent traces."""
    resp = await client.get(
        "/api/v1/analytics/observability/traces?limit=10",
        headers=test_admin_user["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
