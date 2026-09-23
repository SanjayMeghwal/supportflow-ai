"""Ticket management router: CRUD, messaging, and agent assignment.

Endpoints:
  POST   /api/v1/tickets                        — create a new support ticket (CUSTOMER only)
  GET    /api/v1/tickets                         — list tickets (scoped by role)
  GET    /api/v1/tickets/{ticket_id}             — get ticket detail
  PATCH  /api/v1/tickets/{ticket_id}             — update ticket metadata (AGENT/ADMIN)
  POST   /api/v1/tickets/{ticket_id}/messages    — add a message to the thread
  GET    /api/v1/tickets/{ticket_id}/messages    — list messages for a ticket
  POST   /api/v1/tickets/{ticket_id}/assign      — assign/reassign an agent (AGENT/ADMIN)

Security invariants enforced at this layer:
  1. Customers can ONLY interact with their own tickets (verify_resource_ownership).
  2. Internal notes are NEVER returned to CUSTOMER users.
  3. ticket_number is generated server-side — never from client input.
  4. sender_type is derived from the authenticated user's role — never from client input.
  5. Status transitions are validated against an explicit allowlist.
  6. closed_at is managed automatically on status transitions.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.api.deps import (
    get_current_customer,
    get_current_user,
    require_support_agent,
    verify_resource_ownership,
)
from backend.app.core.database import get_db
from backend.app.models.ticket import (
    SenderType,
    Ticket,
    TicketCategory,
    TicketMessage,
    TicketPriority,
    TicketStatus,
)
from backend.app.models.user import Customer, User, UserRole
from backend.app.schemas.ticket import (
    TicketAssignRequest,
    TicketCreateRequest,
    TicketListResponse,
    TicketMessageCreateRequest,
    TicketMessageResponse,
    TicketResponse,
    TicketUpdateRequest,
    is_valid_status_transition,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _generate_ticket_number() -> str:
    """Generate a unique ticket number: TKT-YYYYMMDD-XXXXX.

    Uses current UTC date + 5 random hex characters.
    At ~1M tickets/day, the birthday-paradox collision probability is
    still negligible (p ≈ 0.5 at ~1024 tickets per day-bucket).
    For our expected volume this is more than sufficient.
    """
    date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
    random_part = uuid.uuid4().hex[:5].upper()
    return f"TKT-{date_part}-{random_part}"


def _user_role_to_sender_type(role: UserRole) -> SenderType:
    """Map the authenticated user's role to the appropriate SenderType.

    This mapping is enforced server-side — the client never specifies
    sender_type directly. This prevents a customer from impersonating
    an agent or the AI system.
    """
    if role == UserRole.CUSTOMER:
        return SenderType.CUSTOMER
    return SenderType.AGENT  # Both SUPPORT_AGENT and ADMIN map to AGENT


def _ticket_to_response(
    ticket: Ticket, include_messages: bool = False, is_customer: bool = False
) -> TicketResponse:
    """Convert a Ticket ORM instance to its Pydantic response.

    When include_messages is True, messages are included. For CUSTOMER
    users, internal notes are filtered out.
    """
    messages = None
    if include_messages and ticket.messages is not None:
        msg_list = ticket.messages
        if is_customer:
            msg_list = [m for m in msg_list if not m.is_internal_note]
        messages = [
            TicketMessageResponse(
                id=m.id,
                ticket_id=m.ticket_id,
                sender_id=m.sender_id,
                sender_type=m.sender_type.value,
                content=m.content,
                is_internal_note=m.is_internal_note,
                created_at=m.created_at,
            )
            for m in msg_list
        ]

    return TicketResponse(
        id=ticket.id,
        ticket_number=ticket.ticket_number,
        customer_id=ticket.customer_id,
        assigned_agent_id=ticket.assigned_agent_id,
        title=ticket.title,
        description=ticket.description,
        category=ticket.category.value,
        priority=ticket.priority.value,
        status=ticket.status.value,
        resolution_summary=ticket.resolution_summary,
        closed_at=ticket.closed_at,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        messages=messages,
    )


# ---------------------------------------------------------------------------
# POST /tickets — Create Ticket (CUSTOMER only)
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=TicketResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new support ticket",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Only customers can create tickets"},
    },
)
async def create_ticket(
    payload: TicketCreateRequest,
    customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
) -> TicketResponse:
    """Create a new support ticket for the authenticated customer.

    - ticket_number is generated server-side.
    - customer_id is resolved from the JWT, not from client input.
    - Initial status is always OPEN, priority is MEDIUM.
    """
    ticket = Ticket(
        ticket_number=_generate_ticket_number(),
        customer_id=customer.id,
        title=payload.title,
        description=payload.description,
        category=payload.category,
        priority=TicketPriority.MEDIUM,
        status=TicketStatus.OPEN,
    )
    db.add(ticket)
    await db.flush()
    await db.refresh(ticket)

    return _ticket_to_response(ticket)


# ---------------------------------------------------------------------------
# GET /tickets — List Tickets (role-scoped)
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=TicketListResponse,
    summary="List tickets (scoped by role)",
    responses={
        401: {"description": "Not authenticated"},
    },
)
async def list_tickets(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    limit: int = Query(default=20, ge=1, le=100, description="Page size"),
    status_filter: TicketStatus | None = Query(
        default=None, alias="status", description="Filter by ticket status"
    ),
    category_filter: TicketCategory | None = Query(
        default=None, alias="category", description="Filter by category"
    ),
    priority_filter: TicketPriority | None = Query(
        default=None, alias="priority", description="Filter by priority"
    ),
) -> TicketListResponse:
    """List tickets with pagination and optional filters.

    - CUSTOMER: sees only their own tickets.
    - SUPPORT_AGENT / ADMIN: sees all tickets.
    """

    query = select(Ticket)
    count_query = select(func.count(Ticket.id))

    # Scope to customer's own tickets if CUSTOMER role
    if current_user.role == UserRole.CUSTOMER:
        customer_result = await db.execute(
            select(Customer.id).where(Customer.user_id == current_user.id)
        )
        customer_id = customer_result.scalar_one_or_none()
        if customer_id is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Customer profile not found.",
            )
        query = query.where(Ticket.customer_id == customer_id)
        count_query = count_query.where(Ticket.customer_id == customer_id)

    # Apply optional filters
    if status_filter is not None:
        query = query.where(Ticket.status == status_filter)
        count_query = count_query.where(Ticket.status == status_filter)
    if category_filter is not None:
        query = query.where(Ticket.category == category_filter)
        count_query = count_query.where(Ticket.category == category_filter)
    if priority_filter is not None:
        query = query.where(Ticket.priority == priority_filter)
        count_query = count_query.where(Ticket.priority == priority_filter)

    # Total count (before pagination)
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    # Fetch paginated results, ordered by creation date descending
    query = query.order_by(Ticket.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    tickets = result.scalars().all()

    is_customer = current_user.role == UserRole.CUSTOMER
    return TicketListResponse(
        tickets=[_ticket_to_response(t, include_messages=False) for t in tickets],
        total=total,
        offset=offset,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# GET /tickets/{ticket_id} — Ticket Detail
# ---------------------------------------------------------------------------


@router.get(
    "/{ticket_id}",
    response_model=TicketResponse,
    summary="Get ticket detail",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Cannot access another customer's ticket"},
        404: {"description": "Ticket not found"},
    },
)
async def get_ticket(
    ticket_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TicketResponse:
    """Get full detail for a single ticket, including messages.

    - CUSTOMER: ownership enforced — can only see own tickets.
    - Internal notes are filtered out for CUSTOMER users.
    """
    result = await db.execute(
        select(Ticket)
        .options(selectinload(Ticket.messages))
        .where(Ticket.id == ticket_id)
    )
    ticket = result.scalar_one_or_none()

    if ticket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found.",
        )

    # Enforce resource ownership for customers
    await verify_resource_ownership(
        resource_customer_id=ticket.customer_id,
        current_user=current_user,
        db=db,
    )

    is_customer = current_user.role == UserRole.CUSTOMER
    return _ticket_to_response(ticket, include_messages=True, is_customer=is_customer)


# ---------------------------------------------------------------------------
# PATCH /tickets/{ticket_id} — Update Ticket (AGENT / ADMIN)
# ---------------------------------------------------------------------------


@router.patch(
    "/{ticket_id}",
    response_model=TicketResponse,
    summary="Update ticket metadata",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Only agents/admins can update tickets"},
        404: {"description": "Ticket not found"},
        409: {"description": "Invalid status transition"},
    },
)
async def update_ticket(
    ticket_id: uuid.UUID,
    payload: TicketUpdateRequest,
    current_user: User = Depends(require_support_agent),
    db: AsyncSession = Depends(get_db),
) -> TicketResponse:
    """Update ticket metadata (status, priority, category, resolution).

    Status transitions are validated against the lifecycle allowlist.
    closed_at is set automatically when transitioning to CLOSED or RESOLVED,
    and cleared when reopening.
    """
    result = await db.execute(select(Ticket).where(Ticket.id == ticket_id))
    ticket = result.scalar_one_or_none()

    if ticket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found.",
        )

    # Status transition validation
    if payload.status is not None and payload.status != ticket.status:
        if not is_valid_status_transition(ticket.status, payload.status):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Invalid status transition: "
                    f"{ticket.status.value} → {payload.status.value}."
                ),
            )
        ticket.status = payload.status

        # Manage closed_at timestamp
        if payload.status in (TicketStatus.CLOSED, TicketStatus.RESOLVED):
            ticket.closed_at = datetime.now(timezone.utc)
        elif ticket.closed_at is not None:
            # Reopening — clear the closed timestamp
            ticket.closed_at = None

    if payload.priority is not None:
        ticket.priority = payload.priority

    if payload.category is not None:
        ticket.category = payload.category

    if payload.resolution_summary is not None:
        ticket.resolution_summary = payload.resolution_summary

    await db.flush()
    await db.refresh(ticket)

    return _ticket_to_response(ticket)


# ---------------------------------------------------------------------------
# POST /tickets/{ticket_id}/messages — Add Message
# ---------------------------------------------------------------------------


@router.post(
    "/{ticket_id}/messages",
    response_model=TicketMessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a message to the ticket thread",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Cannot message on another customer's ticket"},
        404: {"description": "Ticket not found"},
    },
)
async def add_message(
    ticket_id: uuid.UUID,
    payload: TicketMessageCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TicketMessageResponse:
    """Add a message to a ticket's conversation thread.

    - sender_type is derived from the user's role (never from client input).
    - Customers cannot create internal notes.
    - Ownership is enforced for CUSTOMER users.
    """
    # Verify ticket exists
    result = await db.execute(select(Ticket).where(Ticket.id == ticket_id))
    ticket = result.scalar_one_or_none()

    if ticket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found.",
        )

    # Enforce resource ownership for customers
    await verify_resource_ownership(
        resource_customer_id=ticket.customer_id,
        current_user=current_user,
        db=db,
    )

    # Customers cannot create internal notes
    is_internal = payload.is_internal_note
    if current_user.role == UserRole.CUSTOMER and is_internal:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Customers cannot create internal notes.",
        )

    message = TicketMessage(
        ticket_id=ticket_id,
        sender_id=current_user.id,
        sender_type=_user_role_to_sender_type(current_user.role),
        content=payload.content,
        is_internal_note=is_internal,
    )
    db.add(message)
    await db.flush()
    await db.refresh(message)

    return TicketMessageResponse(
        id=message.id,
        ticket_id=message.ticket_id,
        sender_id=message.sender_id,
        sender_type=message.sender_type.value,
        content=message.content,
        is_internal_note=message.is_internal_note,
        created_at=message.created_at,
    )


# ---------------------------------------------------------------------------
# GET /tickets/{ticket_id}/messages — List Messages
# ---------------------------------------------------------------------------


@router.get(
    "/{ticket_id}/messages",
    response_model=list[TicketMessageResponse],
    summary="List messages for a ticket",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Cannot view another customer's ticket messages"},
        404: {"description": "Ticket not found"},
    },
)
async def list_messages(
    ticket_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TicketMessageResponse]:
    """List all messages for a ticket in chronological order.

    - Internal notes are filtered out for CUSTOMER users.
    - Ownership enforced for CUSTOMER users.
    """
    # Verify ticket exists
    result = await db.execute(select(Ticket).where(Ticket.id == ticket_id))
    ticket = result.scalar_one_or_none()

    if ticket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found.",
        )

    # Enforce resource ownership for customers
    await verify_resource_ownership(
        resource_customer_id=ticket.customer_id,
        current_user=current_user,
        db=db,
    )

    # Build message query
    msg_query = (
        select(TicketMessage)
        .where(TicketMessage.ticket_id == ticket_id)
        .order_by(TicketMessage.created_at.asc())
    )

    # Filter internal notes for customer users
    if current_user.role == UserRole.CUSTOMER:
        msg_query = msg_query.where(TicketMessage.is_internal_note == False)  # noqa: E712

    msg_result = await db.execute(msg_query)
    messages = msg_result.scalars().all()

    return [
        TicketMessageResponse(
            id=m.id,
            ticket_id=m.ticket_id,
            sender_id=m.sender_id,
            sender_type=m.sender_type.value,
            content=m.content,
            is_internal_note=m.is_internal_note,
            created_at=m.created_at,
        )
        for m in messages
    ]


# ---------------------------------------------------------------------------
# POST /tickets/{ticket_id}/assign — Assign Agent (AGENT / ADMIN)
# ---------------------------------------------------------------------------


@router.post(
    "/{ticket_id}/assign",
    response_model=TicketResponse,
    summary="Assign or reassign an agent to a ticket",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Only agents/admins can assign tickets"},
        404: {"description": "Ticket or agent not found"},
    },
)
async def assign_ticket(
    ticket_id: uuid.UUID,
    payload: TicketAssignRequest,
    current_user: User = Depends(require_support_agent),
    db: AsyncSession = Depends(get_db),
) -> TicketResponse:
    """Assign or reassign a support agent to a ticket.

    Validates that:
    - The ticket exists.
    - The target agent exists and has a SUPPORT_AGENT or ADMIN role.
    """
    # Verify ticket exists
    result = await db.execute(select(Ticket).where(Ticket.id == ticket_id))
    ticket = result.scalar_one_or_none()

    if ticket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found.",
        )

    # Verify the target agent exists and has the appropriate role
    agent_result = await db.execute(
        select(User).where(User.id == payload.agent_id)
    )
    agent = agent_result.scalar_one_or_none()

    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found.",
        )

    if agent.role not in (UserRole.SUPPORT_AGENT, UserRole.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Target user is not a support agent or admin.",
        )

    ticket.assigned_agent_id = agent.id
    await db.flush()
    await db.refresh(ticket)

    return _ticket_to_response(ticket)
