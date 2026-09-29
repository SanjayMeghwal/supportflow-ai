"""Phase 15 — Integration tests: Authentication, RBAC, and Security Hardening.

Exercises the security invariants of the entire system:

Boundary / Input Fuzzing:
  1.  Oversized JWT token is rejected.
  2.  Malformed Bearer token string is rejected.
  3.  JWT with wrong algorithm is rejected.
  4.  JWT with tampered payload is rejected.
  5.  Expired JWT is rejected.
  6.  Inactive user with valid token is rejected.

RBAC / Authorization:
  7.  CUSTOMER cannot access agent-only endpoints.
  8.  CUSTOMER cannot access admin-only endpoints.
  9.  SUPPORT_AGENT cannot access admin-only endpoints.
  10. ADMIN can access all role-protected endpoints.
  11. Missing Authorization header returns 401 (not 403 or 422).

IDOR Penetration:
  12. Customer cannot GET another customer's ticket detail.
  13. Customer cannot PATCH another customer's ticket.
  14. Customer cannot POST message to another customer's ticket.
  15. Customer cannot GET messages from another customer's ticket.
  16. Customer cannot assign an agent to another customer's ticket.

Token Integrity:
  17. Replaying a valid token from another user does not cross identity boundaries.
  18. Token without 'sub' claim is rejected.

Registration:
  19. Registering with a weak password is rejected with 422.
  20. Registering with an invalid email format is rejected with 422.
  21. Registering the same email twice returns 409 Conflict.
"""

import uuid
import time
import pytest
from jose import jwt
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.security import hash_password, create_access_token
from backend.app.core.config import settings
from backend.app.models.ticket import Ticket, TicketPriority, TicketStatus
from backend.app.models.user import Customer, User, UserRole


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register_user(client: AsyncClient, *, email: str, password: str, role: str = "CUSTOMER") -> dict:
    """Register a new user via POST /api/v1/auth/register."""
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "role": role},
    )
    return resp


async def _create_customer_with_token(db: AsyncSession) -> dict:
    """Seed a customer user directly in DB and return auth dict."""
    uid = uuid.uuid4().hex[:8]
    user = User(
        email=f"sec_{uid}@example.com",
        hashed_password=hash_password("SecurePass123!"),
        role=UserRole.CUSTOMER,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    customer = Customer(user_id=user.id, full_name=f"Sec Customer {uid}")
    db.add(customer)
    await db.commit()
    await db.refresh(user)
    await db.refresh(customer)
    token = create_access_token(
        user_id=str(user.id),
        secret_key=settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
        expires_minutes=60,
    )
    return {
        "user": user,
        "customer": customer,
        "token": token,
        "headers": _bearer(token),
    }


async def _create_ticket_for(client: AsyncClient, headers: dict, title: str = "Security Test Ticket") -> str:
    """Create a ticket and return its ID."""
    resp = await client.post(
        "/api/v1/tickets",
        json={"title": title, "description": "Security test ticket for IDOR/RBAC assertions."},
        headers=headers,
    )
    assert resp.status_code == 201
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# 1. Oversized JWT token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_oversized_jwt_token_rejected(client: AsyncClient):
    """Req 1: A massively oversized bearer token is rejected (401 or 422)."""
    huge_token = "x" * 10000
    resp = await client.get("/api/v1/auth/me", headers=_bearer(huge_token))
    assert resp.status_code in (401, 422)


# ---------------------------------------------------------------------------
# 2. Malformed Bearer token string
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_malformed_bearer_token_rejected(client: AsyncClient):
    """Req 2: Arbitrary non-JWT strings in Authorization header are rejected."""
    for malformed in ["not-a-jwt", "Bearer", "Bearer  ", "null", "undefined", "."]:
        resp = await client.get("/api/v1/auth/me", headers={"Authorization": malformed})
        assert resp.status_code in (401, 422), f"Expected 401/422 for '{malformed}', got {resp.status_code}"


# ---------------------------------------------------------------------------
# 3. JWT signed with wrong algorithm
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jwt_wrong_algorithm_rejected(client: AsyncClient):
    """Req 3: JWT signed with a different algorithm (HS512) is rejected."""
    wrong_alg_token = jwt.encode(
        {"sub": str(uuid.uuid4()), "exp": int(time.time()) + 3600},
        settings.JWT_SECRET_KEY,
        algorithm="HS512",
    )
    resp = await client.get("/api/v1/auth/me", headers=_bearer(wrong_alg_token))
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 4. JWT with tampered payload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jwt_tampered_payload_rejected(client: AsyncClient):
    """Req 4: A JWT with a valid header but tampered signature is rejected."""
    # Sign with a completely different secret
    tampered_token = jwt.encode(
        {"sub": str(uuid.uuid4()), "exp": int(time.time()) + 3600},
        "wrong-secret-key-1234567890",
        algorithm=settings.JWT_ALGORITHM,
    )
    resp = await client.get("/api/v1/auth/me", headers=_bearer(tampered_token))
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 5. Expired JWT
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_expired_jwt_rejected(client: AsyncClient):
    """Req 5: An expired token is rejected with 401."""
    expired_token = create_access_token(
        user_id=str(uuid.uuid4()),
        secret_key=settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
        expires_minutes=-1,  # already expired
    )
    resp = await client.get("/api/v1/auth/me", headers=_bearer(expired_token))
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 6. Inactive user with valid token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inactive_user_token_rejected(
    client: AsyncClient,
    test_inactive_user: dict,
):
    """Req 6: An inactive user's valid token is rejected with 401."""
    resp = await client.get("/api/v1/auth/me", headers=test_inactive_user["headers"])
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 7. CUSTOMER cannot access agent-only endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_customer_cannot_access_agent_endpoints(
    client: AsyncClient,
    test_customer_user: dict,
):
    """Req 7: CUSTOMER role is blocked from agent-only endpoints."""
    # Review queue is agent-only
    resp = await client.get("/api/v1/reviews/pending", headers=test_customer_user["headers"])
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 8. CUSTOMER cannot access admin-only endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_customer_cannot_access_admin_endpoints(
    client: AsyncClient,
    test_customer_user: dict,
):
    """Req 8: CUSTOMER role is blocked from admin-only analytics endpoint."""
    resp = await client.get("/api/v1/analytics/summary", headers=test_customer_user["headers"])
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 9. SUPPORT_AGENT cannot perform admin-exclusive write operations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_cannot_delete_knowledge_documents(
    client: AsyncClient,
    test_agent_user: dict,
):
    """Req 9: SUPPORT_AGENT cannot delete knowledge documents (admin-only operation)."""
    fake_doc_id = str(uuid.uuid4())
    resp = await client.delete(
        f"/api/v1/knowledge/{fake_doc_id}",
        headers=test_agent_user["headers"],
    )
    # Should be 403 (forbidden) or 404 (if agent can't see it) — never 200
    assert resp.status_code in (403, 404)
    # Critically: must not be 200 (agent cannot delete knowledge docs)
    assert resp.status_code != 200


# ---------------------------------------------------------------------------
# 10. ADMIN can access all role-protected endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_can_access_analytics(
    client: AsyncClient,
    test_admin_user: dict,
):
    """Req 10: ADMIN role can access all elevated endpoints including analytics."""
    resp = await client.get("/api/v1/analytics/summary", headers=test_admin_user["headers"])
    assert resp.status_code == 200
    data = resp.json()
    assert "total_tickets" in data
    assert "total_reviews" in data


# ---------------------------------------------------------------------------
# 11. Missing Authorization header returns 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_auth_header_returns_401(client: AsyncClient):
    """Req 11: All protected endpoints return 401 (not 403 or 422) with no auth header."""
    protected_endpoints = [
        ("GET", "/api/v1/auth/me"),
        ("GET", "/api/v1/tickets"),
        ("GET", "/api/v1/reviews/pending"),
        ("GET", "/api/v1/analytics/summary"),
    ]
    for method, path in protected_endpoints:
        resp = await client.request(method, path)
        assert resp.status_code == 401, (
            f"Expected 401 for {method} {path} without auth, got {resp.status_code}"
        )


# ---------------------------------------------------------------------------
# 12. Customer cannot GET another customer's ticket
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_customer_cannot_get_others_ticket(
    client: AsyncClient,
    db_session: AsyncSession,
    test_customer_user: dict,
):
    """Req 12: IDOR — Customer B cannot view Customer A's ticket detail."""
    customer_b = await _create_customer_with_token(db_session)

    # Customer A creates a ticket
    ticket_id = await _create_ticket_for(client, test_customer_user["headers"])

    # Customer B attempts to view it
    resp = await client.get(f"/api/v1/tickets/{ticket_id}", headers=customer_b["headers"])
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 13. Customer cannot PATCH another customer's ticket
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_customer_cannot_patch_others_ticket(
    client: AsyncClient,
    db_session: AsyncSession,
    test_customer_user: dict,
):
    """Req 13: Customers cannot update any ticket (role-level enforcement)."""
    customer_b = await _create_customer_with_token(db_session)

    ticket_id = await _create_ticket_for(client, test_customer_user["headers"])

    # Customer B tries to PATCH — customer role cannot update any ticket
    resp = await client.patch(
        f"/api/v1/tickets/{ticket_id}",
        json={"status": "CLOSED"},
        headers=customer_b["headers"],
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 14. Customer cannot POST message to another customer's ticket
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_customer_cannot_post_message_to_others_ticket(
    client: AsyncClient,
    db_session: AsyncSession,
    test_customer_user: dict,
):
    """Req 14: IDOR — Customer B cannot post messages to Customer A's ticket."""
    customer_b = await _create_customer_with_token(db_session)
    ticket_id = await _create_ticket_for(client, test_customer_user["headers"])

    resp = await client.post(
        f"/api/v1/tickets/{ticket_id}/messages",
        json={"content": "IDOR injection attempt from Customer B."},
        headers=customer_b["headers"],
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 15. Customer cannot GET messages from another customer's ticket
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_customer_cannot_get_messages_from_others_ticket(
    client: AsyncClient,
    db_session: AsyncSession,
    test_customer_user: dict,
):
    """Req 15: IDOR — Customer B cannot read messages from Customer A's ticket."""
    customer_b = await _create_customer_with_token(db_session)
    ticket_id = await _create_ticket_for(client, test_customer_user["headers"])

    # Customer A adds a sensitive message
    await client.post(
        f"/api/v1/tickets/{ticket_id}/messages",
        json={"content": "Sensitive billing data"},
        headers=test_customer_user["headers"],
    )

    # Customer B tries to read the messages
    resp = await client.get(
        f"/api/v1/tickets/{ticket_id}/messages",
        headers=customer_b["headers"],
    )
    assert resp.status_code == 403
    assert "Sensitive billing data" not in resp.text


# ---------------------------------------------------------------------------
# 16. Customer cannot assign agent to another customer's ticket
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_customer_cannot_assign_to_others_ticket(
    client: AsyncClient,
    db_session: AsyncSession,
    test_customer_user: dict,
):
    """Req 16: Customers cannot assign any ticket at all (role enforcement)."""
    customer_b = await _create_customer_with_token(db_session)
    ticket_id = await _create_ticket_for(client, test_customer_user["headers"])

    resp = await client.post(
        f"/api/v1/tickets/{ticket_id}/assign",
        json={"agent_id": str(uuid.uuid4())},
        headers=customer_b["headers"],
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 17. Token replay: User A's token cannot impersonate User B
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_identity_isolation(
    client: AsyncClient,
    test_customer_user: dict,
    db_session: AsyncSession,
):
    """Req 17: User A's token returns User A's identity, not User B's."""
    # Get Customer A's identity
    resp_a = await client.get("/api/v1/auth/me", headers=test_customer_user["headers"])
    assert resp_a.status_code == 200
    identity_a = resp_a.json()

    # Create Customer B
    customer_b = await _create_customer_with_token(db_session)

    # Use Customer B's token
    resp_b = await client.get("/api/v1/auth/me", headers=customer_b["headers"])
    assert resp_b.status_code == 200
    identity_b = resp_b.json()

    # Identities must be distinct
    assert identity_a["id"] != identity_b["id"]
    assert identity_a["email"] != identity_b["email"]


# ---------------------------------------------------------------------------
# 18. Token without 'sub' claim is rejected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_without_sub_claim_rejected(client: AsyncClient):
    """Req 18: A JWT with no 'sub' field fails authentication."""
    token_no_sub = jwt.encode(
        {"exp": int(time.time()) + 3600, "data": "no-sub-field"},
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    resp = await client.get("/api/v1/auth/me", headers=_bearer(token_no_sub))
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 19. Weak password rejected on registration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registration_rejects_weak_password(client: AsyncClient):
    """Req 19: Passwords that are too short are rejected with 422."""
    uid = uuid.uuid4().hex[:8]
    resp = await _register_user(client, email=f"weak_{uid}@example.com", password="abc")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 20. Invalid email format rejected on registration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registration_rejects_invalid_email(client: AsyncClient):
    """Req 20: Invalid email formats are rejected with 422."""
    for invalid_email in ["not-an-email", "missing@", "@nodomain.com", "a@b"]:
        resp = await _register_user(client, email=invalid_email, password="StrongPass123!")
        assert resp.status_code == 422, f"Expected 422 for email '{invalid_email}'"


# ---------------------------------------------------------------------------
# 21. Duplicate email registration returns 409
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registration_duplicate_email_returns_409(
    client: AsyncClient,
    test_customer_user: dict,
):
    """Req 21: Registering with an already-registered email returns 409 Conflict."""
    resp = await _register_user(
        client,
        email=test_customer_user["email"],
        password="AnotherPass456!",
    )
    assert resp.status_code == 409
