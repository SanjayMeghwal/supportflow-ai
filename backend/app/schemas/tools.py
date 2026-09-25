"""Pydantic schemas for Phase 11 bounded AI tool request/response contracts.

Tool inputs are strongly typed and validated by Pydantic before any execution.
The LLM never constructs raw SQL or arbitrary code — it only produces a
ToolCallRequest which is validated and dispatched by the application.
"""

from typing import Any, Literal, Optional, Union
import uuid

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Tool Input Schemas (each tool has its own validated input type)
# ---------------------------------------------------------------------------


class GetOrderStatusInput(BaseModel):
    """Validated input for the get_order_status tool."""

    model_config = ConfigDict(extra="forbid")

    order_number: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="The unique order number (e.g. ORD-20260924-ABCDE)",
        examples=["ORD-20260924-ABCDE"],
    )


class GetPaymentStatusInput(BaseModel):
    """Validated input for the get_payment_status tool."""

    model_config = ConfigDict(extra="forbid")

    order_number: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="The unique order number whose payment status is being queried",
        examples=["ORD-20260924-ABCDE"],
    )


# ---------------------------------------------------------------------------
# Discriminated union of all valid tool inputs
# ---------------------------------------------------------------------------

ToolInput = Union[GetOrderStatusInput, GetPaymentStatusInput]

TOOL_NAMES = Literal["get_order_status", "get_payment_status"]


# ---------------------------------------------------------------------------
# Tool Call Request — what the LLM produces and the application validates
# ---------------------------------------------------------------------------


class ToolCallRequest(BaseModel):
    """Structured tool call request produced by the LLM and validated before execution.

    The LLM returns a JSON object matching this schema when it determines
    that a business tool is needed to answer the query.  The application
    validates this strictly — unknown tool names or invalid arguments are
    rejected without execution.
    """

    model_config = ConfigDict(extra="forbid")

    tool_name: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Name of the registered tool to invoke",
    )
    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description="Arguments to pass to the tool (validated against the tool's input schema)",
    )


# ---------------------------------------------------------------------------
# Tool Result — the sanitized output returned from tool execution
# ---------------------------------------------------------------------------


class ToolResult(BaseModel):
    """Structured result from a bounded tool execution.

    Tool results are the authoritative source of business data.
    The LLM receives this result as a fact and must not contradict it.
    """

    model_config = ConfigDict(from_attributes=True)

    tool_name: str = Field(description="Name of the tool that was executed")
    success: bool = Field(description="True if the tool executed successfully")
    data: Optional[dict[str, Any]] = Field(
        default=None,
        description="Sanitized result data from the tool (no raw ORM fields, no secrets)",
    )
    error: Optional[str] = Field(
        default=None,
        description="Human-readable error message if success is False",
    )


# ---------------------------------------------------------------------------
# Order status result payload (sanitized — no internal DB fields)
# ---------------------------------------------------------------------------


class OrderStatusData(BaseModel):
    """Sanitized order status data returned by the get_order_status tool."""

    model_config = ConfigDict(from_attributes=True)

    order_number: str
    order_status: str
    total_amount: str
    currency: str
    item_count: int
    created_at: str


# ---------------------------------------------------------------------------
# Payment status result payload (sanitized)
# ---------------------------------------------------------------------------


class PaymentStatusData(BaseModel):
    """Sanitized payment status data returned by the get_payment_status tool."""

    model_config = ConfigDict(from_attributes=True)

    order_number: str
    payment_status: str
    amount: str
    currency: str
    payment_method: str
    transaction_reference: str
