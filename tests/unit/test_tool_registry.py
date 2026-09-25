"""Unit tests for Phase 11: Bounded Tool Registry (dispatch_tool, get_tool_descriptions).

Tests cover:
- get_tool_descriptions returns expected structure (no schema/auth details leaked)
- dispatch_tool rejects unknown tool names
- dispatch_tool validates arguments via Pydantic before execution
- dispatch_tool calls the executor with correct arguments
- dispatch_tool propagates executor errors as ToolResult failures
- MAX_TOOL_CALLS constant is correctly defined
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.app.schemas.tools import GetOrderStatusInput, ToolCallRequest, ToolResult
from backend.app.services.tool_registry import (
    MAX_TOOL_CALLS,
    TOOL_REGISTRY,
    dispatch_tool,
    get_tool_descriptions,
)


# ---------------------------------------------------------------------------
# get_tool_descriptions
# ---------------------------------------------------------------------------


def test_get_tool_descriptions_returns_all_registered_tools():
    """Returns a list containing one entry per registered tool."""
    descriptions = get_tool_descriptions()
    registered_names = set(TOOL_REGISTRY.keys())
    returned_names = {d["tool_name"] for d in descriptions}
    assert registered_names == returned_names


def test_get_tool_descriptions_structure():
    """Each description entry has exactly 'tool_name' and 'description' keys."""
    descriptions = get_tool_descriptions()
    for entry in descriptions:
        assert set(entry.keys()) == {"tool_name", "description"}
        assert isinstance(entry["tool_name"], str)
        assert isinstance(entry["description"], str)
        assert len(entry["description"]) > 0


def test_get_tool_descriptions_does_not_expose_internals():
    """Tool descriptions must NOT expose schema class, executor, or auth details."""
    descriptions = get_tool_descriptions()
    for entry in descriptions:
        # No Python class references or auth instructions in the description
        assert "input_schema_cls" not in str(entry)
        assert "executor" not in str(entry)
        assert "database" not in entry["description"].lower()
        assert "current_user" not in entry["description"]


def test_get_tool_descriptions_get_order_status_present():
    """get_order_status must be registered and have a non-empty description."""
    descriptions = get_tool_descriptions()
    names = [d["tool_name"] for d in descriptions]
    assert "get_order_status" in names


def test_get_tool_descriptions_get_payment_status_present():
    """get_payment_status must be registered and have a non-empty description."""
    descriptions = get_tool_descriptions()
    names = [d["tool_name"] for d in descriptions]
    assert "get_payment_status" in names


# ---------------------------------------------------------------------------
# MAX_TOOL_CALLS
# ---------------------------------------------------------------------------


def test_max_tool_calls_is_positive_integer():
    """MAX_TOOL_CALLS is a positive integer guarding against runaway loops."""
    assert isinstance(MAX_TOOL_CALLS, int)
    assert MAX_TOOL_CALLS > 0
    assert MAX_TOOL_CALLS <= 10  # Sanity upper bound


# ---------------------------------------------------------------------------
# dispatch_tool — unknown tool rejection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_tool_unknown_tool_returns_error_result():
    """An unregistered tool name is rejected without execution."""
    request = ToolCallRequest(
        tool_name="drop_all_tables",  # Malicious / unknown tool
        arguments={},
    )
    mock_user = MagicMock()
    mock_db = AsyncMock()

    result = await dispatch_tool(request, current_user=mock_user, db=mock_db)

    assert result.success is False
    assert result.data is None
    assert "not registered" in result.error
    assert result.tool_name == "drop_all_tables"


@pytest.mark.asyncio
async def test_dispatch_tool_empty_tool_name_rejected():
    """Empty string is an invalid tool name (caught by Pydantic min_length)."""
    with pytest.raises(Exception):
        ToolCallRequest(tool_name="", arguments={})


# ---------------------------------------------------------------------------
# dispatch_tool — Pydantic argument validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_tool_invalid_arguments_returns_error_result():
    """Pydantic validation error on tool arguments produces a ToolResult error."""
    request = ToolCallRequest(
        tool_name="get_order_status",
        arguments={"order_number": ""},  # Fails min_length=1 on GetOrderStatusInput
    )
    mock_user = MagicMock()
    mock_db = AsyncMock()

    result = await dispatch_tool(request, current_user=mock_user, db=mock_db)

    assert result.success is False
    assert "validation error" in result.error.lower()
    assert result.tool_name == "get_order_status"


@pytest.mark.asyncio
async def test_dispatch_tool_missing_required_argument_returns_error():
    """Missing required argument (order_number) produces a validation error ToolResult."""
    request = ToolCallRequest(
        tool_name="get_payment_status",
        arguments={},  # order_number is required but missing
    )
    mock_user = MagicMock()
    mock_db = AsyncMock()

    result = await dispatch_tool(request, current_user=mock_user, db=mock_db)

    assert result.success is False
    assert "validation error" in result.error.lower()


@pytest.mark.asyncio
async def test_dispatch_tool_extra_argument_rejected():
    """Extra arguments rejected by GetOrderStatusInput (extra='forbid') produce a validation error."""
    request = ToolCallRequest(
        tool_name="get_order_status",
        arguments={
            "order_number": "ORD-001",
            "injected_field": "malicious_payload",  # Extra field
        },
    )
    mock_user = MagicMock()
    mock_db = AsyncMock()

    result = await dispatch_tool(request, current_user=mock_user, db=mock_db)

    assert result.success is False
    assert "validation error" in result.error.lower()


# ---------------------------------------------------------------------------
# dispatch_tool — successful execution path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_tool_delegates_to_executor():
    """dispatch_tool calls the registered executor with validated args, user, and db."""
    expected_result = ToolResult(
        tool_name="get_order_status",
        success=True,
        data={"order_number": "ORD-001", "order_status": "DELIVERED"},
        error=None,
    )
    mock_executor = AsyncMock(return_value=expected_result)
    mock_user = MagicMock()
    mock_db = AsyncMock()

    request = ToolCallRequest(
        tool_name="get_order_status",
        arguments={"order_number": "ORD-001"},
    )

    # Patch only the executor in the registry entry
    with patch.dict(
        TOOL_REGISTRY,
        {
            "get_order_status": TOOL_REGISTRY["get_order_status"]._replace(
                executor=mock_executor
            )
        },
    ):
        result = await dispatch_tool(request, current_user=mock_user, db=mock_db)

    assert result.success is True
    assert result.data["order_status"] == "DELIVERED"
    mock_executor.assert_awaited_once_with(
        order_number="ORD-001",
        current_user=mock_user,
        db=mock_db,
    )


# ---------------------------------------------------------------------------
# dispatch_tool — executor exception safety net
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_tool_executor_exception_returns_error_result():
    """An unexpected exception in the executor is caught and returned as ToolResult error."""
    mock_executor = AsyncMock(side_effect=RuntimeError("DB connection lost"))
    mock_user = MagicMock()
    mock_db = AsyncMock()

    request = ToolCallRequest(
        tool_name="get_order_status",
        arguments={"order_number": "ORD-001"},
    )

    with patch.dict(
        TOOL_REGISTRY,
        {
            "get_order_status": TOOL_REGISTRY["get_order_status"]._replace(
                executor=mock_executor
            )
        },
    ):
        result = await dispatch_tool(request, current_user=mock_user, db=mock_db)

    assert result.success is False
    assert "RuntimeError" in result.error
    assert result.data is None
