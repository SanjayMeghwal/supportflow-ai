"""Bounded AI tool services for Phase 11.

Each tool follows a strict contract:
  1. Input is validated via Pydantic (before this module is called).
  2. Authorization is enforced using the application's existing RBAC and
     resource-ownership checks from api/deps.py.
  3. The database is accessed only through the existing SQLAlchemy async
     session — never via LLM-generated SQL or arbitrary queries.
  4. Results are sanitized before returning to LangGraph / the LLM.

The LLM is never given raw ORM objects, hashed passwords, internal UUIDs
it did not need, or any other sensitive internal field.
"""

from decimal import Decimal
from typing import Any
import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.order import Order, Payment
from backend.app.models.user import Customer, User, UserRole
from backend.app.schemas.tools import (
    OrderStatusData,
    PaymentStatusData,
    ToolResult,
)


# ---------------------------------------------------------------------------
# Authorization helper (reuses existing ownership invariants from deps.py)
# ---------------------------------------------------------------------------


async def _resolve_customer_id_for_user(
    user: User, db: AsyncSession
) -> uuid.UUID | None:
    """Resolve the Customer.id for a CUSTOMER-role user.

    Returns None if the user has no linked customer profile (e.g. agents/admins
    calling with elevated access, where we return True directly).
    """
    result = await db.execute(
        select(Customer.id).where(Customer.user_id == user.id)
    )
    return result.scalar_one_or_none()


async def _authorize_order_access(
    order: Order,
    current_user: User,
    db: AsyncSession,
) -> bool:
    """Enforce resource ownership on an Order.

    - ADMIN and SUPPORT_AGENT have cross-customer read access.
    - CUSTOMER can ONLY access orders where order.customer_id == their own Customer.id.
    - Returns False (IDOR denied) if authorization fails rather than raising,
      so the caller can produce a safe ToolResult error.
    """
    if current_user.role in (UserRole.ADMIN, UserRole.SUPPORT_AGENT):
        return True

    customer_id = await _resolve_customer_id_for_user(current_user, db)
    if customer_id is None:
        return False
    return order.customer_id == customer_id


# ---------------------------------------------------------------------------
# Tool: get_order_status
# ---------------------------------------------------------------------------


async def get_order_status(
    *,
    order_number: str,
    current_user: User,
    db: AsyncSession,
) -> ToolResult:
    """Retrieve sanitized order status for a given order number.

    Authorization:
      - CUSTOMER: may only access their own orders.
      - SUPPORT_AGENT / ADMIN: may access any order for support purposes.

    Result sanitization:
      - Returns order_number, order_status, total_amount, currency, item_count, created_at.
      - Does NOT expose: internal UUIDs, customer_id, raw items_json details.

    Parameters
    ----------
    order_number : str
        The human-readable order number (validated before calling).
    current_user : User
        The authenticated application user making the request.
    db : AsyncSession
        Active database session (never constructed by the LLM).
    """
    # 1. Fetch order by order_number
    result = await db.execute(
        select(Order).where(Order.order_number == order_number.strip())
    )
    order = result.scalar_one_or_none()

    if order is None:
        return ToolResult(
            tool_name="get_order_status",
            success=False,
            data=None,
            error=f"Order '{order_number}' not found.",
        )

    # 2. Authorization check (IDOR protection)
    authorized = await _authorize_order_access(order, current_user, db)
    if not authorized:
        return ToolResult(
            tool_name="get_order_status",
            success=False,
            data=None,
            error="Access denied: you do not have permission to view this order.",
        )

    # 3. Sanitize and return only required fields
    sanitized = OrderStatusData(
        order_number=order.order_number,
        order_status=order.order_status.value,
        total_amount=str(order.total_amount),
        currency=order.currency,
        item_count=len(order.items_json) if isinstance(order.items_json, list) else 0,
        created_at=order.created_at.isoformat(),
    )

    return ToolResult(
        tool_name="get_order_status",
        success=True,
        data=sanitized.model_dump(),
        error=None,
    )


# ---------------------------------------------------------------------------
# Tool: get_payment_status
# ---------------------------------------------------------------------------


async def get_payment_status(
    *,
    order_number: str,
    current_user: User,
    db: AsyncSession,
) -> ToolResult:
    """Retrieve sanitized payment status for a given order number.

    Authorization:
      - CUSTOMER: may only access payments for their own orders.
      - SUPPORT_AGENT / ADMIN: may access any payment for support purposes.

    Result sanitization:
      - Returns order_number, payment_status, amount, currency, payment_method,
        transaction_reference.
      - Does NOT expose: internal UUIDs, gateway_response_json (may contain
        provider secrets), raw order/customer IDs.

    If the order has multiple payments, the most recent is returned.

    Parameters
    ----------
    order_number : str
        The human-readable order number (validated before calling).
    current_user : User
        The authenticated application user making the request.
    db : AsyncSession
        Active database session (never constructed by the LLM).
    """
    # 1. Fetch order + payments eagerly
    result = await db.execute(
        select(Order)
        .options(selectinload(Order.payments))
        .where(Order.order_number == order_number.strip())
    )
    order = result.scalar_one_or_none()

    if order is None:
        return ToolResult(
            tool_name="get_payment_status",
            success=False,
            data=None,
            error=f"Order '{order_number}' not found.",
        )

    # 2. Authorization check (IDOR protection)
    authorized = await _authorize_order_access(order, current_user, db)
    if not authorized:
        return ToolResult(
            tool_name="get_payment_status",
            success=False,
            data=None,
            error="Access denied: you do not have permission to view this order's payment.",
        )

    # 3. Select most recent payment
    if not order.payments:
        return ToolResult(
            tool_name="get_payment_status",
            success=False,
            data=None,
            error=f"No payment records found for order '{order_number}'.",
        )

    payment: Payment = sorted(order.payments, key=lambda p: p.created_at)[-1]

    # 4. Sanitize — deliberately exclude gateway_response_json and internal IDs
    sanitized = PaymentStatusData(
        order_number=order.order_number,
        payment_status=payment.payment_status.value,
        amount=str(payment.amount),
        currency=order.currency,
        payment_method=payment.payment_method.value,
        transaction_reference=payment.transaction_reference,
    )

    return ToolResult(
        tool_name="get_payment_status",
        success=True,
        data=sanitized.model_dump(),
        error=None,
    )
