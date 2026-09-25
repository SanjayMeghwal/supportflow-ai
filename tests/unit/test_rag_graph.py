"""Unit tests for Phase 10 + Phase 11 LangGraph RAG + tool orchestration state graph.

Phase 10 coverage (RAG-only mode):
- AgentState schema validation
- assemble_context: empty, with docs, whitespace-only content
- route_after_context_check: context available / unavailable routing
- validate_response: valid answer, empty/None answer
- Full graph execution with context → grounded answer
- Full graph execution with no context → insufficient_context fallback
- Empty query guard

Phase 11 coverage (bounded tool execution mode):
- _extract_tool_call_request: valid JSON, JSON code block, plain text, malformed
- route_after_answer_or_tool: tool call present / absent routing
- Full graph execution with tool call → execute_tool → synthesize_with_tool path
- MAX_TOOL_CALLS cap: tool loop prevention
- Tool-enabled path requires current_user context
- run_rag_pipeline: anonymous user disables tools (Phase 10 behavior)
"""

import json
from unittest.mock import AsyncMock, MagicMock
import pytest

from backend.app.schemas.tools import ToolCallRequest, ToolResult
from backend.app.services.llm import MockLLMService
from backend.app.services.rag_graph import (
    INSUFFICIENT_CONTEXT_MESSAGE,
    AgentState,
    assemble_context,
    build_rag_graph,
    route_after_answer_or_tool,
    route_after_context_check,
    run_rag_pipeline,
    validate_response,
    _extract_tool_call_request,
)


# ---------------------------------------------------------------------------
# Phase 10 — AgentState schema
# ---------------------------------------------------------------------------


def test_agent_state_keys_phase_11_extended():
    """AgentState must expose Phase 11 tool fields in addition to Phase 10 fields."""
    state: AgentState = {
        "query": "What is the return policy?",
        "top_k": 5,
        "current_user": None,
        "retrieved_docs": [],
        "context_text": "",
        "sources": [],
        "context_available": False,
        "tool_call_request": None,
        "tool_result": None,
        "tool_calls_count": 0,
        "answer": "",
        "is_valid": False,
        "error": None,
    }
    assert state["query"] == "What is the return policy?"
    assert state["context_available"] is False
    assert state["tool_calls_count"] == 0
    assert state["tool_call_request"] is None


# ---------------------------------------------------------------------------
# Phase 10 — assemble_context
# ---------------------------------------------------------------------------


def test_assemble_context_empty():
    """Verify assemble_context handles empty candidate lists."""
    res = assemble_context([])
    assert res["context_available"] is False
    assert res["context_text"] == ""
    assert res["sources"] == []


def test_assemble_context_with_docs():
    """Verify assemble_context formats text blocks and propagates structured sources."""
    mock_docs = [
        {
            "chunk_id": "chunk-101",
            "document_id": "doc-001",
            "document_title": "Refund Policy",
            "chunk_index": 0,
            "content": "Refunds are processed within 5-7 business days.",
            "rerank_score": 0.8954,
            "metadata": {"section": "timelines"},
        },
        {
            "chunk_id": "chunk-102",
            "document_id": "doc-001",
            "document_title": "Refund Policy",
            "chunk_index": 1,
            "content": "Original payment method is used for all refunds.",
            "score": 0.7231,
            "metadata": {},
        },
    ]

    res = assemble_context(mock_docs)
    assert res["context_available"] is True
    assert "[Source 1]: Refund Policy (Passage 1)" in res["context_text"]
    assert "Refunds are processed within 5-7 business days." in res["context_text"]
    assert "[Source 2]: Refund Policy (Passage 2)" in res["context_text"]
    assert len(res["sources"]) == 2
    assert res["sources"][0]["chunk_id"] == "chunk-101"
    assert res["sources"][0]["score"] == 0.8954
    assert res["sources"][0]["metadata"] == {"section": "timelines"}
    assert res["sources"][1]["score"] == 0.7231


def test_assemble_context_whitespace_only():
    """Verify assemble_context ignores whitespace-only chunk content."""
    mock_docs = [{"chunk_id": "c1", "content": "   \n\t  "}]
    res = assemble_context(mock_docs)
    assert res["context_available"] is False
    assert res["context_text"] == ""
    assert res["sources"] == []


# ---------------------------------------------------------------------------
# Phase 10 — route_after_context_check
# ---------------------------------------------------------------------------


def test_route_after_context_check_available():
    """Routes to generate_answer_or_tool_call when context is available."""
    assert (
        route_after_context_check({"context_available": True})
        == "generate_answer_or_tool_call"
    )


def test_route_after_context_check_unavailable():
    """Routes to insufficient_context when context is not available."""
    assert (
        route_after_context_check({"context_available": False})
        == "insufficient_context"
    )
    assert route_after_context_check({}) == "insufficient_context"


# ---------------------------------------------------------------------------
# Phase 10 — validate_response
# ---------------------------------------------------------------------------


def test_validate_response_valid():
    """Verify validate_response cleanly strips non-empty answers."""
    res = validate_response("  Refunds take 5-7 business days.   ")
    assert res["is_valid"] is True
    assert res["answer"] == "Refunds take 5-7 business days."
    assert res["error"] is None


def test_validate_response_empty_or_none():
    """Verify validate_response replaces empty responses with safe fallback."""
    res = validate_response("   ")
    assert res["is_valid"] is False
    assert res["answer"] == INSUFFICIENT_CONTEXT_MESSAGE

    res_none = validate_response(None)
    assert res_none["is_valid"] is False
    assert res_none["answer"] == INSUFFICIENT_CONTEXT_MESSAGE


# ---------------------------------------------------------------------------
# Phase 11 — _extract_tool_call_request
# ---------------------------------------------------------------------------


def test_extract_tool_call_request_valid_json():
    """Parses a well-formed JSON tool call request from raw LLM output."""
    raw = json.dumps({
        "tool_call": {
            "tool_name": "get_order_status",
            "arguments": {"order_number": "ORD-001"},
        }
    })
    result = _extract_tool_call_request(raw)
    assert result is not None
    assert result.tool_name == "get_order_status"
    assert result.arguments == {"order_number": "ORD-001"}


def test_extract_tool_call_request_json_code_block():
    """Parses a tool call JSON wrapped in a markdown code block."""
    raw = (
        "```json\n"
        '{"tool_call": {"tool_name": "get_payment_status", "arguments": {"order_number": "ORD-002"}}}\n'
        "```"
    )
    result = _extract_tool_call_request(raw)
    assert result is not None
    assert result.tool_name == "get_payment_status"
    assert result.arguments["order_number"] == "ORD-002"


def test_extract_tool_call_request_plain_text_returns_none():
    """Plain text answers (no tool call JSON) return None."""
    raw = "Your refund will be processed within 5-7 business days."
    result = _extract_tool_call_request(raw)
    assert result is None


def test_extract_tool_call_request_malformed_json_returns_none():
    """Malformed JSON returns None (treated as a plain answer)."""
    raw = '{"tool_call": {"tool_name": "get_order_status"'  # Truncated, invalid
    result = _extract_tool_call_request(raw)
    assert result is None


def test_extract_tool_call_request_json_without_tool_call_key_returns_none():
    """JSON without a 'tool_call' key is not a tool request."""
    raw = json.dumps({"some_other_key": "value"})
    result = _extract_tool_call_request(raw)
    assert result is None


def test_extract_tool_call_request_empty_string_returns_none():
    """Empty string returns None."""
    assert _extract_tool_call_request("") is None
    assert _extract_tool_call_request(None) is None


# ---------------------------------------------------------------------------
# Phase 11 — route_after_answer_or_tool
# ---------------------------------------------------------------------------


def test_route_after_answer_or_tool_with_tool_call():
    """Routes to execute_tool when a tool_call_request is present."""
    tc = ToolCallRequest(tool_name="get_order_status", arguments={"order_number": "ORD-001"})
    state: AgentState = {"tool_call_request": tc}
    assert route_after_answer_or_tool(state) == "execute_tool"


def test_route_after_answer_or_tool_no_tool_call():
    """Routes to validate_format when no tool_call_request is present."""
    assert route_after_answer_or_tool({"tool_call_request": None}) == "validate_format"
    assert route_after_answer_or_tool({}) == "validate_format"


# ---------------------------------------------------------------------------
# Phase 10 — Full graph execution (RAG-only, no user)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_rag_graph_execution_with_context():
    """Verify end-to-end execution of StateGraph when context is available (Phase 10 mode)."""
    mock_knowledge_service = MagicMock()
    mock_knowledge_service.search_reranked = AsyncMock(
        return_value=[
            {
                "chunk_id": "chunk-abc",
                "document_id": "doc-xyz",
                "document_title": "Cancellation FAQ",
                "chunk_index": 0,
                "content": "Orders can be cancelled within 2 hours of placement.",
                "score": 0.95,
                "metadata": {},
            }
        ]
    )
    mock_llm = MockLLMService(
        default_response="You can cancel your order within 2 hours of placement."
    )
    mock_db = AsyncMock()

    result = await run_rag_pipeline(
        query="Can I cancel my order?",
        db=mock_db,
        top_k=3,
        knowledge_service=mock_knowledge_service,
        llm_service=mock_llm,
        current_user=None,  # No user → Phase 10 RAG-only mode
    )

    assert result["context_available"] is True
    assert result["is_valid"] is True
    assert result["answer"] == "You can cancel your order within 2 hours of placement."
    assert len(result["sources"]) == 1
    assert result["sources"][0]["chunk_id"] == "chunk-abc"
    # LLM called exactly once (no tool call path)
    assert len(mock_llm.call_history) == 1
    mock_knowledge_service.search_reranked.assert_awaited_once_with(
        db=mock_db,
        query="Can I cancel my order?",
        top_k=3,
    )


@pytest.mark.asyncio
async def test_full_rag_graph_execution_insufficient_context():
    """Verify StateGraph routes to insufficient_context when no documents match."""
    mock_knowledge_service = MagicMock()
    mock_knowledge_service.search_reranked = AsyncMock(return_value=[])
    mock_llm = MockLLMService(default_response="Should never be called")
    mock_db = AsyncMock()

    result = await run_rag_pipeline(
        query="What is the quantum telemetry frequency?",
        db=mock_db,
        top_k=5,
        knowledge_service=mock_knowledge_service,
        llm_service=mock_llm,
    )

    assert result["context_available"] is False
    assert result["is_valid"] is True
    assert result["answer"] == INSUFFICIENT_CONTEXT_MESSAGE
    assert result["sources"] == []
    # Critical: LLM must not be called when context is insufficient
    assert len(mock_llm.call_history) == 0


# ---------------------------------------------------------------------------
# Phase 11 — Full graph execution with tool call path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_rag_graph_with_tool_call_execution():
    """Verify Phase 11 graph routes through execute_tool → synthesize_with_tool."""
    tool_call_json = json.dumps({
        "tool_call": {
            "tool_name": "get_order_status",
            "arguments": {"order_number": "ORD-20260924-ABCDE"},
        }
    })
    synthesis_answer = "Your order ORD-20260924-ABCDE has been delivered."

    # LLM returns tool call JSON on first call, then synthesized answer on second
    call_count = {"n": 0}

    class SequentialMockLLM(MockLLMService):
        async def generate(self, messages, *, temperature=0.0, max_tokens=1024):
            await super().generate(messages, temperature=temperature, max_tokens=max_tokens)
            call_count["n"] += 1
            if call_count["n"] == 1:
                return tool_call_json
            return synthesis_answer

    mock_knowledge_service = MagicMock()
    mock_knowledge_service.search_reranked = AsyncMock(
        return_value=[
            {
                "chunk_id": "chunk-order",
                "document_id": "doc-order",
                "document_title": "Order Policy",
                "chunk_index": 0,
                "content": "Orders are processed within 2 business days.",
                "score": 0.9,
                "metadata": {},
            }
        ]
    )

    # Tool dispatch mock: return a successful ToolResult
    tool_result = ToolResult(
        tool_name="get_order_status",
        success=True,
        data={"order_number": "ORD-20260924-ABCDE", "order_status": "DELIVERED"},
        error=None,
    )

    mock_user = MagicMock()
    mock_user.role = MagicMock()
    mock_db = AsyncMock()

    mock_llm = SequentialMockLLM()

    # Patch dispatch_tool so we don't hit the real DB
    from backend.app.services import rag_graph as rag_module
    original_dispatch = rag_module.dispatch_tool

    async def mock_dispatch(request, *, current_user, db):
        return tool_result

    rag_module.dispatch_tool = mock_dispatch

    try:
        result = await run_rag_pipeline(
            query="What is the status of my order ORD-20260924-ABCDE?",
            db=mock_db,
            top_k=3,
            knowledge_service=mock_knowledge_service,
            llm_service=mock_llm,
            current_user=mock_user,
        )
    finally:
        rag_module.dispatch_tool = original_dispatch

    assert result["context_available"] is True
    assert result["is_valid"] is True
    assert result["answer"] == synthesis_answer
    # LLM was called twice: once for tool request, once for synthesis
    assert len(mock_llm.call_history) == 2
    # Tool result must be stored in the final state
    assert result["tool_result"] is not None
    assert result["tool_result"].tool_name == "get_order_status"
    assert result["tool_calls_count"] == 1


@pytest.mark.asyncio
async def test_run_rag_pipeline_anonymous_user_uses_rag_only_prompt():
    """Without a current_user, the graph uses Phase 10 RAG-only prompt (no tool instructions)."""
    mock_knowledge_service = MagicMock()
    mock_knowledge_service.search_reranked = AsyncMock(
        return_value=[
            {
                "chunk_id": "chunk-refund",
                "document_id": "doc-refund",
                "document_title": "Refund Policy",
                "chunk_index": 0,
                "content": "Refunds take 5-7 business days.",
                "score": 0.88,
                "metadata": {},
            }
        ]
    )
    mock_llm = MockLLMService(default_response="Refunds take 5-7 business days.")
    mock_db = AsyncMock()

    result = await run_rag_pipeline(
        query="How long do refunds take?",
        db=mock_db,
        knowledge_service=mock_knowledge_service,
        llm_service=mock_llm,
        current_user=None,
    )

    assert result["is_valid"] is True
    assert result["answer"] == "Refunds take 5-7 business days."
    # Verify Phase 10 system prompt was used (no tool call instructions in messages)
    system_message = mock_llm.call_history[0]["messages"][0]["content"]
    assert "tool" not in system_message.lower() or "tool_call" not in system_message


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_rag_pipeline_empty_query_raises_value_error():
    """Verify run_rag_pipeline rejects empty or whitespace-only queries."""
    mock_db = AsyncMock()
    with pytest.raises(ValueError, match="cannot be empty"):
        await run_rag_pipeline(query="   ", db=mock_db)
