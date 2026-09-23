"""Comprehensive API and authorization test suite for Phase 4.

Covers:
  1. Password hashing works.
  2. Password verification works.
  3. Registration succeeds.
  4. Duplicate email is rejected.
  5. Password is never returned in API response.
  6. Login succeeds with valid credentials.
  7. Login fails with invalid password.
  8. Login fails for nonexistent user.
  9. JWT is generated.
  10. /auth/me works with valid token.
  11. /auth/me rejects missing token.
  12. /auth/me rejects invalid token.
  13. Expired token is rejected.
  14. Inactive user cannot authenticate/use protected endpoints.
  15. Customer cannot use a customer-only endpoint without authentication.
  16. Role-protected endpoint rejects insufficient role.
  17. Correct role can access role-protected endpoint.
  18. Resource ownership enforcement prevents IDOR attacks.
"""

import uuid
import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.deps import (
    get_current_customer,
    require_admin,
    require_customer,
    require_roles,
    verify_resource_ownership,
)
from backend.app.core.config import settings
from backend.app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from backend.app.models.user import UserRole


# ---------------------------------------------------------------------------
# 1 & 2: Password Security Primitives
# ---------------------------------------------------------------------------


def test_password_hashing_works():
    """Requirement 1: Password hashing works and produces salted bcrypt hash."""
    plain = "MySecretSecurePassword123!"
    hashed = hash_password(plain)

    assert hashed != plain
    assert hashed.startswith("$2b$") or hashed.startswith("$2a$")
    assert len(hashed) >= 50


def test_password_verification_works():
    """Requirement 2: Password verification works for valid and invalid credentials."""
    plain = "MySecretSecurePassword123!"
    hashed = hash_password(plain)

    assert verify_password(plain, hashed) is True
    assert verify_password("WrongPassword!", hashed) is False
    assert verify_password("", hashed) is False


# ---------------------------------------------------------------------------
# 3, 4, 5: Registration Endpoints & Response Sanitization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registration_succeeds(client: AsyncClient):
    """Requirement 3: Registration succeeds and creates customer account."""
    unique = uuid.uuid4().hex[:8]
    payload = {
        "email": f"NewUser_{unique}@Example.COM",  # Test normalization (upper to lower)
        "password": "SecurePassword123!",
        "full_name": "New Customer Name",
    }
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert data["email"] == f"newuser_{unique}@example.com"
    assert data["role"] == "CUSTOMER"
    assert data["is_active"] is True
    assert "id" in data
    assert "created_at" in data


@pytest.mark.asyncio
async def test_duplicate_email_rejected(client: AsyncClient, test_customer_user: dict):
    """Requirement 4: Duplicate email is rejected with 409 Conflict."""
    payload = {
        "email": test_customer_user["email"],
        "password": "AnotherPassword123!",
        "full_name": "Duplicate User",
    }
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 409
    data = response.json()
    assert "already exists" in data["detail"]


@pytest.mark.asyncio
async def test_password_never_returned_in_api_response(client: AsyncClient, test_customer_user: dict):
    """Requirement 5: Password is never returned in any API response."""
    # 1. Register endpoint
    unique = uuid.uuid4().hex[:8]
    reg_response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"sanitize_{unique}@example.com",
            "password": "SecurePassword123!",
            "full_name": "Sanitization Check",
        },
    )
    reg_data = reg_response.json()
    assert "password" not in reg_data
    assert "hashed_password" not in reg_data

    # 2. Login endpoint
    login_response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": test_customer_user["email"],
            "password": test_customer_user["raw_password"],
        },
    )
    login_data = login_response.json()
    assert "password" not in login_data
    assert "hashed_password" not in login_data
    assert "password" not in login_data["user"]
    assert "hashed_password" not in login_data["user"]

    # 3. Current user /auth/me endpoint
    me_response = await client.get("/api/v1/auth/me", headers=test_customer_user["headers"])
    me_data = me_response.json()
    assert "password" not in me_data
    assert "hashed_password" not in me_data


# ---------------------------------------------------------------------------
# 6, 7, 8, 9: Authentication & JWT Generation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_succeeds_with_valid_credentials(client: AsyncClient, test_customer_user: dict):
    """Requirement 6: Login succeeds with valid credentials."""
    response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": test_customer_user["email"],
            "password": test_customer_user["raw_password"],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == test_customer_user["email"]


@pytest.mark.asyncio
async def test_login_fails_with_invalid_password(client: AsyncClient, test_customer_user: dict):
    """Requirement 7: Login fails with invalid password."""
    response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": test_customer_user["email"],
            "password": "WrongPassword999!",
        },
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials."


@pytest.mark.asyncio
async def test_login_fails_for_nonexistent_user(client: AsyncClient):
    """Requirement 8: Login fails for nonexistent user without leaking existence."""
    response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "nonexistent_user_never_created@example.com",
            "password": "AnyPassword123!",
        },
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials."


def test_jwt_is_generated():
    """Requirement 9: JWT is generated with valid claims and structure."""
    user_id = str(uuid.uuid4())
    token = create_access_token(
        user_id=user_id,
        secret_key=settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
        expires_minutes=15,
    )
    assert isinstance(token, str)
    decoded = decode_access_token(
        token=token,
        secret_key=settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    assert decoded == user_id


# ---------------------------------------------------------------------------
# 10, 11, 12, 13: Protected /auth/me Endpoint & Token Validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_me_works_with_valid_token(client: AsyncClient, test_customer_user: dict):
    """Requirement 10: /auth/me works with valid token."""
    response = await client.get("/api/v1/auth/me", headers=test_customer_user["headers"])
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == test_customer_user["email"]
    assert data["role"] == "CUSTOMER"
    assert data["full_name"] == test_customer_user["customer"].full_name


@pytest.mark.asyncio
async def test_auth_me_rejects_missing_token(client: AsyncClient):
    """Requirement 11: /auth/me rejects missing token with 401."""
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_auth_me_rejects_invalid_token(client: AsyncClient):
    """Requirement 12: /auth/me rejects invalid token with 401."""
    headers = {"Authorization": "Bearer invalid.token.payload"}
    response = await client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_expired_token_is_rejected(client: AsyncClient, test_customer_user: dict):
    """Requirement 13: Expired token is rejected with 401."""
    expired_token = create_access_token(
        user_id=str(test_customer_user["user"].id),
        secret_key=settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
        expires_minutes=-10,  # Expired 10 minutes ago
    )
    headers = {"Authorization": f"Bearer {expired_token}"}
    response = await client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# 14: Inactive User Rejection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inactive_user_cannot_authenticate_or_use_protected_endpoints(
    client: AsyncClient, test_inactive_user: dict
):
    """Requirement 14: Inactive user cannot authenticate or access protected endpoints."""
    # Attempt login
    login_response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": test_inactive_user["email"],
            "password": test_inactive_user["raw_password"],
        },
    )
    assert login_response.status_code == 401

    # Attempt accessing protected endpoint with pre-generated token
    me_response = await client.get("/api/v1/auth/me", headers=test_inactive_user["headers"])
    assert me_response.status_code == 401
    assert "inactive" in me_response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 15, 16, 17: Role-Based Access Control (RBAC)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_customer_cannot_use_customer_only_endpoint_without_auth(client: AsyncClient):
    """Requirement 15: Customer-only endpoint rejects unauthenticated access with 401."""
    # /auth/me requires authentication and returns 401 if unauthenticated
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_role_protected_endpoint_rejects_insufficient_role(test_customer_user: dict):
    """Requirement 16: Role-protected authorization rejects insufficient role with 403 Forbidden."""
    # CUSTOMER role attempting an ADMIN-only dependency check
    admin_guard = require_roles(UserRole.ADMIN)
    with pytest.raises(HTTPException) as exc_info:
        await admin_guard(current_user=test_customer_user["user"])
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Insufficient permissions."


@pytest.mark.asyncio
async def test_correct_role_can_access_role_protected_endpoint(test_admin_user: dict):
    """Requirement 17: Correct role passes role-protected authorization."""
    # ADMIN role successfully passes the ADMIN-only dependency check
    admin_guard = require_roles(UserRole.ADMIN)
    authorized_user = await admin_guard(current_user=test_admin_user["user"])
    assert authorized_user.id == test_admin_user["user"].id
    assert authorized_user.role == UserRole.ADMIN


# ---------------------------------------------------------------------------
# 18: Resource Ownership Scoping (IDOR Prevention)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resource_ownership_enforcement_prevents_idor(
    db_session: AsyncSession,
    test_customer_user: dict,
    test_admin_user: dict,
):
    """Requirement 18 (Security): Resource ownership verifies customer identity against IDOR.

    - CUSTOMER accessing own customer record succeeds (returns True).
    - CUSTOMER attempting to access another customer's record is blocked (raises 403).
    - ADMIN possesses oversight privilege and can access the record (returns True).
    """
    own_customer_id = test_customer_user["customer"].id
    foreign_customer_id = uuid.uuid4()  # Belongs to a different customer

    # 1. Customer accesses own resource -> succeeds
    assert await verify_resource_ownership(
        resource_customer_id=own_customer_id,
        current_user=test_customer_user["user"],
        db=db_session,
    ) is True

    # 2. Customer attempts IDOR against foreign resource -> 403 Forbidden
    with pytest.raises(HTTPException) as exc_info:
        await verify_resource_ownership(
            resource_customer_id=foreign_customer_id,
            current_user=test_customer_user["user"],
            db=db_session,
        )
    assert exc_info.value.status_code == 403
    assert "do not own" in exc_info.value.detail

    # 3. Admin has authorized oversight across customer resources -> succeeds
    assert await verify_resource_ownership(
        resource_customer_id=own_customer_id,
        current_user=test_admin_user["user"],
        db=db_session,
    ) is True

