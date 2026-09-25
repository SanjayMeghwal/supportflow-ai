"""Phase 11: Bounded AI Tool Registry.

Design Principles
-----------------
1. The LLM does NOT call tools directly — it produces a ToolCallRequest JSON
   object, which the registry validates and dispatches.
2. Only tools that are explicitly registered in TOOL_REGISTRY may be executed.
3. All tool execution is subject to a MAX_TOOL_CALLS cap per pipeline run
   to prevent runaway loops.
4. Authorization is enforced inside every tool — the registry does not bypass it.
5. Tool input is parsed by Pydantic before execution — type errors surface as
   ToolResult errors (never uncaught exceptions to the LLM).

Security Invariants
-------------------
- No eval(), exec(), or arbitrary shell/SQL.
- Tools may ONLY access the database via the application's async session.
- Tool results are sanitized — no raw ORM objects, no secrets.
- The LLM cannot register, modify, or discover tools dynamically.
"""

from typing import Any, Callable, Awaitable, NamedTuple

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.user import User
from backend.app.schemas.tools import (
    GetOrderStatusInput,
    GetPaymentStatusInput,
    ToolCallRequest,
    ToolResult,
)
from backend.app.services.tools import get_order_status, get_payment_status

# Maximum number of tool calls allowed per pipeline run.
# Prevents infinite tool-call loops while still permitting chained lookups.
MAX_TOOL_CALLS: int = 3


# ---------------------------------------------------------------------------
# Internal registration record
# ---------------------------------------------------------------------------


class _RegistryEntry(NamedTuple):
    """Internal record for a registered tool."""

    description: str
    input_schema_cls: type  # Pydantic model class for this tool's input
    executor: Callable[..., Awaitable[ToolResult]]  # The async tool function


# ---------------------------------------------------------------------------
# Tool Registry — immutable at runtime
# ---------------------------------------------------------------------------
#
# To register a new tool:
#   1. Add its validated Pydantic input schema to schemas/tools.py.
#   2. Implement the async executor function in services/tools.py.
#   3. Add an entry to TOOL_REGISTRY below.
#
# The LLM cannot modify this registry.

TOOL_REGISTRY: dict[str, _RegistryEntry] = {
    "get_order_status": _RegistryEntry(
        description=(
            "Retrieve the current status of a customer order by order number. "
            "Use when the customer asks about their order status, shipping, or delivery."
        ),
        input_schema_cls=GetOrderStatusInput,
        executor=get_order_status,
    ),
    "get_payment_status": _RegistryEntry(
        description=(
            "Retrieve the payment status for a customer order by order number. "
            "Use when the customer asks about payment, billing, or refund status."
        ),
        input_schema_cls=GetPaymentStatusInput,
        executor=get_payment_status,
    ),
}


def get_tool_descriptions() -> list[dict[str, str]]:
    """Return a read-only list of tool names and descriptions for LLM context injection.

    This is the ONLY information surfaced to the LLM about available tools.
    It does NOT expose schema details, database access methods, or authorization logic.
    """
    return [
        {"tool_name": name, "description": entry.description}
        for name, entry in TOOL_REGISTRY.items()
    ]


async def dispatch_tool(
    request: ToolCallRequest,
    *,
    current_user: User,
    db: AsyncSession,
) -> ToolResult:
    """Validate and execute a bounded tool call request.

    Steps:
      1. Check that the requested tool_name is in the registry.
      2. Validate arguments against the tool's Pydantic input schema.
      3. Execute the tool with (current_user, db) — authorization is enforced inside.
      4. Return a ToolResult (success or error) — never raises exceptions to the graph.

    Parameters
    ----------
    request : ToolCallRequest
        The LLM-produced tool call request (already validated as a ToolCallRequest).
    current_user : User
        Authenticated user passed from the API layer — never derived from LLM output.
    db : AsyncSession
        Active database session — never constructed by the LLM.
    """
    tool_name = request.tool_name

    # 1. Check registry membership — unknown tools are rejected
    if tool_name not in TOOL_REGISTRY:
        return ToolResult(
            tool_name=tool_name,
            success=False,
            data=None,
            error=f"Tool '{tool_name}' is not registered and cannot be executed.",
        )

    entry = TOOL_REGISTRY[tool_name]

    # 2. Validate input arguments via Pydantic
    try:
        validated_input = entry.input_schema_cls(**request.arguments)
    except ValidationError as exc:
        return ToolResult(
            tool_name=tool_name,
            success=False,
            data=None,
            error=f"Invalid tool arguments: {exc.error_count()} validation error(s). "
                  f"First error: {exc.errors()[0].get('msg', 'unknown')}",
        )

    # 3. Execute the tool — authorization is enforced inside the executor
    try:
        return await entry.executor(
            **validated_input.model_dump(),
            current_user=current_user,
            db=db,
        )
    except Exception as exc:  # pragma: no cover — safety net for unexpected errors
        return ToolResult(
            tool_name=tool_name,
            success=False,
            data=None,
            error=f"Tool execution failed unexpectedly: {type(exc).__name__}",
        )
