"""Phase 15 — Integration tests: Ticket lifecycle end-to-end journeys.

These tests exercise the complete ticket lifecycle from creation through all
status transitions, verifying both the HTTP API layer and the database state
layer together. They confirm that status machine invariants are enforced at
every stage of a ticket's journey.

Journeys:
  1.  Customer creates ticket → status is OPEN → DB state verified.
  2.  Agent moves ticket: OPEN → IN_PROGRESS → DB state verified.
  3.  Agent moves ticket: IN_PROGRESS → RESOLVED → DB state verified.
  4.  Agent closes ticket: OPEN → CLOSED → terminal state enforced.
  5.  Agent cannot skip to RESOLVED from OPEN in one jump (invalid transition).
  6.  Customer adds message → message persisted in DB with correct sender_type.
  7.  Agent adds internal note → hidden from customer GET, visible to agent.
  8.  Customer B cannot read or write to Customer A's ticket (cross-tenant IDOR).
  9.  Assign → reassign → ticket reflects latest agent_id.
  10. CLOSED ticket rejects all status transitions (terminal state).
  11. Pagination cursor consistency: no duplicates across pages.
  12. Status filter + pagination: filtered count ≤ total count.
"""

import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.security import hash_password, create_access_token
from backend.app.core.config import settings
from backend.app.models.ticket import SenderType, Ticket, TicketMessage, TicketStatus
from backend.app.models.user import Customer, User, UserRole


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_customer(db: AsyncSession) -> dict:
    """Create a fresh customer user + Customer profile with auth token."""
    uid = uuid.uuid4().hex[:8]
    user = User(
        email=f"cust_{uid}@example.com",
        hashed_password=hash_password("Passw0rd!"),
        role=UserRole.CUSTOMER,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    customer = Customer(user_id=user.id, full_name=f"Integration Customer {uid}")
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
        "headers": {"Authorization": f"Bearer {token}"},
    }


async def _create_ticket_via_api(client: AsyncClient, headers: dict, *, title: str = "Integration Test Ticket") -> dict:
    """Create a ticket via POST /api/v1/tickets and return parsed JSON."""
    resp = await client.post(
        "/api/v1/tickets",
        json={"title": title, "description": "End-to-end integration ticket description."},
        headers=headers,
    )
    assert resp.status_code == 201, f"Ticket creation failed: {resp.text}"
    return resp.json()


# ---------------------------------------------------------------------------
# 1. Customer creates ticket → DB state verified
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ticket_creation_persisted_in_db(
    client: AsyncClient,
    db_session: AsyncSession,
    test_customer_user: dict,
):
    """Journey 1: Created ticket is persisted to DB with correct initial state."""
    data = await _create_ticket_via_api(client, test_customer_user["headers"])
    ticket_id = uuid.UUID(data["id"])

    # Directly query the database to confirm persistence
    result = await db_session.execute(select(Ticket).where(Ticket.id == ticket_id))
    db_ticket = result.scalar_one_or_none()

    assert db_ticket is not None, "Ticket was not persisted in the database"
    assert db_ticket.status == TicketStatus.OPEN
    assert db_ticket.customer_id == test_customer_user["customer"].id
    assert db_ticket.ticket_number.startswith("TKT-")
    assert db_ticket.assigned_agent_id is None


# ---------------------------------------------------------------------------
# 2. OPEN → IN_PROGRESS
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ticket_open_to_in_progress(
    client: AsyncClient,
    db_session: AsyncSession,
    test_customer_user: dict,
    test_agent_user: dict,
):
    """Journey 2: Agent transitions OPEN → IN_PROGRESS; DB reflects new status."""
    data = await _create_ticket_via_api(client, test_customer_user["headers"])
    ticket_id = data["id"]

    patch_resp = await client.patch(
        f"/api/v1/tickets/{ticket_id}",
        json={"status": "IN_PROGRESS"},
        headers=test_agent_user["headers"],
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["status"] == "IN_PROGRESS"

    # Verify in DB
    result = await db_session.execute(select(Ticket).where(Ticket.id == uuid.UUID(ticket_id)))
    db_ticket = result.scalar_one()
    assert db_ticket.status == TicketStatus.IN_PROGRESS


# ---------------------------------------------------------------------------
# 3. IN_PROGRESS → RESOLVED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ticket_in_progress_to_resolved(
    client: AsyncClient,
    db_session: AsyncSession,
    test_customer_user: dict,
    test_agent_user: dict,
):
    """Journey 3: Agent transitions IN_PROGRESS → RESOLVED; DB reflects final state."""
    data = await _create_ticket_via_api(client, test_customer_user["headers"])
    ticket_id = data["id"]
    agent_headers = test_agent_user["headers"]

    # OPEN → IN_PROGRESS
    await client.patch(
        f"/api/v1/tickets/{ticket_id}",
        json={"status": "IN_PROGRESS"},
        headers=agent_headers,
    )

    # IN_PROGRESS → RESOLVED
    resolve_resp = await client.patch(
        f"/api/v1/tickets/{ticket_id}",
        json={"status": "RESOLVED"},
        headers=agent_headers,
    )
    assert resolve_resp.status_code == 200
    assert resolve_resp.json()["status"] == "RESOLVED"

    result = await db_session.execute(select(Ticket).where(Ticket.id == uuid.UUID(ticket_id)))
    db_ticket = result.scalar_one()
    assert db_ticket.status == TicketStatus.RESOLVED


# ---------------------------------------------------------------------------
# 4. OPEN → CLOSED (direct terminal transition)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ticket_open_to_closed(
    client: AsyncClient,
    db_session: AsyncSession,
    test_customer_user: dict,
    test_agent_user: dict,
):
    """Journey 4: Agent closes ticket from OPEN; ticket enters terminal CLOSED state."""
    data = await _create_ticket_via_api(client, test_customer_user["headers"])
    ticket_id = data["id"]

    close_resp = await client.patch(
        f"/api/v1/tickets/{ticket_id}",
        json={"status": "CLOSED"},
        headers=test_agent_user["headers"],
    )
    assert close_resp.status_code == 200
    assert close_resp.json()["status"] == "CLOSED"

    result = await db_session.execute(select(Ticket).where(Ticket.id == uuid.UUID(ticket_id)))
    db_ticket = result.scalar_one()
    assert db_ticket.status == TicketStatus.CLOSED


# ---------------------------------------------------------------------------
# 5. Invalid transition OPEN → RESOLVED is rejected with 409
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_transition_open_to_resolved(
    client: AsyncClient,
    test_customer_user: dict,
    test_agent_user: dict,
):
    """Journey 5: OPEN → RESOLVED (skipping IN_PROGRESS) returns 409 Conflict."""
    data = await _create_ticket_via_api(client, test_customer_user["headers"])
    ticket_id = data["id"]

    resp = await client.patch(
        f"/api/v1/tickets/{ticket_id}",
        json={"status": "RESOLVED"},
        headers=test_agent_user["headers"],
    )
    assert resp.status_code == 409
    assert "invalid status transition" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 6. Customer message persisted in DB with correct sender_type
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_customer_message_persisted_in_db(
    client: AsyncClient,
    db_session: AsyncSession,
    test_customer_user: dict,
):
    """Journey 6: Customer message is persisted with sender_type=CUSTOMER."""
    data = await _create_ticket_via_api(client, test_customer_user["headers"])
    ticket_id = data["id"]

    msg_resp = await client.post(
        f"/api/v1/tickets/{ticket_id}/messages",
        json={"content": "I need help with my billing statement."},
        headers=test_customer_user["headers"],
    )
    assert msg_resp.status_code == 201

    msg_id = uuid.UUID(msg_resp.json()["id"])
    result = await db_session.execute(
        select(TicketMessage).where(TicketMessage.id == msg_id)
    )
    db_msg = result.scalar_one_or_none()
    assert db_msg is not None
    assert db_msg.sender_type == SenderType.CUSTOMER
    assert db_msg.is_internal_note is False
    assert db_msg.content == "I need help with my billing statement."


# ---------------------------------------------------------------------------
# 7. Internal note visible to agent, hidden from customer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_internal_note_visibility_integrity(
    client: AsyncClient,
    db_session: AsyncSession,
    test_customer_user: dict,
    test_agent_user: dict,
):
    """Journey 7: Internal note is hidden from customer in messages list but visible to agent."""
    data = await _create_ticket_via_api(client, test_customer_user["headers"])
    ticket_id = data["id"]

    # Agent adds internal note
    note_resp = await client.post(
        f"/api/v1/tickets/{ticket_id}/messages",
        json={"content": "INTERNAL: Flag for billing team review.", "is_internal_note": True},
        headers=test_agent_user["headers"],
    )
    assert note_resp.status_code == 201
    note_id = uuid.UUID(note_resp.json()["id"])

    # Verify in DB: is_internal_note=True, sender_type=AGENT
    result = await db_session.execute(
        select(TicketMessage).where(TicketMessage.id == note_id)
    )
    db_note = result.scalar_one()
    assert db_note.is_internal_note is True
    assert db_note.sender_type == SenderType.AGENT

    # Customer lists messages — note must NOT appear
    cust_resp = await client.get(
        f"/api/v1/tickets/{ticket_id}/messages",
        headers=test_customer_user["headers"],
    )
    assert cust_resp.status_code == 200
    customer_messages = cust_resp.json()
    assert all(m["is_internal_note"] is False for m in customer_messages)
    assert all(m["content"] != "INTERNAL: Flag for billing team review." for m in customer_messages)

    # Agent lists messages — note MUST appear
    agent_resp = await client.get(
        f"/api/v1/tickets/{ticket_id}/messages",
        headers=test_agent_user["headers"],
    )
    agent_messages = agent_resp.json()
    internal_notes = [m for m in agent_messages if m["is_internal_note"]]
    assert any(n["content"] == "INTERNAL: Flag for billing team review." for n in internal_notes)


# ---------------------------------------------------------------------------
# 8. Cross-tenant IDOR: Customer B cannot read/write Customer A's ticket
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_tenant_idor_protection(
    client: AsyncClient,
    db_session: AsyncSession,
    test_customer_user: dict,
):
    """Journey 8: Customer B cannot read or write to Customer A's ticket."""
    customer_b = await _create_customer(db_session)

    # Customer A creates ticket
    data = await _create_ticket_via_api(client, test_customer_user["headers"], title="Customer A Private Ticket")
    ticket_id = data["id"]

    # Customer B attempts to GET ticket detail
    get_resp = await client.get(
        f"/api/v1/tickets/{ticket_id}",
        headers=customer_b["headers"],
    )
    assert get_resp.status_code == 403, "Customer B should not see Customer A's ticket"

    # Customer B attempts to GET messages
    msg_get_resp = await client.get(
        f"/api/v1/tickets/{ticket_id}/messages",
        headers=customer_b["headers"],
    )
    assert msg_get_resp.status_code == 403, "Customer B should not see Customer A's messages"

    # Customer B attempts to POST a message
    msg_post_resp = await client.post(
        f"/api/v1/tickets/{ticket_id}/messages",
        json={"content": "Injected message from Customer B"},
        headers=customer_b["headers"],
    )
    assert msg_post_resp.status_code == 403, "Customer B should not post to Customer A's ticket"

    # Verify: No messages were injected into the DB
    result = await db_session.execute(
        select(TicketMessage).where(
            TicketMessage.ticket_id == uuid.UUID(ticket_id)
        )
    )
    messages = result.scalars().all()
    assert all(m.content != "Injected message from Customer B" for m in messages)


# ---------------------------------------------------------------------------
# 9. Assign → reassign → ticket reflects latest agent_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ticket_reassignment(
    client: AsyncClient,
    db_session: AsyncSession,
    test_customer_user: dict,
    test_agent_user: dict,
):
    """Journey 9: Ticket can be reassigned; DB always reflects the latest agent."""
    data = await _create_ticket_via_api(client, test_customer_user["headers"])
    ticket_id = data["id"]
    agent_id = str(test_agent_user["user"].id)

    # Assign to agent
    assign_resp = await client.post(
        f"/api/v1/tickets/{ticket_id}/assign",
        json={"agent_id": agent_id},
        headers=test_agent_user["headers"],
    )
    assert assign_resp.status_code == 200
    assert assign_resp.json()["assigned_agent_id"] == agent_id

    # Verify in DB
    result = await db_session.execute(select(Ticket).where(Ticket.id == uuid.UUID(ticket_id)))
    db_ticket = result.scalar_one()
    assert str(db_ticket.assigned_agent_id) == agent_id

    # Create a second agent and reassign
    second_agent = await _create_customer(db_session)
    # Make them an agent via DB
    second_agent["user"].role = UserRole.SUPPORT_AGENT
    db_session.add(second_agent["user"])
    await db_session.commit()
    await db_session.refresh(second_agent["user"])

    second_token = create_access_token(
        user_id=str(second_agent["user"].id),
        secret_key=settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
        expires_minutes=60,
    )
    second_agent_headers = {"Authorization": f"Bearer {second_token}"}

    reassign_resp = await client.post(
        f"/api/v1/tickets/{ticket_id}/assign",
        json={"agent_id": str(second_agent["user"].id)},
        headers=second_agent_headers,
    )
    assert reassign_resp.status_code == 200
    assert reassign_resp.json()["assigned_agent_id"] == str(second_agent["user"].id)


# ---------------------------------------------------------------------------
# 10. CLOSED ticket rejects all status transitions (terminal state)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_closed_ticket_rejects_all_transitions(
    client: AsyncClient,
    test_customer_user: dict,
    test_agent_user: dict,
):
    """Journey 10: CLOSED is a terminal state — all transition attempts return 409."""
    data = await _create_ticket_via_api(client, test_customer_user["headers"])
    ticket_id = data["id"]
    agent_headers = test_agent_user["headers"]

    # Close the ticket
    await client.patch(
        f"/api/v1/tickets/{ticket_id}",
        json={"status": "CLOSED"},
        headers=agent_headers,
    )

    # Attempt any transition from CLOSED
    for target_status in ["OPEN", "IN_PROGRESS", "RESOLVED", "PENDING_AGENT_REVIEW"]:
        resp = await client.patch(
            f"/api/v1/tickets/{ticket_id}",
            json={"status": target_status},
            headers=agent_headers,
        )
        assert resp.status_code == 409, f"Expected 409 for CLOSED → {target_status}, got {resp.status_code}"


# ---------------------------------------------------------------------------
# 11. Pagination cursor consistency — no duplicates across pages
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pagination_no_duplicates(
    client: AsyncClient,
    test_customer_user: dict,
):
    """Journey 11: No ticket appears in multiple pages simultaneously."""
    # Create 6 tickets
    for i in range(6):
        await _create_ticket_via_api(
            client,
            test_customer_user["headers"],
            title=f"Pagination Journey Ticket {i}",
        )

    page1 = await client.get(
        "/api/v1/tickets?limit=3&offset=0",
        headers=test_customer_user["headers"],
    )
    page2 = await client.get(
        "/api/v1/tickets?limit=3&offset=3",
        headers=test_customer_user["headers"],
    )

    assert page1.status_code == 200
    assert page2.status_code == 200

    ids_p1 = {t["id"] for t in page1.json()["tickets"]}
    ids_p2 = {t["id"] for t in page2.json()["tickets"]}
    assert ids_p1.isdisjoint(ids_p2), "Duplicate tickets found across paginated pages"


# ---------------------------------------------------------------------------
# 12. Status filter + pagination: filtered count ≤ total count
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_filter_count_consistency(
    client: AsyncClient,
    test_customer_user: dict,
    test_agent_user: dict,
):
    """Journey 12: Filtered total for a specific status is ≤ unfiltered total."""
    # Create and close one ticket
    data = await _create_ticket_via_api(client, test_customer_user["headers"], title="Status Filter Consistency")
    ticket_id = data["id"]
    await client.patch(
        f"/api/v1/tickets/{ticket_id}",
        json={"status": "CLOSED"},
        headers=test_agent_user["headers"],
    )

    # Get total (no filter)
    all_resp = await client.get("/api/v1/tickets", headers=test_agent_user["headers"])
    total = all_resp.json()["total"]

    # Get filtered total (CLOSED only)
    closed_resp = await client.get(
        "/api/v1/tickets?status=CLOSED",
        headers=test_agent_user["headers"],
    )
    closed_total = closed_resp.json()["total"]

    assert closed_total <= total
    assert closed_total >= 1  # We just closed one
    for ticket in closed_resp.json()["tickets"]:
        assert ticket["status"] == "CLOSED"
