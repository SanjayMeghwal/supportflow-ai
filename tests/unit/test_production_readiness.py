"""Automated verification tests for Phase 20 Production Readiness."""

from unittest.mock import MagicMock
import pytest
from httpx import ASGITransport, AsyncClient

from backend.app.core.config import settings
from backend.app.core.rate_limit import get_client_ip, limiter
from backend.app.main import app


@pytest.mark.asyncio
async def test_liveness_endpoint_returns_200_without_db():
    """Verify that /health/live returns HTTP 200 and 'live' status immediately."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/live")
        assert response.status_code == 200
        data = response.json()
        assert data == {"status": "live"}


@pytest.mark.asyncio
async def test_readiness_endpoint_structure():
    """Verify that /health/ready returns a structured status with database and redis fields."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/ready")
        # Response can be 200 or 503 depending on whether test DB is active
        assert response.status_code in (200, 503)
        data = response.json()
        assert "status" in data
        assert data["status"] in ("ready", "not_ready")
        assert "database" in data
        assert "redis" in data
        # Ensure no sensitive credentials or exception details are leaked
        assert "password" not in str(data).lower()
        assert "secret" not in str(data).lower()
        assert "postgresql://" not in str(data).lower()


@pytest.mark.asyncio
async def test_general_health_endpoint_backward_compatibility_and_sanitization():
    """Verify that /health retains backward-compatible keys and never leaks raw exceptions."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "database" in data
        assert "environment" in data
        # Assert database status is clean ('healthy' or 'unhealthy', no exception traceback)
        assert data["database"] in ("healthy", "unhealthy")
        assert "Traceback" not in data["database"]
        assert "password" not in str(data).lower()


def test_database_connection_pool_settings():
    """Verify that database connection pool parameters are properly configured in Settings."""
    assert hasattr(settings, "DB_POOL_SIZE")
    assert hasattr(settings, "DB_MAX_OVERFLOW")
    assert hasattr(settings, "DB_POOL_TIMEOUT")
    assert hasattr(settings, "DB_POOL_RECYCLE")
    assert settings.DB_POOL_SIZE > 0
    assert settings.DB_MAX_OVERFLOW >= 0
    assert settings.DB_POOL_TIMEOUT > 0
    assert settings.DB_POOL_RECYCLE > 0


def test_client_ip_extraction_with_real_ip():
    """Verify that get_client_ip prioritizes X-Real-IP over client-spoofed X-Forwarded-For."""
    mock_request = MagicMock()
    mock_request.headers = {
        "X-Real-IP": "203.0.113.50",
        "X-Forwarded-For": "198.51.100.1, 10.0.0.1",
    }
    mock_request.client.host = "127.0.0.1"

    # With TRUST_PROXY_HEADERS active, X-Real-IP set by Nginx must take precedence
    original_setting = settings.TRUST_PROXY_HEADERS
    try:
        settings.TRUST_PROXY_HEADERS = True
        ip = get_client_ip(mock_request)
        assert ip == "203.0.113.50"
    finally:
        settings.TRUST_PROXY_HEADERS = original_setting


def test_client_ip_extraction_with_forwarded_for():
    """Verify that get_client_ip falls back to leftmost X-Forwarded-For if X-Real-IP absent."""
    mock_request = MagicMock()
    mock_request.headers = {
        "X-Forwarded-For": "198.51.100.22, 10.0.0.1",
    }
    mock_request.client.host = "127.0.0.1"

    original_setting = settings.TRUST_PROXY_HEADERS
    try:
        settings.TRUST_PROXY_HEADERS = True
        ip = get_client_ip(mock_request)
        assert ip == "198.51.100.22"
    finally:
        settings.TRUST_PROXY_HEADERS = original_setting


def test_client_ip_untrusted_proxy_uses_client_host():
    """Verify that get_client_ip ignores spoofed headers when TRUST_PROXY_HEADERS is False."""
    mock_request = MagicMock()
    mock_request.headers = {
        "X-Real-IP": "203.0.113.50",
        "X-Forwarded-For": "198.51.100.1",
    }
    mock_request.client.host = "192.0.2.1"

    original_setting = settings.TRUST_PROXY_HEADERS
    try:
        settings.TRUST_PROXY_HEADERS = False
        ip = get_client_ip(mock_request)
        assert ip == "192.0.2.1"
    finally:
        settings.TRUST_PROXY_HEADERS = original_setting


@pytest.mark.asyncio
async def test_rate_limiter_graceful_close():
    """Verify that limiter.close() can be called cleanly during application shutdown."""
    await limiter.close()
    assert limiter._redis_client is None


def test_env_example_contains_all_production_variables():
    """Verify that .env.example contains all essential production configuration variables."""
    from pathlib import Path
    env_example_path = Path(__file__).parents[2] / ".env.example"
    assert env_example_path.exists(), ".env.example must exist at project root"

    content = env_example_path.read_text(encoding="utf-8")
    required_variables = [
        "APP_ENV",
        "DEBUG",
        "DATABASE_URL",
        "REDIS_URL",
        "DB_POOL_SIZE",
        "DB_MAX_OVERFLOW",
        "DB_POOL_TIMEOUT",
        "DB_POOL_RECYCLE",
        "JWT_SECRET_KEY",
        "TRUST_PROXY_HEADERS",
        "CORS_ORIGINS",
        "ENABLE_SECURITY_HEADERS",
        "RATE_LIMIT_ENABLED",
        "MAX_REQUEST_BODY_SIZE",
        "MAX_FILE_UPLOAD_SIZE",
        "GROQ_API_KEY",
    ]
    for var in required_variables:
        assert f"{var}=" in content, f"Variable {var} missing from .env.example"
