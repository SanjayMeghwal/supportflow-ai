import pytest
from httpx import ASGITransport, AsyncClient
from backend.app.main import app


@pytest.mark.asyncio
async def test_root_endpoint():
    """Verify root status endpoint returns application metadata."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["app"] == "SupportFlow AI"
        assert data["status"] == "online"
        assert data["version"] == "0.1.0"


@pytest.mark.asyncio
async def test_health_check_endpoint():
    """Verify health check endpoint returns valid response structure."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "database" in data
        assert "environment" in data
