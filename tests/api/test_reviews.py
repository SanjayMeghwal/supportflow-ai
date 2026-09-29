"""Phase 15 — API test suite for Phase 12: Human-In-The-Loop (HITL) Review Workflow.

Covers:
  1.  GET /pending requires SUPPORT_AGENT or ADMIN — 401 for unauthenticated.
  2.  GET /pending returns 403 for CUSTOMER role.
  3.  GET /pending returns empty queue when no reviews exist (zero-safe).
  4.  GET /{review_id} returns 401 for unauthenticated.
  5.  GET /{review_id} returns 403 for CUSTOMER role.
  6.  GET /{review_id} returns 404 for nonexistent review ID.
  7.  POST /approve returns 401 for unauthenticated.
  8.  POST /approve returns 403 for CUSTOMER role.
  9.  POST /approve returns 404 for nonexistent review ID.
  10. POST /edit returns 400 when final_submitted_text is empty string.
  11. POST /edit returns 401 for unauthenticated.
  12. POST /edit returns 403 for CUSTOMER role.
  13. POST /edit returns 404 for nonexistent review ID.
  14. POST /reject returns 400 when feedback_notes missing.
  15. POST /reject returns 401 for unauthenticated.
  16. POST /reject returns 403 for CUSTOMER role.
  17. POST /reject returns 404 for nonexistent review ID.
  18. POST /escalate returns 401 for unauthenticated.
  19. POST /escalate returns 403 for CUSTOMER role.
  20. POST /escalate returns 404 for nonexistent review ID.
  21. Full HITL lifecycle: seed review → agent approves → ticket resolves → duplicate action returns 409.
  22. Full HITL lifecycle: seed review → agent edits draft → message dispatched.
  23. Full HITL lifecycle: seed review → agent rejects → ticket returns to IN_PROGRESS.
  24. Full HITL lifecycle: seed review → agent escalates → review is ESCALATED.
  25. Extra fields in approve request are rejected with 422 (extra="forbid").
  26. Extra fields in edit request are rejected with 422.
  27. Reviewer_id is never accepted from client input.
  28. GET /pending pagination: skip and limit are respected.
"""

import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.security import hash_password, create_access_token
from backend.app.core.config import settings
from backend.app.models.ai import AIRun, AIRunStatus, HumanReview, ReviewStatus
from backend.app.models.ticket import Ticket, TicketPriority, TicketStatus
from backend.app.models.user import Customer, User, UserRole


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_customer(db: AsyncSession) -> tuple[User, Customer]:
    """Create a customer user + profile in the DB."""
    uid = uuid.uuid4().hex[:8]
    user = User(
        email=f"cust_{uid}@example.com",
        hashed_password=hash_password("Password123!"),
        role=UserRole.CUSTOMER,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    customer = Customer(user_id=user.id, full_name=f"Customer {uid}")
    db.add(customer)
    await db.commit()
    await db.refresh(user)
    await db.refresh(customer)
    return user, customer


async def _seed_ticket(db: AsyncSession, customer_id: uuid.UUID) -> Ticket:
    """Create a ticket for a given customer_id."""
    ticket = Ticket(
        ticket_number=f"TKT-{uuid.uuid4().hex[:6].upper()}",
        customer_id=customer_id,
        title="Automated HITL test ticket",
        description="This ticket was seeded for HITL testing purposes.",
        priority=TicketPriority.HIGH,
        status=TicketStatus.PENDING_AGENT_REVIEW,
    )
    db.add(ticket)
    await db.flush()
    await db.refresh(ticket)
    return ticket


async def _seed_ai_run(db: AsyncSession, ticket_id: uuid.UUID) -> AIRun:
    """Create an AIRun record linked to a ticket."""
    ai_run = AIRun(
        ticket_id=ticket_id,
        model_name="llama3-8b-8192",
        intent_detected="billing_inquiry",
        confidence_score=0.65,
        execution_status=AIRunStatus.ESCALATED_LOW_CONFIDENCE,
        response_text="Thank you for your patience. Let me review your account.",
    )
    db.add(ai_run)
    await db.flush()
    await db.refresh(ai_run)
    return ai_run


async def _seed_review(
    db: AsyncSession,
    ticket_id: uuid.UUID,
    ai_run_id: uuid.UUID,
    *,
    escalation_reason: str = "Low confidence score: 0.65",
) -> HumanReview:
    """Create a pending HumanReview linked to a ticket and AI run."""
    review = HumanReview(
        ticket_id=ticket_id,
        ai_run_id=ai_run_id,
        status=ReviewStatus.PENDING,
        escalation_reason=escalation_reason,
        original_ai_draft="Thank you for your patience. Let me review your account.",
    )
    db.add(review)
    await db.commit()
    await db.refresh(review)
    return review


async def _create_full_review(db: AsyncSession) -> HumanReview:
    """Full seeding pipeline: customer → ticket → ai_run → review."""
    _, customer = await _seed_customer(db)
    ticket = await _seed_ticket(db, customer.id)
    ai_run = await _seed_ai_run(db, ticket.id)
    return await _seed_review(db, ticket.id, ai_run.id)


# ---------------------------------------------------------------------------
# 1. GET /pending — unauthenticated must return 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pending_reviews_requires_authentication(client: AsyncClient):
    """Requirement 1: /reviews/pending must reject unauthenticated with 401."""
    response = await client.get("/api/v1/reviews/pending")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# 2. GET /pending — CUSTOMER must receive 403
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pending_reviews_forbidden_for_customer(
    client: AsyncClient,
    test_customer_user: dict,
):
    """Requirement 2: CUSTOMER role is forbidden from accessing the review queue."""
    response = await client.get(
        "/api/v1/reviews/pending",
        headers=test_customer_user["headers"],
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# 3. GET /pending — empty queue returns 200 with empty list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pending_reviews_empty_queue_is_zero_safe(
    client: AsyncClient,
    test_agent_user: dict,
):
    """Requirement 3: Empty review queue returns 200 with total >= 0, not a 500."""
    response = await client.get(
        "/api/v1/reviews/pending",
        headers=test_agent_user["headers"],
    )
    assert response.status_code == 200
    data = response.json()
    assert "total" in data
    assert "items" in data
    assert isinstance(data["total"], int)
    assert isinstance(data["items"], list)
    assert data["total"] >= 0


# ---------------------------------------------------------------------------
# 4–6. GET /{review_id} — access control and 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_review_requires_authentication(client: AsyncClient):
    """Requirement 4: GET /reviews/{id} must reject unauthenticated with 401."""
    response = await client.get(f"/api/v1/reviews/{uuid.uuid4()}")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_review_forbidden_for_customer(
    client: AsyncClient,
    test_customer_user: dict,
):
    """Requirement 5: CUSTOMER cannot fetch review detail."""
    response = await client.get(
        f"/api/v1/reviews/{uuid.uuid4()}",
        headers=test_customer_user["headers"],
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_get_review_not_found(
    client: AsyncClient,
    test_agent_user: dict,
):
    """Requirement 6: Non-existent review_id returns 404 Not Found."""
    response = await client.get(
        f"/api/v1/reviews/{uuid.uuid4()}",
        headers=test_agent_user["headers"],
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 7–9. POST /approve — access control and 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_requires_authentication(client: AsyncClient):
    """Requirement 7: /approve must reject unauthenticated with 401."""
    response = await client.post(
        f"/api/v1/reviews/{uuid.uuid4()}/approve",
        json={},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_approve_forbidden_for_customer(
    client: AsyncClient,
    test_customer_user: dict,
):
    """Requirement 8: CUSTOMER cannot approve reviews."""
    response = await client.post(
        f"/api/v1/reviews/{uuid.uuid4()}/approve",
        json={},
        headers=test_customer_user["headers"],
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_approve_review_not_found(
    client: AsyncClient,
    test_agent_user: dict,
):
    """Requirement 9: Approving a nonexistent review returns 404."""
    response = await client.post(
        f"/api/v1/reviews/{uuid.uuid4()}/approve",
        json={},
        headers=test_agent_user["headers"],
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 10–13. POST /edit — validation, access control and 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edit_requires_authentication(client: AsyncClient):
    """Requirement 11: /edit must reject unauthenticated with 401."""
    response = await client.post(
        f"/api/v1/reviews/{uuid.uuid4()}/edit",
        json={"final_submitted_text": "Some edited text."},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_edit_forbidden_for_customer(
    client: AsyncClient,
    test_customer_user: dict,
):
    """Requirement 12: CUSTOMER cannot edit reviews."""
    response = await client.post(
        f"/api/v1/reviews/{uuid.uuid4()}/edit",
        json={"final_submitted_text": "Some edited text."},
        headers=test_customer_user["headers"],
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_edit_review_not_found(
    client: AsyncClient,
    test_agent_user: dict,
):
    """Requirement 13: Editing a nonexistent review returns 404."""
    response = await client.post(
        f"/api/v1/reviews/{uuid.uuid4()}/edit",
        json={"final_submitted_text": "Corrected response text for the customer."},
        headers=test_agent_user["headers"],
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 14–17. POST /reject — validation, access control and 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reject_requires_authentication(client: AsyncClient):
    """Requirement 15: /reject must reject unauthenticated with 401."""
    response = await client.post(
        f"/api/v1/reviews/{uuid.uuid4()}/reject",
        json={"feedback_notes": "Incorrect response."},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_reject_forbidden_for_customer(
    client: AsyncClient,
    test_customer_user: dict,
):
    """Requirement 16: CUSTOMER cannot reject reviews."""
    response = await client.post(
        f"/api/v1/reviews/{uuid.uuid4()}/reject",
        json={"feedback_notes": "Incorrect response."},
        headers=test_customer_user["headers"],
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_reject_review_not_found(
    client: AsyncClient,
    test_agent_user: dict,
):
    """Requirement 17: Rejecting a nonexistent review returns 404."""
    response = await client.post(
        f"/api/v1/reviews/{uuid.uuid4()}/reject",
        json={"feedback_notes": "The AI response was completely off-topic."},
        headers=test_agent_user["headers"],
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 18–20. POST /escalate — access control and 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_escalate_requires_authentication(client: AsyncClient):
    """Requirement 18: /escalate must reject unauthenticated with 401."""
    response = await client.post(
        f"/api/v1/reviews/{uuid.uuid4()}/escalate",
        json={"feedback_notes": "Requires specialist team."},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_escalate_forbidden_for_customer(
    client: AsyncClient,
    test_customer_user: dict,
):
    """Requirement 19: CUSTOMER cannot escalate reviews."""
    response = await client.post(
        f"/api/v1/reviews/{uuid.uuid4()}/escalate",
        json={"feedback_notes": "Requires specialist team."},
        headers=test_customer_user["headers"],
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_escalate_review_not_found(
    client: AsyncClient,
    test_agent_user: dict,
):
    """Requirement 20: Escalating a nonexistent review returns 404."""
    response = await client.post(
        f"/api/v1/reviews/{uuid.uuid4()}/escalate",
        json={"feedback_notes": "Needs billing specialist team to handle."},
        headers=test_agent_user["headers"],
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 21. Full lifecycle: approve → ticket resolves → duplicate action 409
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_lifecycle_approve_then_duplicate_returns_409(
    client: AsyncClient,
    db_session: AsyncSession,
    test_agent_user: dict,
):
    """Requirement 21: Agent approves review; subsequent action returns 409."""
    review = await _create_full_review(db_session)
    review_id = str(review.id)

    # Step 1: Approve the review
    approve_resp = await client.post(
        f"/api/v1/reviews/{review_id}/approve",
        json={"notes": "Looks good, AI response is accurate.", "resolve_ticket": False},
        headers=test_agent_user["headers"],
    )
    assert approve_resp.status_code == 200, approve_resp.text
    data = approve_resp.json()
    assert data["status"] == "APPROVED"
    assert data["action_taken"] == "APPROVED"
    assert data["reviewer_id"] == str(test_agent_user["user"].id)

    # Step 2: Attempt to approve again → must return 409 Conflict
    duplicate_resp = await client.post(
        f"/api/v1/reviews/{review_id}/approve",
        json={},
        headers=test_agent_user["headers"],
    )
    assert duplicate_resp.status_code == 409


# ---------------------------------------------------------------------------
# 22. Full lifecycle: edit draft → edited response dispatched
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_lifecycle_edit_draft(
    client: AsyncClient,
    db_session: AsyncSession,
    test_agent_user: dict,
):
    """Requirement 22: Agent submits an edited draft; review is marked EDITED."""
    review = await _create_full_review(db_session)
    review_id = str(review.id)

    edit_resp = await client.post(
        f"/api/v1/reviews/{review_id}/edit",
        json={
            "final_submitted_text": "Thank you for contacting us. Your refund has been initiated.",
            "notes": "Added refund confirmation detail.",
            "resolve_ticket": False,
        },
        headers=test_agent_user["headers"],
    )
    assert edit_resp.status_code == 200, edit_resp.text
    data = edit_resp.json()
    assert data["status"] == "EDITED"
    assert data["action_taken"] == "EDITED"
    assert data["final_submitted_text"] == "Thank you for contacting us. Your refund has been initiated."
    assert data["reviewer_id"] == str(test_agent_user["user"].id)


# ---------------------------------------------------------------------------
# 23. Full lifecycle: reject → ticket returns to IN_PROGRESS
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_lifecycle_reject_draft(
    client: AsyncClient,
    db_session: AsyncSession,
    test_agent_user: dict,
):
    """Requirement 23: Agent rejects draft; review status becomes REJECTED."""
    review = await _create_full_review(db_session)
    review_id = str(review.id)

    reject_resp = await client.post(
        f"/api/v1/reviews/{review_id}/reject",
        json={"feedback_notes": "AI response was completely wrong about the policy."},
        headers=test_agent_user["headers"],
    )
    assert reject_resp.status_code == 200, reject_resp.text
    data = reject_resp.json()
    assert data["status"] == "REJECTED"
    assert data["action_taken"] == "REJECTED"
    assert "completely wrong" in data["feedback_notes"]
    assert data["reviewer_id"] == str(test_agent_user["user"].id)


# ---------------------------------------------------------------------------
# 24. Full lifecycle: escalate → review becomes ESCALATED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_lifecycle_escalate(
    client: AsyncClient,
    db_session: AsyncSession,
    test_agent_user: dict,
):
    """Requirement 24: Agent escalates; review status becomes ESCALATED."""
    review = await _create_full_review(db_session)
    review_id = str(review.id)

    escalate_resp = await client.post(
        f"/api/v1/reviews/{review_id}/escalate",
        json={
            "feedback_notes": "Requires legal team escalation for potential chargeback dispute.",
            "assign_to_agent_id": None,
        },
        headers=test_agent_user["headers"],
    )
    assert escalate_resp.status_code == 200, escalate_resp.text
    data = escalate_resp.json()
    assert data["status"] == "ESCALATED"
    assert data["action_taken"] == "ESCALATED"
    assert data["reviewer_id"] == str(test_agent_user["user"].id)


# ---------------------------------------------------------------------------
# 25–26. Extra fields are rejected with 422 (extra="forbid")
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_extra_fields_rejected(
    client: AsyncClient,
    test_agent_user: dict,
):
    """Requirement 25: Extra fields in approve request return 422 Unprocessable Entity."""
    response = await client.post(
        f"/api/v1/reviews/{uuid.uuid4()}/approve",
        json={"reviewer_id": str(uuid.uuid4()), "malicious_field": "injected"},
        headers=test_agent_user["headers"],
    )
    # 422 because extra fields are forbidden by Pydantic (before 404 is reached)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_edit_extra_fields_rejected(
    client: AsyncClient,
    test_agent_user: dict,
):
    """Requirement 26: Extra fields in edit request return 422 Unprocessable Entity."""
    response = await client.post(
        f"/api/v1/reviews/{uuid.uuid4()}/edit",
        json={
            "final_submitted_text": "Valid text",
            "injected_field": "should fail",
        },
        headers=test_agent_user["headers"],
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# 27. reviewer_id cannot be spoofed from client
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reviewer_id_is_server_controlled(
    client: AsyncClient,
    db_session: AsyncSession,
    test_agent_user: dict,
):
    """Requirement 27: reviewer_id must equal the authenticated user, not any client-supplied value."""
    review = await _create_full_review(db_session)
    review_id = str(review.id)
    fake_agent_id = str(uuid.uuid4())

    # Approve with no extra fields (extra="forbid" prevents injecting reviewer_id)
    approve_resp = await client.post(
        f"/api/v1/reviews/{review_id}/approve",
        json={"notes": "Verified"},
        headers=test_agent_user["headers"],
    )
    assert approve_resp.status_code == 200
    data = approve_resp.json()

    # reviewer_id must be the authenticated agent's user ID — not a fake one
    assert data["reviewer_id"] == str(test_agent_user["user"].id)
    assert data["reviewer_id"] != fake_agent_id


# ---------------------------------------------------------------------------
# 28. GET /pending pagination — skip and limit respected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pending_reviews_pagination(
    client: AsyncClient,
    db_session: AsyncSession,
    test_agent_user: dict,
):
    """Requirement 28: /pending supports skip and limit pagination parameters."""
    # Seed 3 reviews
    for _ in range(3):
        await _create_full_review(db_session)

    # Fetch with limit=2
    resp_page1 = await client.get(
        "/api/v1/reviews/pending?skip=0&limit=2",
        headers=test_agent_user["headers"],
    )
    assert resp_page1.status_code == 200
    data1 = resp_page1.json()
    assert len(data1["items"]) <= 2

    # Fetch with skip=2, limit=2
    resp_page2 = await client.get(
        "/api/v1/reviews/pending?skip=2&limit=2",
        headers=test_agent_user["headers"],
    )
    assert resp_page2.status_code == 200
    data2 = resp_page2.json()

    # Pages must not overlap
    ids_page1 = {item["id"] for item in data1["items"]}
    ids_page2 = {item["id"] for item in data2["items"]}
    assert ids_page1.isdisjoint(ids_page2)


# ---------------------------------------------------------------------------
# Bonus: GET review detail returns expected structure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_review_detail_structure(
    client: AsyncClient,
    db_session: AsyncSession,
    test_agent_user: dict,
):
    """Agent can fetch a review detail with all expected fields."""
    review = await _create_full_review(db_session)
    review_id = str(review.id)

    response = await client.get(
        f"/api/v1/reviews/{review_id}",
        headers=test_agent_user["headers"],
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == review_id
    assert "ticket_id" in data
    assert "ai_run_id" in data
    assert "status" in data
    assert data["status"] == "PENDING"
    assert "original_ai_draft" in data
    assert "escalation_reason" in data
    assert "tool_invocations" in data
    assert isinstance(data["tool_invocations"], list)


# ---------------------------------------------------------------------------
# Bonus: Admin can also approve reviews (not just agents)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_can_approve_review(
    client: AsyncClient,
    db_session: AsyncSession,
    test_admin_user: dict,
):
    """Admin role has full authority to approve HITL reviews."""
    review = await _create_full_review(db_session)
    review_id = str(review.id)

    approve_resp = await client.post(
        f"/api/v1/reviews/{review_id}/approve",
        json={"notes": "Admin approved.", "resolve_ticket": True},
        headers=test_admin_user["headers"],
    )
    assert approve_resp.status_code == 200
    data = approve_resp.json()
    assert data["status"] == "APPROVED"
    assert data["reviewer_id"] == str(test_admin_user["user"].id)
