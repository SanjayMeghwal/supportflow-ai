from unittest.mock import patch
import pytest
from httpx import ASGITransport, AsyncClient
from backend.app.main import app


@pytest.mark.asyncio
async def test_unhandled_exception_returns_safe_500_response():
    """Verify that unhandled server exceptions do not leak stack traces, database strings, or paths."""
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("sqlalchemy.ext.asyncio.AsyncSession.execute", side_effect=RuntimeError("Database password leaked! /var/secret/db.key")):
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
