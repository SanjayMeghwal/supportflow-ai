"""Unit tests for Phase 12 — Human-In-The-Loop Review & Escalation Workflow.

Coverage:
  check_escalation_triggers:
    - No trigger → returns (False, None, SUCCESS)
    - Explicit human-request phrase → ESCALATED_GUARDRAIL
    - Legal/chargeback phrase → ESCALATED_GUARDRAIL
    - Tool failure → ESCALATED_GUARDRAIL
    - Tool denial (success=False) → ESCALATED_GUARDRAIL
    - Missing context → ESCALATED_LOW_CONFIDENCE
    - Low confidence score below threshold → ESCALATED_LOW_CONFIDENCE
    - Confidence score at threshold → no escalation
    - Confidence score above threshold → no escalation
    - Successful tool result does NOT escalate
    - Case-insensitive keyword detection

  ReviewStatus / ReviewAction enum values:
    - All expected variants present

  Pydantic schema validation (review.py):
    - ReviewApproveRequest: valid, extra field rejected
    - ReviewEditRequest: empty final_text rejected, valid accepted
    - ReviewRejectRequest: empty notes rejected
    - ReviewEscalateRequest: optional assign_to_agent_id

  rag_graph Phase 12 integration:
    - AgentState has escalation fields
    - Full pipeline: no escalation on successful grounded answer
    - Full pipeline: escalation triggered when context missing
    - Full pipeline: escalation triggered for guardrail keyword
    - Full pipeline: escalation triggered for failed tool
    - escalation_status is always populated (SUCCESS or escalated variant)

  review_service exceptions:
    - ReviewNotFoundError, ReviewAlreadyCompletedError, InvalidReviewActionError importable
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from backend.app.models.ai import AIRunStatus, ReviewAction, ReviewStatus
from backend.app.schemas.review import (
    ReviewApproveRequest,
    ReviewEditRequest,
    ReviewEscalateRequest,
    ReviewItemResponse,
    ReviewListResponse,
    ReviewRejectRequest,
)
from backend.app.schemas.tools import ToolResult
from backend.app.services.review_service import (
    CONFIDENCE_THRESHOLD,
    ESCALATION_PHRASES,
    InvalidReviewActionError,
    ReviewAlreadyCompletedError,
    ReviewNotFoundError,
    check_escalation_triggers,
)
from backend.app.services.rag_graph import (
    AgentState,
    build_rag_graph,
    run_rag_pipeline,
)
from backend.app.services.llm import MockLLMService


# ---------------------------------------------------------------------------
# check_escalation_triggers — baseline
# ---------------------------------------------------------------------------


def test_no_escalation_for_normal_query():
    """A normal, high-confidence, context-available query must NOT escalate."""
    should, reason, status = check_escalation_triggers(
        "What is your return policy?",
        context_available=True,
        confidence_score=0.90,
        tool_result=None,
    )
    assert should is False
    assert reason is None
    assert status == AIRunStatus.SUCCESS


def test_no_escalation_when_confidence_at_threshold():
    """Confidence exactly at the threshold must NOT escalate."""
    should, reason, status = check_escalation_triggers(
        "How do I track my order?",
        context_available=True,
        confidence_score=CONFIDENCE_THRESHOLD,
        tool_result=None,
    )
    assert should is False
    assert status == AIRunStatus.SUCCESS


def test_no_escalation_when_no_confidence_score():
    """When no confidence score is provided and context is available, no escalation."""
    should, reason, status = check_escalation_triggers(
        "Tell me about your warranty.",
        context_available=True,
        confidence_score=None,
        tool_result=None,
    )
    assert should is False
    assert status == AIRunStatus.SUCCESS


# ---------------------------------------------------------------------------
# check_escalation_triggers — ESCALATED_GUARDRAIL (human/legal keywords)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("phrase", [
    "talk to an agent",
    "speak to a human",
    "human please",
    "I want to speak to manager",
    "I need legal action",
    "chargeback",
    "dispute payment",
    "real person",
])
def test_escalation_guardrail_explicit_phrases(phrase: str):
    """Any guardrail phrase in the query must trigger ESCALATED_GUARDRAIL."""
    should, reason, status = check_escalation_triggers(
        f"I would like to {phrase} about my order",
        context_available=True,
        confidence_score=0.95,
        tool_result=None,
    )
    assert should is True
    assert status == AIRunStatus.ESCALATED_GUARDRAIL
    assert reason is not None
    assert len(reason) > 0


def test_escalation_guardrail_case_insensitive():
    """Keyword matching must be case-insensitive."""
    should, reason, status = check_escalation_triggers(
        "TALK TO AN AGENT NOW",
        context_available=True,
        confidence_score=0.99,
        tool_result=None,
    )
    assert should is True
    assert status == AIRunStatus.ESCALATED_GUARDRAIL


def test_escalation_guardrail_partial_match():
    """Keyword that appears as a substring in the query must be detected."""
    should, reason, status = check_escalation_triggers(
        "please connect me to a person who can help",
        context_available=True,
        confidence_score=0.85,
        tool_result=None,
    )
    assert should is True
    assert status == AIRunStatus.ESCALATED_GUARDRAIL


def test_escalation_phrases_tuple_is_nonempty():
    """The ESCALATION_PHRASES constant must contain at least the key trigger phrases."""
    assert len(ESCALATION_PHRASES) >= 5
    assert "talk to an agent" in ESCALATION_PHRASES
    assert "chargeback" in ESCALATION_PHRASES
    assert "legal action" in ESCALATION_PHRASES


# ---------------------------------------------------------------------------
# check_escalation_triggers — ESCALATED_GUARDRAIL (tool failure)
# ---------------------------------------------------------------------------


def test_escalation_guardrail_tool_failure():
    """A failed tool result must trigger ESCALATED_GUARDRAIL."""
    failed_result = ToolResult(
        tool_name="get_order_status",
        success=False,
        data=None,
        error="Order not found for user",
    )
    should, reason, status = check_escalation_triggers(
        "What is the status of order #123?",
        context_available=True,
        confidence_score=0.80,
        tool_result=failed_result,
    )
    assert should is True
    assert status == AIRunStatus.ESCALATED_GUARDRAIL
    assert "get_order_status" in reason


def test_escalation_guardrail_tool_denied():
    """A tool denied due to authorization must trigger ESCALATED_GUARDRAIL."""
    denied_result = ToolResult(
        tool_name="get_payment_status",
        success=False,
        data=None,
        error="Access denied: order does not belong to this user",
    )
    should, reason, status = check_escalation_triggers(
        "Show me my payment status",
        context_available=True,
        confidence_score=0.88,
        tool_result=denied_result,
    )
    assert should is True
    assert status == AIRunStatus.ESCALATED_GUARDRAIL


def test_no_escalation_for_successful_tool():
    """A successful tool result must NOT trigger escalation."""
    success_result = ToolResult(
        tool_name="get_order_status",
        success=True,
        data={"status": "SHIPPED"},
        error=None,
    )
    should, reason, status = check_escalation_triggers(
        "What is the status of order #123?",
        context_available=True,
        confidence_score=0.90,
        tool_result=success_result,
    )
    assert should is False
    assert status == AIRunStatus.SUCCESS


# ---------------------------------------------------------------------------
# check_escalation_triggers — ESCALATED_LOW_CONFIDENCE
# ---------------------------------------------------------------------------


def test_escalation_low_confidence_no_context():
    """Missing knowledge base context must trigger ESCALATED_LOW_CONFIDENCE."""
    should, reason, status = check_escalation_triggers(
        "What is the meaning of life?",
        context_available=False,
        confidence_score=None,
        tool_result=None,
    )
    assert should is True
    assert status == AIRunStatus.ESCALATED_LOW_CONFIDENCE
    assert "context" in reason.lower()


def test_escalation_low_confidence_score_below_threshold():
    """Score below threshold must trigger ESCALATED_LOW_CONFIDENCE."""
    should, reason, status = check_escalation_triggers(
        "How do I reset my password?",
        context_available=True,
        confidence_score=0.50,
        tool_result=None,
    )
    assert should is True
    assert status == AIRunStatus.ESCALATED_LOW_CONFIDENCE
    assert "0.50" in reason


def test_escalation_low_confidence_just_below_threshold():
    """Score just below 0.70 must escalate."""
    should, reason, status = check_escalation_triggers(
        "Generic question",
        context_available=True,
        confidence_score=0.6999,
        tool_result=None,
    )
    assert should is True
    assert status == AIRunStatus.ESCALATED_LOW_CONFIDENCE


def test_no_escalation_confidence_above_threshold():
    """Score above threshold must NOT escalate."""
    should, reason, status = check_escalation_triggers(
        "Generic question",
        context_available=True,
        confidence_score=0.71,
        tool_result=None,
    )
    assert should is False
    assert status == AIRunStatus.SUCCESS


# ---------------------------------------------------------------------------
# Priority order: guardrail takes precedence over low confidence
# ---------------------------------------------------------------------------


def test_guardrail_takes_priority_over_low_confidence():
    """If both guardrail and low-confidence conditions exist, guardrail wins."""
    should, reason, status = check_escalation_triggers(
        "I want to talk to an agent",
        context_available=False,
        confidence_score=0.20,
        tool_result=None,
    )
    assert should is True
    assert status == AIRunStatus.ESCALATED_GUARDRAIL


# ---------------------------------------------------------------------------
# ReviewStatus and ReviewAction enum validation
# ---------------------------------------------------------------------------


def test_review_status_enum_variants():
    """ReviewStatus must have all lifecycle variants."""
    assert ReviewStatus.PENDING == "PENDING"
    assert ReviewStatus.APPROVED == "APPROVED"
    assert ReviewStatus.EDITED == "EDITED"
    assert ReviewStatus.REJECTED == "REJECTED"
    assert ReviewStatus.ESCALATED == "ESCALATED"


def test_review_action_enum_variants():
    """ReviewAction must match the four human decisions."""
    assert ReviewAction.APPROVED == "APPROVED"
    assert ReviewAction.EDITED == "EDITED"
    assert ReviewAction.REJECTED == "REJECTED"
    assert ReviewAction.ESCALATED == "ESCALATED"


def test_ai_run_status_escalation_variants():
    """AIRunStatus must have escalated variants used by review service."""
    assert AIRunStatus.SUCCESS == "SUCCESS"
    assert AIRunStatus.ESCALATED_LOW_CONFIDENCE == "ESCALATED_LOW_CONFIDENCE"
    assert AIRunStatus.ESCALATED_GUARDRAIL == "ESCALATED_GUARDRAIL"
    assert AIRunStatus.FAILED == "FAILED"


# ---------------------------------------------------------------------------
# Pydantic schema validation — ReviewApproveRequest
# ---------------------------------------------------------------------------


def test_approve_request_valid_defaults():
    req = ReviewApproveRequest()
    assert req.notes is None
    assert req.resolve_ticket is False


def test_approve_request_with_notes():
    req = ReviewApproveRequest(notes="Looks good", resolve_ticket=True)
    assert req.notes == "Looks good"
    assert req.resolve_ticket is True


def test_approve_request_rejects_extra_fields():
    """extra=forbid must reject unknown fields from client."""
    with pytest.raises(Exception):
        ReviewApproveRequest(notes="ok", reviewer_id="some-uuid")


# ---------------------------------------------------------------------------
# Pydantic schema validation — ReviewEditRequest
# ---------------------------------------------------------------------------


def test_edit_request_valid():
    req = ReviewEditRequest(final_submitted_text="Here is the corrected response.")
    assert req.final_submitted_text == "Here is the corrected response."
    assert req.notes is None
    assert req.resolve_ticket is False


def test_edit_request_empty_text_rejected():
    with pytest.raises(Exception):
        ReviewEditRequest(final_submitted_text="")


def test_edit_request_rejects_extra_fields():
    with pytest.raises(Exception):
        ReviewEditRequest(final_submitted_text="ok", reviewer_id="injected")


# ---------------------------------------------------------------------------
# Pydantic schema validation — ReviewRejectRequest
# ---------------------------------------------------------------------------


def test_reject_request_valid():
    req = ReviewRejectRequest(feedback_notes="Draft was factually incorrect.")
    assert req.feedback_notes == "Draft was factually incorrect."


def test_reject_request_empty_notes_rejected():
    with pytest.raises(Exception):
        ReviewRejectRequest(feedback_notes="")


def test_reject_request_rejects_extra_fields():
    with pytest.raises(Exception):
        ReviewRejectRequest(feedback_notes="ok", reviewer_id="injected")


# ---------------------------------------------------------------------------
# Pydantic schema validation — ReviewEscalateRequest
# ---------------------------------------------------------------------------


def test_escalate_request_valid_no_assignment():
    req = ReviewEscalateRequest(feedback_notes="Needs senior agent review.")
    assert req.feedback_notes == "Needs senior agent review."
    assert req.assign_to_agent_id is None


def test_escalate_request_with_agent_assignment():
    agent_id = uuid.uuid4()
    req = ReviewEscalateRequest(
        feedback_notes="Assign to billing specialist.",
        assign_to_agent_id=agent_id,
    )
    assert req.assign_to_agent_id == agent_id


def test_escalate_request_empty_notes_rejected():
    with pytest.raises(Exception):
        ReviewEscalateRequest(feedback_notes="")


# ---------------------------------------------------------------------------
# review_service — exception classes importable and distinct
# ---------------------------------------------------------------------------


def test_review_exception_hierarchy():
    """All three service exceptions must be importable and distinct."""
    assert issubclass(ReviewNotFoundError, Exception)
    assert issubclass(ReviewAlreadyCompletedError, Exception)
    assert issubclass(InvalidReviewActionError, Exception)
    # All three must be distinct types
    assert ReviewNotFoundError is not ReviewAlreadyCompletedError
    assert ReviewAlreadyCompletedError is not InvalidReviewActionError


def test_review_exceptions_raise_correctly():
    with pytest.raises(ReviewNotFoundError):
        raise ReviewNotFoundError("test not found")
    with pytest.raises(ReviewAlreadyCompletedError):
        raise ReviewAlreadyCompletedError("already done")
    with pytest.raises(InvalidReviewActionError):
        raise InvalidReviewActionError("bad action")


# ---------------------------------------------------------------------------
# AgentState — Phase 12 escalation fields
# ---------------------------------------------------------------------------


def test_agent_state_has_phase12_escalation_fields():
    """AgentState TypedDict must expose all Phase 12 escalation fields."""
    state: AgentState = {
        "query": "test query",
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
        "escalation_triggered": False,
        "escalation_reason": None,
        "escalation_status": None,
    }
    # All three escalation keys must be accessible
    assert "escalation_triggered" in state
    assert "escalation_reason" in state
    assert "escalation_status" in state
    assert state["escalation_triggered"] is False
    assert state["escalation_reason"] is None
    assert state["escalation_status"] is None


# ---------------------------------------------------------------------------
# rag_graph — Phase 12 integration (full pipeline, mocked I/O)
# ---------------------------------------------------------------------------


def _make_mock_doc(score: float = 0.92) -> dict:
    return {
        "content": "Our return policy allows returns within 30 days.",
        "document_title": "Return Policy",
        "chunk_index": 0,
        "rerank_score": score,
        "chunk_id": str(uuid.uuid4()),
        "document_id": str(uuid.uuid4()),
        "metadata": {},
    }


@pytest.mark.asyncio
async def test_pipeline_no_escalation_high_confidence():
    """A successful, high-confidence, grounded answer must NOT trigger escalation."""
    mock_ks = MagicMock()
    mock_ks.search_reranked = AsyncMock(return_value=[_make_mock_doc(0.92)])

    mock_llm = MockLLMService(
        responses=["Our return policy allows returns within 30 days."]
    )
    mock_db = AsyncMock()

    result = await run_rag_pipeline(
        "What is the return policy?",
        db=mock_db,
        knowledge_service=mock_ks,
        llm_service=mock_llm,
        current_user=None,
    )

    assert result["escalation_triggered"] is False
    assert result["escalation_status"] == AIRunStatus.SUCCESS.value
    assert result["escalation_reason"] is None
    assert result["is_valid"] is True


@pytest.mark.asyncio
async def test_pipeline_escalation_missing_context():
    """When retrieval returns no docs, the pipeline must flag escalation."""
    mock_ks = MagicMock()
    mock_ks.search_reranked = AsyncMock(return_value=[])  # no docs

    mock_llm = MockLLMService(responses=["I cannot help."])
    mock_db = AsyncMock()

    result = await run_rag_pipeline(
        "What is the capital of Mars?",
        db=mock_db,
        knowledge_service=mock_ks,
        llm_service=mock_llm,
        current_user=None,
    )

    assert result["escalation_triggered"] is True
    assert result["escalation_status"] == AIRunStatus.ESCALATED_LOW_CONFIDENCE.value
    assert result["escalation_reason"] is not None


@pytest.mark.asyncio
async def test_pipeline_escalation_guardrail_keyword():
    """A query containing a guardrail phrase must produce ESCALATED_GUARDRAIL."""
    mock_ks = MagicMock()
    mock_ks.search_reranked = AsyncMock(return_value=[_make_mock_doc(0.95)])

    mock_llm = MockLLMService(
        responses=["I understand you want to speak with an agent."]
    )
    mock_db = AsyncMock()

    result = await run_rag_pipeline(
        "I want to talk to an agent about my order",
        db=mock_db,
        knowledge_service=mock_ks,
        llm_service=mock_llm,
        current_user=None,
    )

    assert result["escalation_triggered"] is True
    assert result["escalation_status"] == AIRunStatus.ESCALATED_GUARDRAIL.value


@pytest.mark.asyncio
async def test_pipeline_escalation_low_confidence_score():
    """A low reranker score must trigger ESCALATED_LOW_CONFIDENCE."""
    mock_ks = MagicMock()
    mock_ks.search_reranked = AsyncMock(return_value=[_make_mock_doc(0.40)])

    mock_llm = MockLLMService(responses=["Here is some low-confidence information."])
    mock_db = AsyncMock()

    result = await run_rag_pipeline(
        "Tell me about the obscure product specs",
        db=mock_db,
        knowledge_service=mock_ks,
        llm_service=mock_llm,
        current_user=None,
    )

    assert result["escalation_triggered"] is True
    assert result["escalation_status"] == AIRunStatus.ESCALATED_LOW_CONFIDENCE.value


@pytest.mark.asyncio
async def test_pipeline_escalation_status_always_set():
    """escalation_status must always be populated (never None) after pipeline run."""
    mock_ks = MagicMock()
    mock_ks.search_reranked = AsyncMock(return_value=[_make_mock_doc(0.85)])

    mock_llm = MockLLMService(responses=["The product ships in 3-5 business days."])
    mock_db = AsyncMock()

    result = await run_rag_pipeline(
        "How long does shipping take?",
        db=mock_db,
        knowledge_service=mock_ks,
        llm_service=mock_llm,
    )

    assert result["escalation_status"] is not None
    # Must be a valid AIRunStatus value
    valid_values = {s.value for s in AIRunStatus}
    assert result["escalation_status"] in valid_values


@pytest.mark.asyncio
async def test_pipeline_escalation_tool_failure(monkeypatch):
    """When a tool fails, the escalation node must fire ESCALATED_GUARDRAIL."""
    mock_ks = MagicMock()
    mock_ks.search_reranked = AsyncMock(return_value=[_make_mock_doc(0.88)])

    # LLM requests a tool call
    tool_call_json = '{"tool_call": {"tool_name": "get_order_status", "arguments": {"order_id": "ORD-999"}}}'
    # Second LLM call (synthesis) returns plain text
    mock_llm = MockLLMService(
        responses=[tool_call_json, "I could not retrieve your order status."]
    )

    failed_result = ToolResult(
        tool_name="get_order_status",
        success=False,
        data=None,
        error="Order ORD-999 not found",
    )

    mock_user = MagicMock()
    mock_user.id = uuid.uuid4()
    mock_user.role = MagicMock(value="SUPPORT_AGENT")
    mock_db = AsyncMock()

    # Patch dispatch_tool to return a failure
    with patch(
        "backend.app.services.rag_graph.dispatch_tool",
        new=AsyncMock(return_value=failed_result),
    ):
        result = await run_rag_pipeline(
            "What is the status of order ORD-999?",
            db=mock_db,
            knowledge_service=mock_ks,
            llm_service=mock_llm,
            current_user=mock_user,
        )

    assert result["escalation_triggered"] is True
    assert result["escalation_status"] == AIRunStatus.ESCALATED_GUARDRAIL.value
    assert "get_order_status" in result["escalation_reason"]


# ---------------------------------------------------------------------------
# ReviewListResponse and ReviewItemResponse schema
# ---------------------------------------------------------------------------


def test_review_list_response_empty():
    resp = ReviewListResponse(total=0, items=[])
    assert resp.total == 0
    assert resp.items == []


def test_review_item_response_serialization():
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    item = ReviewItemResponse(
        id=uuid.uuid4(),
        ticket_id=uuid.uuid4(),
        ai_run_id=uuid.uuid4(),
        status=ReviewStatus.PENDING,
        escalation_reason="Tool failed",
        original_ai_draft="Draft text here",
        created_at=now,
        updated_at=now,
    )
    assert item.status == ReviewStatus.PENDING
    assert item.reviewer_id is None
    assert item.action_taken is None
    assert item.resolved_at is None
    assert item.ticket_number is None
