"""Security tests for Authentication and Password Hardening (Phase 18)."""

from datetime import datetime, timedelta, timezone
import uuid
from jose import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.core.security import create_access_token, hash_password
from backend.app.models.user import User, UserRole


@pytest.mark.asyncio
async def test_auth_missing_token_returns_401(client: AsyncClient):
    """Missing Authorization header must return 401 Unauthorized."""
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    assert "detail" in resp.json()


@pytest.mark.asyncio
async def test_auth_malformed_token_returns_401(client: AsyncClient):
    """Malformed token string must return 401 Unauthorized."""
    resp = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-valid-jwt"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_auth_expired_token_returns_401(client: AsyncClient):
    """Expired JWT access token must be rejected with 401."""
    now = datetime.now(timezone.utc)
    expired_payload = {
        "sub": str(uuid.uuid4()),
        "type": "access",
        "iat": now - timedelta(hours=2),
        "exp": now - timedelta(hours=1),
    }
    expired_token = jwt.encode(expired_payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired_token}"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_auth_invalid_signature_returns_401(client: AsyncClient):
    """JWT signed with a foreign key must be rejected with 401."""
    now = datetime.now(timezone.utc)
    fake_payload = {
        "sub": str(uuid.uuid4()),
        "type": "access",
        "iat": now,
        "exp": now + timedelta(hours=1),
    }
    tampered_token = jwt.encode(fake_payload, "completely-wrong-secret-key-12345", algorithm=settings.JWT_ALGORITHM)

    resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tampered_token}"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_auth_token_without_sub_returns_401(client: AsyncClient):
    """JWT missing the 'sub' claim must be rejected."""
    now = datetime.now(timezone.utc)
    no_sub_payload = {
        "type": "access",
        "iat": now,
        "exp": now + timedelta(hours=1),
    }
    token = jwt.encode(no_sub_payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_auth_wrong_token_type_returns_401(client: AsyncClient):
    """Token with type != 'access' (e.g. 'refresh') cannot be used for API authentication."""
    now = datetime.now(timezone.utc)
    refresh_payload = {
        "sub": str(uuid.uuid4()),
        "type": "refresh",
        "iat": now,
        "exp": now + timedelta(hours=1),
    }
    token = jwt.encode(refresh_payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_auth_inactive_user_rejected_with_401(client: AsyncClient, db_session: AsyncSession):
    """Inactive user with otherwise valid token must be rejected with 401."""
    uid = uuid.uuid4().hex[:8]
    user = User(
        email=f"inactive_{uid}@example.com",
        hashed_password=hash_password("ValidPassword123!"),
        role=UserRole.CUSTOMER,
        is_active=False,
    )
    db_session.add(user)
    await db_session.commit()

    token = create_access_token(
        user_id=str(user.id),
        secret_key=settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
        expires_minutes=60,
    )

    resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert "inactive" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_login_generic_error_prevents_user_enumeration(client: AsyncClient):
    """Non-existent email and wrong password must return identical error detail."""
    resp1 = await client.post(
        "/api/v1/auth/login",
        json={"email": "nonexistent_email_123456@example.com", "password": "WrongPassword1!"},
    )
    assert resp1.status_code == 401

    resp2 = await client.post(
        "/api/v1/auth/login",
        json={"email": "customer@example.com", "password": "DefinitelyWrongPassword1!"},
    )
    assert resp2.status_code == 401

    assert resp1.json()["detail"] == resp2.json()["detail"]
    assert resp1.json()["detail"] == "Invalid credentials."


@pytest.mark.asyncio
async def test_password_hash_never_exposed_in_api_responses(client: AsyncClient, test_admin_user: dict):
    """Verify that password hash is never present in user payload or profile."""
    resp = await client.get("/api/v1/auth/me", headers=test_admin_user["headers"])
    assert resp.status_code == 200
    data = resp.json()
    assert "password" not in data
    assert "hashed_password" not in data
