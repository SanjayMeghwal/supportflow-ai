"""Security tests for HTTP Security Headers and Request Size Limits (Phase 18)."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_security_headers_present_on_endpoints(client: AsyncClient):
    """Verify that all standard hardening HTTP headers are returned."""
    resp = await client.get("/health")
    assert resp.status_code == 200

    headers = resp.headers
    assert headers.get("X-Content-Type-Options") == "nosniff"
    assert headers.get("X-Frame-Options") == "DENY"
    assert headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert "Content-Security-Policy" in headers
    assert "Permissions-Policy" in headers


@pytest.mark.asyncio
async def test_oversized_payload_rejected_with_413(client: AsyncClient):
    """Requests declaring Content-Length greater than MAX_REQUEST_BODY_SIZE must return 413."""
    oversized_length = str(20 * 1024 * 1024)  # 20 MB
    resp = await client.post(
        "/api/v1/auth/login",
        headers={"Content-Length": oversized_length, "Content-Type": "application/json"},
        content=b"{}",
    )
    assert resp.status_code == 413
    assert "exceeds maximum permitted size" in resp.json()["detail"].lower()
