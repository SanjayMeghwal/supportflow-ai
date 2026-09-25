"""Unit tests for Phase 10 LangGraph RAG orchestration state graph."""

from unittest.mock import AsyncMock, MagicMock
import pytest

from backend.app.services.llm import MockLLMService
from backend.app.services.rag_graph import (
    INSUFFICIENT_CONTEXT_MESSAGE,
    AgentState,
    assemble_context,
    build_rag_graph,
    generate_grounded_answer,
    route_after_context_check,
    run_rag_pipeline,
    validate_response,
)


def test_agent_state_keys():
    """Verify AgentState schema exposes all required fields."""
    state: AgentState = {
        "query": "What is the return policy?",
        "top_k": 5,
        "retrieved_docs": [],
        "context_text": "",
        "sources": [],
        "context_available": False,
        "answer": "",
        "is_valid": False,
        "error": None,
    }
    assert state["query"] == "What is the return policy?"
    assert state["context_available"] is False


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


def test_route_after_context_check():
    """Verify conditional edge router selects appropriate node based on context availability."""
    assert (
        route_after_context_check({"context_available": True})
        == "generate_answer"
    )
    assert (
        route_after_context_check({"context_available": False})
        == "insufficient_context"
    )
    assert route_after_context_check({}) == "insufficient_context"


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


@pytest.mark.asyncio
async def test_generate_grounded_answer():
    """Verify generate_grounded_answer structures grounding prompt correctly."""
    mock_llm = MockLLMService(default_response="Grounded mock answer.")
    answer = await generate_grounded_answer(
        llm_service=mock_llm,
        query="What is the refund timeline?",
        context_text="[Source 1]: Refunds take 5-7 days.",
    )

    assert answer == "Grounded mock answer."
    assert len(mock_llm.call_history) == 1
    messages = mock_llm.call_history[0]["messages"]
    assert messages[0]["role"] == "system"
    assert "strictly based on the provided reference context" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert "Reference Context:\n[Source 1]: Refunds take 5-7 days." in messages[1]["content"]
    assert "Customer Inquiry:\nWhat is the refund timeline?" in messages[1]["content"]


@pytest.mark.asyncio
async def test_full_rag_graph_execution_with_context():
    """Verify end-to-end execution of StateGraph when context is available."""
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
    )

    assert result["context_available"] is True
    assert result["is_valid"] is True
    assert result["answer"] == "You can cancel your order within 2 hours of placement."
    assert len(result["sources"]) == 1
    assert result["sources"][0]["chunk_id"] == "chunk-abc"
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


@pytest.mark.asyncio
async def test_run_rag_pipeline_empty_query_raises_value_error():
    """Verify run_rag_pipeline rejects empty or whitespace-only queries."""
    mock_db = AsyncMock()
    with pytest.raises(ValueError, match="cannot be empty"):
        await run_rag_pipeline(query="   ", db=mock_db)
