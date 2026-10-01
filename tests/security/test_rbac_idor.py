"""Security tests for RBAC, IDOR and Tenant/Customer Resource Isolation (Phase 18)."""

import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.security import create_access_token, hash_password
from backend.app.core.config import settings
from backend.app.models.ticket import Ticket, TicketCategory, TicketPriority, TicketStatus
from backend.app.models.user import Customer, User, UserRole


async def _seed_customer_and_ticket(db: AsyncSession, *, name: str) -> tuple[dict, Ticket]:
    """Helper to seed an independent customer and ticket."""
    uid = uuid.uuid4().hex[:8]
    user = User(
        email=f"{name.lower().replace(' ', '_')}_{uid}@example.com",
        hashed_password=hash_password("SecurePassword123!"),
        role=UserRole.CUSTOMER,
        is_active=True,
    )
    db.add(user)
    await db.flush()

    customer = Customer(
        user_id=user.id,
        full_name=f"{name} {uid}",
    )
    db.add(customer)
    await db.flush()

    ticket = Ticket(
        ticket_number=f"TKT-TEST-{uid.upper()}",
        customer_id=customer.id,
        title=f"Secret Ticket for {name}",
        description="Confidential ticket contents.",
        category=TicketCategory.BILLING,
        priority=TicketPriority.HIGH,
        status=TicketStatus.OPEN,
    )
    db.add(ticket)
    await db.commit()
    await db.refresh(ticket)

    token = create_access_token(
        user_id=str(user.id),
        secret_key=settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
        expires_minutes=60,
    )
    auth_data = {
        "user": user,
        "customer": customer,
        "headers": {"Authorization": f"Bearer {token}"},
    }
    return auth_data, ticket


@pytest.mark.asyncio
async def test_customer_cannot_access_observability_endpoints(client: AsyncClient, test_customer_user: dict):
    """Customer role must be forbidden from accessing admin observability endpoints."""
    endpoints = [
        "/api/v1/analytics/observability/overview",
        "/api/v1/analytics/observability/requests",
        "/api/v1/analytics/observability/llm",
        "/api/v1/analytics/observability/traces",
    ]
    for endpoint in endpoints:
        resp = await client.get(endpoint, headers=test_customer_user["headers"])
        assert resp.status_code == 403, f"Endpoint {endpoint} was not forbidden for customer"
        assert resp.json()["detail"] == "Insufficient permissions."


@pytest.mark.asyncio
async def test_customer_cannot_upload_knowledge_documents(client: AsyncClient, test_customer_user: dict):
    """Customer role cannot access knowledge ingestion upload endpoint."""
    resp = await client.post(
        "/api/v1/knowledge/upload",
        files={"file": ("test.txt", b"some knowledge", "text/plain")},
        data={"title": "Unauthorized Upload"},
        headers=test_customer_user["headers"],
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_idor_customer_cannot_view_foreign_ticket(client: AsyncClient, db_session: AsyncSession):
    """Customer A must be forbidden from viewing Customer B's ticket."""
    cust_a, _ = await _seed_customer_and_ticket(db_session, name="Alice")
    _, ticket_b = await _seed_customer_and_ticket(db_session, name="Bob")

    resp = await client.get(f"/api/v1/tickets/{ticket_b.id}", headers=cust_a["headers"])
    assert resp.status_code == 403
    assert "forbidden" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_idor_customer_cannot_patch_foreign_ticket(client: AsyncClient, db_session: AsyncSession):
    """Customer A cannot update metadata of Customer B's ticket."""
    cust_a, _ = await _seed_customer_and_ticket(db_session, name="CustomerA")
    _, ticket_b = await _seed_customer_and_ticket(db_session, name="CustomerB")

    resp = await client.patch(
        f"/api/v1/tickets/{ticket_b.id}",
        json={"priority": "CRITICAL"},
        headers=cust_a["headers"],
    )
    # PATCH requires agent or admin role -> 403
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_idor_customer_cannot_message_foreign_ticket(client: AsyncClient, db_session: AsyncSession):
    """Customer A cannot append a message to Customer B's ticket thread."""
    cust_a, _ = await _seed_customer_and_ticket(db_session, name="CustomerA")
    _, ticket_b = await _seed_customer_and_ticket(db_session, name="CustomerB")

    resp = await client.post(
        f"/api/v1/tickets/{ticket_b.id}/messages",
        json={"content": "Injected malicious message"},
        headers=cust_a["headers"],
    )
    assert resp.status_code == 403
    assert "forbidden" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_idor_customer_cannot_read_messages_of_foreign_ticket(client: AsyncClient, db_session: AsyncSession):
    """Customer A cannot read messages belonging to Customer B's ticket thread."""
    cust_a, _ = await _seed_customer_and_ticket(db_session, name="CustomerA")
    _, ticket_b = await _seed_customer_and_ticket(db_session, name="CustomerB")

    resp = await client.get(
        f"/api/v1/tickets/{ticket_b.id}/messages",
        headers=cust_a["headers"],
    )
    assert resp.status_code == 403
    assert "forbidden" in resp.json()["detail"].lower()
