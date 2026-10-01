"""Security tests for Error Sanitization and Information Leakage Prevention (Phase 18)."""

import pytest
from httpx import AsyncClient
from unittest.mock import patch


@pytest.mark.asyncio
async def test_unhandled_exception_returns_safe_500_response(client: AsyncClient):
    """Verify that unhandled server exceptions do not leak stack traces, database strings, or paths."""
    with patch("backend.app.api.v1.auth.login", side_effect=RuntimeError("Database password leaked! /var/secret/db.key")):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "test@example.com", "password": "Password123!"},
        )
        assert resp.status_code == 500
        data = resp.json()

        # The error response must NOT contain the exception string, file paths, or stack trace
        assert "password" not in data["detail"].lower()
        assert "secret" not in data["detail"].lower()
        assert "Traceback" not in resp.text
        assert "request_id" in data
