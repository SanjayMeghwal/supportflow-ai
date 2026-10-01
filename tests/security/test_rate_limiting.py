"""Security tests for API Rate Limiting and Abuse Prevention (Phase 18)."""

import pytest
from httpx import AsyncClient

from backend.app.core.config import settings
from backend.app.core.rate_limit import InMemorySlidingWindow, limiter


@pytest.mark.asyncio
async def test_in_memory_sliding_window_allows_within_limit():
    """Verify that in-memory limiter permits calls up to the ceiling."""
    window = InMemorySlidingWindow()
    key = "test_client_key_1"
    limit = 5

    for i in range(limit):
        allowed, remaining, retry_after = window.check(key, limit=limit, window_seconds=60)
        assert allowed is True
        assert remaining == limit - (i + 1)
        assert retry_after == 0


@pytest.mark.asyncio
async def test_in_memory_sliding_window_blocks_on_exceed():
    """Verify that in-memory limiter blocks requests once ceiling is reached."""
    window = InMemorySlidingWindow()
    key = "test_client_key_2"
    limit = 3

    for _ in range(limit):
        allowed, _, _ = window.check(key, limit=limit, window_seconds=60)
        assert allowed is True

    # Next attempt must be blocked
    allowed, remaining, retry_after = window.check(key, limit=limit, window_seconds=60)
    assert allowed is False
    assert remaining == 0
    assert retry_after > 0


@pytest.mark.asyncio
async def test_rate_limit_headers_injected_on_auth_endpoint(client: AsyncClient):
    """Verify that rate-limited routes return standard X-RateLimit headers."""
    limiter.reset_memory()
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "WrongPassword1!"},
    )
    # Regardless of auth failure (401), rate limit headers should be set
    assert "X-RateLimit-Limit" in resp.headers
    assert "X-RateLimit-Remaining" in resp.headers
    assert int(resp.headers["X-RateLimit-Limit"]) == settings.RATE_LIMIT_AUTH


@pytest.mark.asyncio
async def test_rate_limit_triggers_429_on_excessive_attempts(client: AsyncClient):
    """Verify that exceeding rate limit triggers 429 Too Many Requests."""
    limiter.reset_memory()
    auth_limit = settings.RATE_LIMIT_AUTH

    # Exhaust limit
    for _ in range(auth_limit):
        await client.post(
            "/api/v1/auth/login",
            json={"email": "flooder@example.com", "password": "WrongPassword1!"},
        )

    # Next request must be rejected with 429
    blocked_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "flooder@example.com", "password": "WrongPassword1!"},
    )
    assert blocked_resp.status_code == 429
    assert "Retry-After" in blocked_resp.headers
    assert "rate limit exceeded" in blocked_resp.json()["detail"].lower()

    # Reset memory so other tests aren't impacted
    limiter.reset_memory()
