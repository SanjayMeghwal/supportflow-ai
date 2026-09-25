"""Unit tests for Phase 11 tool Pydantic schemas.

Covers:
- GetOrderStatusInput validation (min/max length, extra field rejection)
- GetPaymentStatusInput validation
- ToolCallRequest validation
- ToolResult structure and serialization
- OrderStatusData and PaymentStatusData schemas
"""

import pytest
from pydantic import ValidationError

from backend.app.schemas.tools import (
    GetOrderStatusInput,
    GetPaymentStatusInput,
    OrderStatusData,
    PaymentStatusData,
    ToolCallRequest,
    ToolResult,
)


# ---------------------------------------------------------------------------
# GetOrderStatusInput
# ---------------------------------------------------------------------------


def test_get_order_status_input_valid():
    """Accepts a well-formed order number."""
    schema = GetOrderStatusInput(order_number="ORD-20260924-ABCDE")
    assert schema.order_number == "ORD-20260924-ABCDE"


def test_get_order_status_input_empty_string_rejected():
    """Empty order_number must be rejected (min_length=1)."""
    with pytest.raises(ValidationError) as exc_info:
        GetOrderStatusInput(order_number="")
    errors = exc_info.value.errors()
    assert any("min_length" in str(e) or "string_too_short" in str(e) for e in errors)


def test_get_order_status_input_too_long_rejected():
    """order_number exceeding max_length=64 must be rejected."""
    with pytest.raises(ValidationError):
        GetOrderStatusInput(order_number="X" * 65)


def test_get_order_status_input_extra_field_rejected():
    """Extra fields are forbidden (model_config extra='forbid')."""
    with pytest.raises(ValidationError):
        GetOrderStatusInput(order_number="ORD-001", unknown_field="hack")


# ---------------------------------------------------------------------------
# GetPaymentStatusInput
# ---------------------------------------------------------------------------


def test_get_payment_status_input_valid():
    """Accepts a well-formed order number."""
    schema = GetPaymentStatusInput(order_number="ORD-20260924-XYZ99")
    assert schema.order_number == "ORD-20260924-XYZ99"


def test_get_payment_status_input_empty_rejected():
    """Empty order_number must be rejected."""
    with pytest.raises(ValidationError):
        GetPaymentStatusInput(order_number="")


def test_get_payment_status_input_extra_field_rejected():
    """Extra fields are forbidden."""
    with pytest.raises(ValidationError):
        GetPaymentStatusInput(order_number="ORD-001", injected="value")


# ---------------------------------------------------------------------------
# ToolCallRequest
# ---------------------------------------------------------------------------


def test_tool_call_request_valid_with_arguments():
    """Well-formed ToolCallRequest with arguments."""
    req = ToolCallRequest(
        tool_name="get_order_status",
        arguments={"order_number": "ORD-20260924-ABCDE"},
    )
    assert req.tool_name == "get_order_status"
    assert req.arguments == {"order_number": "ORD-20260924-ABCDE"}


def test_tool_call_request_empty_arguments_defaults():
    """ToolCallRequest defaults arguments to empty dict."""
    req = ToolCallRequest(tool_name="get_payment_status")
    assert req.arguments == {}


def test_tool_call_request_empty_tool_name_rejected():
    """Empty tool_name must be rejected (min_length=1)."""
    with pytest.raises(ValidationError):
        ToolCallRequest(tool_name="")


def test_tool_call_request_extra_field_rejected():
    """Extra fields are forbidden."""
    with pytest.raises(ValidationError):
        ToolCallRequest(tool_name="get_order_status", unauthorized_field="injection")


# ---------------------------------------------------------------------------
# ToolResult
# ---------------------------------------------------------------------------


def test_tool_result_success():
    """ToolResult correctly represents a successful tool execution."""
    result = ToolResult(
        tool_name="get_order_status",
        success=True,
        data={"order_number": "ORD-001", "order_status": "DELIVERED"},
        error=None,
    )
    assert result.success is True
    assert result.data["order_status"] == "DELIVERED"
    assert result.error is None


def test_tool_result_failure():
    """ToolResult correctly represents a failed tool execution."""
    result = ToolResult(
        tool_name="get_order_status",
        success=False,
        data=None,
        error="Order 'ORD-999' not found.",
    )
    assert result.success is False
    assert result.data is None
    assert "not found" in result.error


def test_tool_result_model_dump():
    """ToolResult.model_dump() produces a plain dict suitable for JSON serialization."""
    result = ToolResult(
        tool_name="get_payment_status",
        success=True,
        data={"payment_status": "SUCCESS"},
        error=None,
    )
    dumped = result.model_dump()
    assert isinstance(dumped, dict)
    assert dumped["tool_name"] == "get_payment_status"
    assert dumped["success"] is True


# ---------------------------------------------------------------------------
# OrderStatusData
# ---------------------------------------------------------------------------


def test_order_status_data_valid():
    """OrderStatusData accepts all required fields."""
    data = OrderStatusData(
        order_number="ORD-20260924-ABCDE",
        order_status="CANCELLED",
        total_amount="2000.00",
        currency="INR",
        item_count=3,
        created_at="2026-09-24T10:30:00+00:00",
    )
    assert data.order_status == "CANCELLED"
    assert data.currency == "INR"
    assert data.item_count == 3


def test_order_status_data_model_dump():
    """OrderStatusData.model_dump() includes all fields."""
    data = OrderStatusData(
        order_number="ORD-001",
        order_status="PLACED",
        total_amount="500.00",
        currency="INR",
        item_count=1,
        created_at="2026-01-01T00:00:00+00:00",
    )
    dumped = data.model_dump()
    assert "order_number" in dumped
    assert "item_count" in dumped
    # Sensitive internal fields must NOT be present
    assert "customer_id" not in dumped
    assert "id" not in dumped


# ---------------------------------------------------------------------------
# PaymentStatusData
# ---------------------------------------------------------------------------


def test_payment_status_data_valid():
    """PaymentStatusData accepts all required fields."""
    data = PaymentStatusData(
        order_number="ORD-20260924-ABCDE",
        payment_status="REFUND_INITIATED",
        amount="2000.00",
        currency="INR",
        payment_method="UPI",
        transaction_reference="TXN-ABCDE12345",
    )
    assert data.payment_status == "REFUND_INITIATED"
    assert data.payment_method == "UPI"


def test_payment_status_data_model_dump_excludes_sensitive():
    """PaymentStatusData must NOT expose gateway_response_json or internal IDs."""
    data = PaymentStatusData(
        order_number="ORD-001",
        payment_status="SUCCESS",
        amount="1000.00",
        currency="INR",
        payment_method="CREDIT_CARD",
        transaction_reference="TXN-123456",
    )
    dumped = data.model_dump()
    assert "gateway_response_json" not in dumped
    assert "order_id" not in dumped
    assert "id" not in dumped
    assert "transaction_reference" in dumped
