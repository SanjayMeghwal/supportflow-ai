"""Unit tests for Phase 11: Bounded tool executors (get_order_status, get_payment_status).

Tests cover:
- get_order_status: order not found → ToolResult error
- get_order_status: CUSTOMER IDOR denial (wrong customer_id)
- get_order_status: CUSTOMER authorized access (own order) → sanitized data
- get_order_status: SUPPORT_AGENT cross-customer access
- get_order_status: ADMIN cross-customer access
- get_order_status: sensitive fields excluded from result
- get_payment_status: order not found → ToolResult error
- get_payment_status: no payments → ToolResult error
- get_payment_status: CUSTOMER IDOR denial
- get_payment_status: authorized access → sanitized data
- get_payment_status: most-recent payment selected when multiple exist
- get_payment_status: gateway_response_json excluded from result
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from backend.app.models.order import Order, OrderStatus, Payment, PaymentMethod, PaymentStatus
from backend.app.models.user import Customer, User, UserRole
from backend.app.services.tools import get_order_status, get_payment_status


# ---------------------------------------------------------------------------
# Helpers — lightweight in-memory mock builders
# ---------------------------------------------------------------------------


def _make_user(role: UserRole, user_id: uuid.UUID | None = None) -> User:
    user = MagicMock(spec=User)
    user.id = user_id or uuid.uuid4()
    user.role = role
    return user


def _make_order(
    order_number: str = "ORD-20260924-ABCDE",
    customer_id: uuid.UUID | None = None,
    order_status: OrderStatus = OrderStatus.DELIVERED,
    total_amount: Decimal = Decimal("2000.00"),
    currency: str = "INR",
    items_json: list | None = None,
) -> Order:
    order = MagicMock(spec=Order)
    order.order_number = order_number
    order.customer_id = customer_id or uuid.uuid4()
    order.order_status = order_status
    order.total_amount = total_amount
    order.currency = currency
    order.items_json = items_json if items_json is not None else [{"sku": "ITEM-001"}]
    order.created_at = datetime(2026, 9, 24, 10, 0, 0, tzinfo=timezone.utc)
    order.payments = []
    return order


def _make_payment(
    order: Order,
    payment_status: PaymentStatus = PaymentStatus.SUCCESS,
    amount: Decimal = Decimal("2000.00"),
    payment_method: PaymentMethod = PaymentMethod.UPI,
    transaction_reference: str = "TXN-12345",
    created_at: datetime | None = None,
) -> Payment:
    payment = MagicMock(spec=Payment)
    payment.payment_status = payment_status
    payment.amount = amount
    payment.payment_method = payment_method
    payment.transaction_reference = transaction_reference
    payment.created_at = created_at or datetime(2026, 9, 24, 11, 0, 0, tzinfo=timezone.utc)
    return payment


def _make_db_returning(value) -> AsyncMock:
    """Build a mock AsyncSession.execute() that returns a scalar_one_or_none value."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = value
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    return mock_db


# ---------------------------------------------------------------------------
# get_order_status — not found
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_order_status_order_not_found():
    """Returns a failure ToolResult when the order number does not exist."""
    mock_db = _make_db_returning(None)
    user = _make_user(UserRole.CUSTOMER)

    result = await get_order_status(
        order_number="ORD-NONEXISTENT",
        current_user=user,
        db=mock_db,
    )

    assert result.success is False
    assert result.data is None
    assert "not found" in result.error
    assert result.tool_name == "get_order_status"


# ---------------------------------------------------------------------------
# get_order_status — CUSTOMER IDOR protection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_order_status_customer_idor_denied():
    """CUSTOMER cannot access an order belonging to a different customer."""
    own_customer_id = uuid.uuid4()
    other_customer_id = uuid.uuid4()

    order = _make_order(customer_id=other_customer_id)
    user = _make_user(UserRole.CUSTOMER)

    # First call: fetch order → returns order
    # Second call: resolve customer_id → returns own_customer_id (different from order.customer_id)
    order_result = MagicMock()
    order_result.scalar_one_or_none.return_value = order

    customer_result = MagicMock()
    customer_result.scalar_one_or_none.return_value = own_customer_id

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=[order_result, customer_result])

    result = await get_order_status(
        order_number="ORD-20260924-ABCDE",
        current_user=user,
        db=mock_db,
    )

    assert result.success is False
    assert "denied" in result.error.lower() or "permission" in result.error.lower()
    assert result.data is None


# ---------------------------------------------------------------------------
# get_order_status — CUSTOMER authorized (own order)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_order_status_customer_own_order_success():
    """CUSTOMER with a matching customer_id gets sanitized order data."""
    customer_id = uuid.uuid4()
    order = _make_order(
        customer_id=customer_id,
        order_status=OrderStatus.CANCELLED,
        total_amount=Decimal("2000.00"),
        items_json=[{"sku": "A"}, {"sku": "B"}],
    )

    order_result = MagicMock()
    order_result.scalar_one_or_none.return_value = order
    customer_result = MagicMock()
    customer_result.scalar_one_or_none.return_value = customer_id

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=[order_result, customer_result])
    user = _make_user(UserRole.CUSTOMER)

    result = await get_order_status(
        order_number="ORD-20260924-ABCDE",
        current_user=user,
        db=mock_db,
    )

    assert result.success is True
    assert result.tool_name == "get_order_status"
    assert result.data["order_number"] == "ORD-20260924-ABCDE"
    assert result.data["order_status"] == "CANCELLED"
    assert result.data["total_amount"] == "2000.00"
    assert result.data["item_count"] == 2
    assert result.data["currency"] == "INR"
    assert "created_at" in result.data


# ---------------------------------------------------------------------------
# get_order_status — SUPPORT_AGENT cross-customer access
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_order_status_support_agent_can_access_any_order():
    """SUPPORT_AGENT bypasses IDOR check and can access any order."""
    order = _make_order(customer_id=uuid.uuid4())  # Different customer
    mock_db = _make_db_returning(order)
    user = _make_user(UserRole.SUPPORT_AGENT)

    result = await get_order_status(
        order_number="ORD-20260924-ABCDE",
        current_user=user,
        db=mock_db,
    )

    assert result.success is True
    assert result.data is not None


# ---------------------------------------------------------------------------
# get_order_status — ADMIN cross-customer access
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_order_status_admin_can_access_any_order():
    """ADMIN bypasses IDOR check and can access any order."""
    order = _make_order(customer_id=uuid.uuid4())
    mock_db = _make_db_returning(order)
    user = _make_user(UserRole.ADMIN)

    result = await get_order_status(
        order_number="ORD-20260924-ABCDE",
        current_user=user,
        db=mock_db,
    )

    assert result.success is True


# ---------------------------------------------------------------------------
# get_order_status — sensitive field exclusion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_order_status_excludes_sensitive_fields():
    """Sanitized result must NOT expose customer_id, raw items_json, or internal IDs."""
    customer_id = uuid.uuid4()
    order = _make_order(customer_id=customer_id)
    mock_db = _make_db_returning(order)
    user = _make_user(UserRole.ADMIN)

    result = await get_order_status(
        order_number="ORD-20260924-ABCDE",
        current_user=user,
        db=mock_db,
    )

    assert result.success is True
    data = result.data
    assert "customer_id" not in data
    assert "items_json" not in data
    assert "id" not in data


# ---------------------------------------------------------------------------
# get_payment_status — order not found
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_payment_status_order_not_found():
    """Returns a failure ToolResult when the order does not exist."""
    mock_db = _make_db_returning(None)
    user = _make_user(UserRole.ADMIN)

    result = await get_payment_status(
        order_number="ORD-NONEXISTENT",
        current_user=user,
        db=mock_db,
    )

    assert result.success is False
    assert result.data is None
    assert "not found" in result.error
    assert result.tool_name == "get_payment_status"


# ---------------------------------------------------------------------------
# get_payment_status — no payments on order
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_payment_status_no_payments_returns_error():
    """Returns a failure ToolResult when the order exists but has no payments."""
    order = _make_order()
    order.payments = []  # No payments
    mock_db = _make_db_returning(order)
    user = _make_user(UserRole.ADMIN)

    result = await get_payment_status(
        order_number="ORD-20260924-ABCDE",
        current_user=user,
        db=mock_db,
    )

    assert result.success is False
    assert "No payment records" in result.error


# ---------------------------------------------------------------------------
# get_payment_status — CUSTOMER IDOR denial
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_payment_status_customer_idor_denied():
    """CUSTOMER cannot access payment for an order that belongs to another customer."""
    own_customer_id = uuid.uuid4()
    other_customer_id = uuid.uuid4()

    order = _make_order(customer_id=other_customer_id)

    order_result = MagicMock()
    order_result.scalar_one_or_none.return_value = order
    customer_result = MagicMock()
    customer_result.scalar_one_or_none.return_value = own_customer_id

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=[order_result, customer_result])
    user = _make_user(UserRole.CUSTOMER)

    result = await get_payment_status(
        order_number="ORD-20260924-ABCDE",
        current_user=user,
        db=mock_db,
    )

    assert result.success is False
    assert "denied" in result.error.lower() or "permission" in result.error.lower()


# ---------------------------------------------------------------------------
# get_payment_status — authorized access, sanitized result
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_payment_status_admin_authorized_success():
    """ADMIN gets sanitized payment data for any order."""
    order = _make_order(customer_id=uuid.uuid4())
    payment = _make_payment(
        order=order,
        payment_status=PaymentStatus.REFUND_INITIATED,
        amount=Decimal("2000.00"),
        payment_method=PaymentMethod.UPI,
        transaction_reference="TXN-REFUND-999",
    )
    order.payments = [payment]
    mock_db = _make_db_returning(order)
    user = _make_user(UserRole.ADMIN)

    result = await get_payment_status(
        order_number="ORD-20260924-ABCDE",
        current_user=user,
        db=mock_db,
    )

    assert result.success is True
    data = result.data
    assert data["order_number"] == "ORD-20260924-ABCDE"
    assert data["payment_status"] == "REFUND_INITIATED"
    assert data["payment_method"] == "UPI"
    assert data["transaction_reference"] == "TXN-REFUND-999"
    assert data["currency"] == "INR"


# ---------------------------------------------------------------------------
# get_payment_status — most recent payment selected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_payment_status_returns_most_recent_payment():
    """When multiple payments exist, the most recent (by created_at) is returned."""
    order = _make_order(customer_id=uuid.uuid4())

    older_payment = _make_payment(
        order=order,
        payment_status=PaymentStatus.FAILED,
        transaction_reference="TXN-OLD",
        created_at=datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc),
    )
    newer_payment = _make_payment(
        order=order,
        payment_status=PaymentStatus.SUCCESS,
        transaction_reference="TXN-NEW",
        created_at=datetime(2026, 9, 24, 15, 0, 0, tzinfo=timezone.utc),
    )
    order.payments = [older_payment, newer_payment]
    mock_db = _make_db_returning(order)
    user = _make_user(UserRole.ADMIN)

    result = await get_payment_status(
        order_number="ORD-20260924-ABCDE",
        current_user=user,
        db=mock_db,
    )

    assert result.success is True
    assert result.data["transaction_reference"] == "TXN-NEW"
    assert result.data["payment_status"] == "SUCCESS"


# ---------------------------------------------------------------------------
# get_payment_status — sensitive field exclusion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_payment_status_excludes_sensitive_fields():
    """gateway_response_json, internal order_id, and raw IDs must NOT appear in result."""
    order = _make_order(customer_id=uuid.uuid4())
    payment = _make_payment(order=order)
    payment.gateway_response_json = {"provider": "Razorpay", "secret": "xyz"}
    order.payments = [payment]
    mock_db = _make_db_returning(order)
    user = _make_user(UserRole.ADMIN)

    result = await get_payment_status(
        order_number="ORD-20260924-ABCDE",
        current_user=user,
        db=mock_db,
    )

    assert result.success is True
    data = result.data
    assert "gateway_response_json" not in data
    assert "order_id" not in data
    assert "id" not in data
