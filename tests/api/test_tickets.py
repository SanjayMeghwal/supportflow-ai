"""Comprehensive API test suite for Phase 5 — Ticket Management.

Covers:
  1.  Customer creates a ticket successfully.
  2.  Ticket creation requires authentication.
  3.  Agent/Admin cannot create tickets.
  4.  Customer lists only their own tickets.
  5.  Agent lists all tickets across customers.
  6.  Customer gets own ticket detail.
  7.  Customer cannot access another customer's ticket.
  8.  Agent gets any ticket detail regardless of ownership.
  9.  Agent updates ticket status.
  10. Customer cannot update ticket.
  11. Invalid status transition is rejected.
  12. Customer adds a message.
  13. Agent adds a message.
  14. Agent adds an internal note.
  15. Customer cannot see internal notes.
  16. Customer cannot create internal notes.
  17. Agent assigns ticket to another agent.
  18. Customer cannot assign tickets.
  19. Pagination works correctly.
  20. Status filter works on list endpoint.
  21. Customer B cannot POST a message to Customer A's ticket (IDOR).
  22. Customer B cannot GET messages from Customer A's ticket (IDOR).
"""

import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.core.security import create_access_token, hash_password
from backend.app.models.ticket import (
    SenderType,
    Ticket,
    TicketMessage,
    TicketPriority,
    TicketStatus,
)
from backend.app.models.user import Customer, User, UserRole


# ---------------------------------------------------------------------------
# Helpers for test setup
# ---------------------------------------------------------------------------


async def _seed_ticket(
    db: AsyncSession,
    customer_id: uuid.UUID,
    *,
    ticket_number: str | None = None,
    status: TicketStatus = TicketStatus.OPEN,
    title: str = "Seeded Test Ticket",
    description: str = "This is a seeded test ticket for testing purposes.",
) -> Ticket:
    """Insert a ticket directly via ORM for test setup."""
    ticket = Ticket(
        ticket_number=ticket_number or f"TKT-SEED-{uuid.uuid4().hex[:5].upper()}",
        customer_id=customer_id,
        title=title,
        description=description,
        priority=TicketPriority.MEDIUM,
        status=status,
    )
    db.add(ticket)
    await db.flush()
    await db.refresh(ticket)
    return ticket


async def _create_customer_user(
    db: AsyncSession,
    *,
    email_prefix: str = "customer",
    full_name: str = "Test Customer",
) -> dict:
    """Helper to create and authenticate an additional customer user with valid bearer headers."""
    unique_id = uuid.uuid4().hex[:8]
    email = f"{email_prefix}_{unique_id}@example.com"
    raw_password = "Password123!"
    user = User(
        email=email,
        hashed_password=hash_password(raw_password),
        role=UserRole.CUSTOMER,
        is_active=True,
    )
    db.add(user)
    await db.flush()

    customer = Customer(
        user_id=user.id,
        full_name=f"{full_name} {unique_id}",
    )
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
        "email": email,
        "raw_password": raw_password,
        "token": token,
        "headers": {"Authorization": f"Bearer {token}"},
    }


# ---------------------------------------------------------------------------
# 1. Customer Creates Ticket
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_customer_creates_ticket(client: AsyncClient, test_customer_user: dict):
    """Requirement 1: Customer can create a ticket; ticket_number is auto-generated."""
    payload = {
        "title": "My internet connection is slow",
        "description": "I've been experiencing very slow speeds for the past 3 days. My plan should be 100 Mbps.",
        "category": "TECHNICAL",
    }
    response = await client.post(
        "/api/v1/tickets", json=payload, headers=test_customer_user["headers"]
    )
    assert response.status_code == 201

    data = response.json()
    assert data["title"] == "My internet connection is slow"
    assert data["category"] == "TECHNICAL"
    assert data["status"] == "OPEN"
    assert data["priority"] == "MEDIUM"
    assert data["customer_id"] == str(test_customer_user["customer"].id)
    assert data["ticket_number"].startswith("TKT-")
    assert data["assigned_agent_id"] is None
    assert "id" in data
    assert "created_at" in data


# ---------------------------------------------------------------------------
# 2. Ticket Creation Requires Authentication
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ticket_creation_requires_authentication(client: AsyncClient):
    """Requirement 2: Cannot create ticket without authentication."""
    payload = {
        "title": "Unauthorized ticket attempt",
        "description": "This should fail because there is no auth token.",
    }
    response = await client.post("/api/v1/tickets", json=payload)
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# 3. Agent/Admin Cannot Create Tickets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_cannot_create_tickets(client: AsyncClient, test_agent_user: dict):
    """Requirement 3: Only CUSTOMER role can create tickets."""
    payload = {
        "title": "Agent trying to create ticket",
        "description": "This should fail because agents cannot create tickets.",
    }
    response = await client.post(
        "/api/v1/tickets", json=payload, headers=test_agent_user["headers"]
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_cannot_create_tickets(client: AsyncClient, test_admin_user: dict):
    """Requirement 3b: ADMIN role also cannot create tickets."""
    payload = {
        "title": "Admin trying to create ticket",
        "description": "This should fail because admins cannot create tickets.",
    }
    response = await client.post(
        "/api/v1/tickets", json=payload, headers=test_admin_user["headers"]
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# 4. Customer Lists Only Own Tickets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_customer_lists_only_own_tickets(
    client: AsyncClient,
    db_session: AsyncSession,
    test_customer_user: dict,
):
    """Requirement 4: Customer sees only their own tickets, not others."""
    # Create a ticket for this customer via API
    await client.post(
        "/api/v1/tickets",
        json={
            "title": "My own ticket",
            "description": "This is a ticket I created for filtering test.",
        },
        headers=test_customer_user["headers"],
    )

    # Create a ticket for a DIFFERENT customer directly in DB
    other_customer = Customer(
        user_id=uuid.uuid4(),  # Non-existent user, but fine for DB seeding
        full_name="Other Customer",
    )
    # We need a real user for the FK — use a separate approach
    from backend.app.core.security import hash_password
    from backend.app.models.user import User, UserRole

    other_user = User(
        email=f"other_{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("OtherPassword123!"),
        role=UserRole.CUSTOMER,
        is_active=True,
    )
    db_session.add(other_user)
    await db_session.flush()

    other_customer = Customer(user_id=other_user.id, full_name="Other Customer")
    db_session.add(other_customer)
    await db_session.flush()

    await _seed_ticket(db_session, other_customer.id, title="Someone else's ticket")
    await db_session.commit()

    # List tickets for the original customer
    response = await client.get(
        "/api/v1/tickets", headers=test_customer_user["headers"]
    )
    assert response.status_code == 200
    data = response.json()

    # Every ticket in the response must belong to the test customer
    for ticket in data["tickets"]:
        assert ticket["customer_id"] == str(test_customer_user["customer"].id)

    # The other customer's ticket must NOT appear
    titles = [t["title"] for t in data["tickets"]]
    assert "Someone else's ticket" not in titles


# ---------------------------------------------------------------------------
# 5. Agent Lists All Tickets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_lists_all_tickets(
    client: AsyncClient,
    db_session: AsyncSession,
    test_customer_user: dict,
    test_agent_user: dict,
):
    """Requirement 5: Agent/Admin sees all tickets across all customers."""
    # Create a ticket via API
    await client.post(
        "/api/v1/tickets",
        json={
            "title": "Ticket visible to agents",
            "description": "Agents should be able to see this ticket.",
        },
        headers=test_customer_user["headers"],
    )

    response = await client.get(
        "/api/v1/tickets", headers=test_agent_user["headers"]
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    assert len(data["tickets"]) >= 1


# ---------------------------------------------------------------------------
# 6. Customer Gets Own Ticket Detail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_customer_gets_own_ticket_detail(
    client: AsyncClient, test_customer_user: dict
):
    """Requirement 6: Customer can view detail of their own ticket."""
    # Create a ticket
    create_resp = await client.post(
        "/api/v1/tickets",
        json={
            "title": "Detail test ticket",
            "description": "This ticket exists to test the detail endpoint.",
        },
        headers=test_customer_user["headers"],
    )
    ticket_id = create_resp.json()["id"]

    # Get detail
    response = await client.get(
        f"/api/v1/tickets/{ticket_id}", headers=test_customer_user["headers"]
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == ticket_id
    assert data["title"] == "Detail test ticket"
    assert "messages" in data  # Detail includes messages


# ---------------------------------------------------------------------------
# 7. Customer Cannot Access Another Customer's Ticket
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_customer_cannot_access_others_ticket(
    client: AsyncClient,
    db_session: AsyncSession,
    test_customer_user: dict,
):
    """Requirement 7: IDOR protection — customer cannot view another's ticket."""
    from backend.app.core.security import hash_password
    from backend.app.models.user import User, UserRole

    # Create another customer with a ticket
    other_user = User(
        email=f"idor_{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("Password123!"),
        role=UserRole.CUSTOMER,
        is_active=True,
    )
    db_session.add(other_user)
    await db_session.flush()

    other_customer = Customer(user_id=other_user.id, full_name="IDOR Target")
    db_session.add(other_customer)
    await db_session.flush()

    other_ticket = await _seed_ticket(
        db_session, other_customer.id, title="Private ticket"
    )
    await db_session.commit()

    # Attempt to access with the original customer's token
    response = await client.get(
        f"/api/v1/tickets/{other_ticket.id}",
        headers=test_customer_user["headers"],
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# 8. Agent Gets Any Ticket Detail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_gets_any_ticket_detail(
    client: AsyncClient,
    test_customer_user: dict,
    test_agent_user: dict,
):
    """Requirement 8: Agent can view any ticket regardless of ownership."""
    create_resp = await client.post(
        "/api/v1/tickets",
        json={
            "title": "Agent cross-access test",
            "description": "Agent should be able to see this customer's ticket.",
        },
        headers=test_customer_user["headers"],
    )
    ticket_id = create_resp.json()["id"]

    response = await client.get(
        f"/api/v1/tickets/{ticket_id}", headers=test_agent_user["headers"]
    )
    assert response.status_code == 200
    assert response.json()["id"] == ticket_id


# ---------------------------------------------------------------------------
# 9. Agent Updates Ticket Status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_updates_ticket_status(
    client: AsyncClient,
    test_customer_user: dict,
    test_agent_user: dict,
):
    """Requirement 9: Agent can update ticket status via PATCH."""
    create_resp = await client.post(
        "/api/v1/tickets",
        json={
            "title": "Status update test",
            "description": "This ticket will have its status updated.",
        },
        headers=test_customer_user["headers"],
    )
    ticket_id = create_resp.json()["id"]

    # Update status from OPEN → IN_PROGRESS
    response = await client.patch(
        f"/api/v1/tickets/{ticket_id}",
        json={"status": "IN_PROGRESS"},
        headers=test_agent_user["headers"],
    )
    assert response.status_code == 200
    assert response.json()["status"] == "IN_PROGRESS"


# ---------------------------------------------------------------------------
# 10. Customer Cannot Update Ticket
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_customer_cannot_update_ticket(
    client: AsyncClient, test_customer_user: dict
):
    """Requirement 10: Customer role is forbidden from updating ticket metadata."""
    create_resp = await client.post(
        "/api/v1/tickets",
        json={
            "title": "Customer update attempt",
            "description": "Customer should not be able to update this ticket.",
        },
        headers=test_customer_user["headers"],
    )
    ticket_id = create_resp.json()["id"]

    response = await client.patch(
        f"/api/v1/tickets/{ticket_id}",
        json={"status": "IN_PROGRESS"},
        headers=test_customer_user["headers"],
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# 11. Invalid Status Transition Rejected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_status_transition_rejected(
    client: AsyncClient,
    test_customer_user: dict,
    test_agent_user: dict,
):
    """Requirement 11: Invalid status transitions return 409 Conflict."""
    create_resp = await client.post(
        "/api/v1/tickets",
        json={
            "title": "Transition test",
            "description": "This ticket will test invalid status transitions.",
        },
        headers=test_customer_user["headers"],
    )
    ticket_id = create_resp.json()["id"]

    # Close the ticket: OPEN → CLOSED
    await client.patch(
        f"/api/v1/tickets/{ticket_id}",
        json={"status": "CLOSED"},
        headers=test_agent_user["headers"],
    )

    # Attempt invalid: CLOSED → OPEN (CLOSED is terminal)
    response = await client.patch(
        f"/api/v1/tickets/{ticket_id}",
        json={"status": "OPEN"},
        headers=test_agent_user["headers"],
    )
    assert response.status_code == 409
    assert "Invalid status transition" in response.json()["detail"]


# ---------------------------------------------------------------------------
# 12. Customer Adds a Message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_customer_adds_message(
    client: AsyncClient, test_customer_user: dict
):
    """Requirement 12: Customer can add a message; sender_type set server-side."""
    create_resp = await client.post(
        "/api/v1/tickets",
        json={
            "title": "Messaging test",
            "description": "This ticket exists to test messaging.",
        },
        headers=test_customer_user["headers"],
    )
    ticket_id = create_resp.json()["id"]

    response = await client.post(
        f"/api/v1/tickets/{ticket_id}/messages",
        json={"content": "Hello, I need help with my order."},
        headers=test_customer_user["headers"],
    )
    assert response.status_code == 201
    data = response.json()
    assert data["content"] == "Hello, I need help with my order."
    assert data["sender_type"] == "CUSTOMER"
    assert data["is_internal_note"] is False
    assert data["sender_id"] == str(test_customer_user["user"].id)


# ---------------------------------------------------------------------------
# 13. Agent Adds a Message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_adds_message(
    client: AsyncClient,
    test_customer_user: dict,
    test_agent_user: dict,
):
    """Requirement 13: Agent can add a message; sender_type=AGENT set server-side."""
    create_resp = await client.post(
        "/api/v1/tickets",
        json={
            "title": "Agent messaging test",
            "description": "Ticket for testing agent messaging.",
        },
        headers=test_customer_user["headers"],
    )
    ticket_id = create_resp.json()["id"]

    response = await client.post(
        f"/api/v1/tickets/{ticket_id}/messages",
        json={"content": "Thank you for reaching out. Let me look into this."},
        headers=test_agent_user["headers"],
    )
    assert response.status_code == 201
    data = response.json()
    assert data["sender_type"] == "AGENT"


# ---------------------------------------------------------------------------
# 14. Agent Adds Internal Note
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_adds_internal_note(
    client: AsyncClient,
    test_customer_user: dict,
    test_agent_user: dict,
):
    """Requirement 14: Agent can create internal notes (is_internal_note=True)."""
    create_resp = await client.post(
        "/api/v1/tickets",
        json={
            "title": "Internal note test",
            "description": "Ticket for testing internal notes.",
        },
        headers=test_customer_user["headers"],
    )
    ticket_id = create_resp.json()["id"]

    response = await client.post(
        f"/api/v1/tickets/{ticket_id}/messages",
        json={
            "content": "Internal: Customer has history of escalations.",
            "is_internal_note": True,
        },
        headers=test_agent_user["headers"],
    )
    assert response.status_code == 201
    assert response.json()["is_internal_note"] is True


# ---------------------------------------------------------------------------
# 15. Customer Cannot See Internal Notes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_customer_cannot_see_internal_notes(
    client: AsyncClient,
    test_customer_user: dict,
    test_agent_user: dict,
):
    """Requirement 15: Internal notes are filtered from CUSTOMER responses."""
    create_resp = await client.post(
        "/api/v1/tickets",
        json={
            "title": "Note visibility test",
            "description": "Ticket for testing internal note visibility.",
        },
        headers=test_customer_user["headers"],
    )
    ticket_id = create_resp.json()["id"]

    # Customer adds a normal message
    await client.post(
        f"/api/v1/tickets/{ticket_id}/messages",
        json={"content": "Customer visible message"},
        headers=test_customer_user["headers"],
    )

    # Agent adds an internal note
    await client.post(
        f"/api/v1/tickets/{ticket_id}/messages",
        json={"content": "Secret agent note", "is_internal_note": True},
        headers=test_agent_user["headers"],
    )

    # Customer lists messages — internal note should be hidden
    response = await client.get(
        f"/api/v1/tickets/{ticket_id}/messages",
        headers=test_customer_user["headers"],
    )
    assert response.status_code == 200
    messages = response.json()

    for msg in messages:
        assert msg["is_internal_note"] is False
    assert any(m["content"] == "Customer visible message" for m in messages)
    assert not any(m["content"] == "Secret agent note" for m in messages)

    # Agent lists messages — can see internal notes
    agent_response = await client.get(
        f"/api/v1/tickets/{ticket_id}/messages",
        headers=test_agent_user["headers"],
    )
    agent_messages = agent_response.json()
    assert any(m["content"] == "Secret agent note" for m in agent_messages)


# ---------------------------------------------------------------------------
# 16. Customer Cannot Create Internal Notes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_customer_cannot_create_internal_notes(
    client: AsyncClient, test_customer_user: dict
):
    """Requirement 16: Customer is forbidden from creating internal notes."""
    create_resp = await client.post(
        "/api/v1/tickets",
        json={
            "title": "Customer internal note attempt",
            "description": "Customer tries to create an internal note.",
        },
        headers=test_customer_user["headers"],
    )
    ticket_id = create_resp.json()["id"]

    response = await client.post(
        f"/api/v1/tickets/{ticket_id}/messages",
        json={"content": "I am pretending to be internal.", "is_internal_note": True},
        headers=test_customer_user["headers"],
    )
    assert response.status_code == 403
    assert "internal notes" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 17. Agent Assigns Ticket
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_assigns_ticket(
    client: AsyncClient,
    test_customer_user: dict,
    test_agent_user: dict,
):
    """Requirement 17: Agent can assign a ticket to another agent."""
    create_resp = await client.post(
        "/api/v1/tickets",
        json={
            "title": "Assignment test ticket",
            "description": "Ticket for testing agent assignment.",
        },
        headers=test_customer_user["headers"],
    )
    ticket_id = create_resp.json()["id"]

    response = await client.post(
        f"/api/v1/tickets/{ticket_id}/assign",
        json={"agent_id": str(test_agent_user["user"].id)},
        headers=test_agent_user["headers"],
    )
    assert response.status_code == 200
    assert response.json()["assigned_agent_id"] == str(test_agent_user["user"].id)


# ---------------------------------------------------------------------------
# 18. Customer Cannot Assign Tickets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_customer_cannot_assign_tickets(
    client: AsyncClient, test_customer_user: dict
):
    """Requirement 18: Customer role cannot assign agents to tickets."""
    create_resp = await client.post(
        "/api/v1/tickets",
        json={
            "title": "Customer assign attempt",
            "description": "Customer tries to assign an agent — should fail.",
        },
        headers=test_customer_user["headers"],
    )
    ticket_id = create_resp.json()["id"]

    response = await client.post(
        f"/api/v1/tickets/{ticket_id}/assign",
        json={"agent_id": str(uuid.uuid4())},
        headers=test_customer_user["headers"],
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# 19. Pagination Works
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pagination_works(
    client: AsyncClient, test_customer_user: dict
):
    """Requirement 19: Pagination offset/limit are respected."""
    # Create multiple tickets
    for i in range(5):
        await client.post(
            "/api/v1/tickets",
            json={
                "title": f"Pagination test ticket {i}",
                "description": f"Ticket {i} for pagination test, long enough description.",
            },
            headers=test_customer_user["headers"],
        )

    # Request page with limit=2
    response = await client.get(
        "/api/v1/tickets?limit=2&offset=0",
        headers=test_customer_user["headers"],
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["tickets"]) == 2
    assert data["limit"] == 2
    assert data["offset"] == 0
    assert data["total"] >= 5

    # Request second page
    response2 = await client.get(
        "/api/v1/tickets?limit=2&offset=2",
        headers=test_customer_user["headers"],
    )
    data2 = response2.json()
    assert len(data2["tickets"]) == 2
    assert data2["offset"] == 2

    # Ensure pages don't overlap
    page1_ids = {t["id"] for t in data["tickets"]}
    page2_ids = {t["id"] for t in data2["tickets"]}
    assert page1_ids.isdisjoint(page2_ids)


# ---------------------------------------------------------------------------
# 20. Status Filter Works
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_filter_works(
    client: AsyncClient,
    test_customer_user: dict,
    test_agent_user: dict,
):
    """Requirement 20: Status filter returns only matching tickets."""
    # Create two tickets
    r1 = await client.post(
        "/api/v1/tickets",
        json={
            "title": "Open ticket for filter",
            "description": "This ticket stays open for filter testing.",
        },
        headers=test_customer_user["headers"],
    )
    r2 = await client.post(
        "/api/v1/tickets",
        json={
            "title": "Closed ticket for filter",
            "description": "This ticket will be closed for filter testing.",
        },
        headers=test_customer_user["headers"],
    )
    ticket_id_2 = r2.json()["id"]

    # Close the second ticket
    await client.patch(
        f"/api/v1/tickets/{ticket_id_2}",
        json={"status": "CLOSED"},
        headers=test_agent_user["headers"],
    )

    # Filter by CLOSED status
    response = await client.get(
        "/api/v1/tickets?status=CLOSED",
        headers=test_customer_user["headers"],
    )
    assert response.status_code == 200
    data = response.json()
    for ticket in data["tickets"]:
        assert ticket["status"] == "CLOSED"


# ---------------------------------------------------------------------------
# 21. IDOR: Customer B Cannot POST Message to Customer A's Ticket
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_customer_cannot_post_message_to_others_ticket(
    client: AsyncClient,
    db_session: AsyncSession,
    test_customer_user: dict,
):
    """Requirement 21: IDOR protection — Customer B cannot post messages to Customer A's ticket."""
    # Customer A is test_customer_user
    customer_a = test_customer_user

    # Create Customer B with distinct credentials
    customer_b = await _create_customer_user(
        db_session, email_prefix="customer_b", full_name="Customer B"
    )

    # Create Ticket owned by Customer A
    create_resp = await client.post(
        "/api/v1/tickets",
        json={
            "title": "Customer A Private Ticket",
            "description": "Sensitive inquiry submitted by Customer A.",
        },
        headers=customer_a["headers"],
    )
    assert create_resp.status_code == 201
    customer_a_ticket_id = create_resp.json()["id"]

    # Customer B attempts to POST a message to Customer A's ticket
    message_payload = {
        "content": "Malicious message injection from unauthorized Customer B.",
        "is_internal_note": False,
    }
    response = await client.post(
        f"/api/v1/tickets/{customer_a_ticket_id}/messages",
        json=message_payload,
        headers=customer_b["headers"],
    )

    # Expected: 403 Forbidden
    assert response.status_code == 403
    assert "not own this resource" in response.json()["detail"].lower()

    # Verify: No message was created on Customer A's ticket
    msg_result = await db_session.execute(
        select(TicketMessage).where(
            TicketMessage.ticket_id == uuid.UUID(customer_a_ticket_id)
        )
    )
    messages = msg_result.scalars().all()
    assert len(messages) == 0

    # Verify: The ticket still belongs to Customer A
    ticket_result = await db_session.execute(
        select(Ticket).where(Ticket.id == uuid.UUID(customer_a_ticket_id))
    )
    persisted_ticket = ticket_result.scalar_one()
    assert persisted_ticket.customer_id == customer_a["customer"].id

    # Verify: Customer B cannot modify Customer A's ticket through the message endpoint
    assert persisted_ticket.status == TicketStatus.OPEN
    assert persisted_ticket.assigned_agent_id is None


# ---------------------------------------------------------------------------
# 22. IDOR: Customer B Cannot GET Messages from Customer A's Ticket
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_customer_cannot_get_messages_from_others_ticket(
    client: AsyncClient,
    db_session: AsyncSession,
    test_customer_user: dict,
):
    """Requirement 22: IDOR protection — Customer B cannot view messages from Customer A's ticket."""
    # Customer A is test_customer_user
    customer_a = test_customer_user

    # Create Customer B with distinct credentials
    customer_b = await _create_customer_user(
        db_session, email_prefix="customer_b", full_name="Customer B"
    )

    # Create Ticket owned by Customer A
    create_resp = await client.post(
        "/api/v1/tickets",
        json={
            "title": "Customer A Confidential Thread",
            "description": "Customer A discussing sensitive billing issues.",
        },
        headers=customer_a["headers"],
    )
    assert create_resp.status_code == 201
    customer_a_ticket_id = create_resp.json()["id"]

    # Customer A adds at least one message to that ticket
    secret_content = "Confidential billing details shared by Customer A."
    add_msg_resp = await client.post(
        f"/api/v1/tickets/{customer_a_ticket_id}/messages",
        json={"content": secret_content},
        headers=customer_a["headers"],
    )
    assert add_msg_resp.status_code == 201

    # Customer B attempts to GET messages from Customer A's ticket
    response = await client.get(
        f"/api/v1/tickets/{customer_a_ticket_id}/messages",
        headers=customer_b["headers"],
    )

    # Expected: 403 Forbidden
    assert response.status_code == 403
    assert "not own this resource" in response.json()["detail"].lower()

    # Verify: Customer B receives no messages
    assert secret_content not in response.text
    data = response.json()
    assert "detail" in data
    assert not isinstance(data, list)
