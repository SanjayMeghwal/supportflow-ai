"""Unit tests for RAGAS-style claim extraction, groundedness, and faithfulness verification."""

import pytest
from backend.app.evaluation.evaluators import FaithfulnessEvaluator
from backend.app.evaluation.metrics import (
    compute_faithfulness,
    extract_claims,
    verify_claim_against_context,
)
from backend.app.evaluation.schemas import EvaluationSample
from backend.app.services.llm import MockLLMService


# ============================================================================
# 1. CLAIM EXTRACTION
# ============================================================================


def test_extract_claims_basic():
    text = (
        "We offer a 30-day refund policy on all purchases. "
        "Refunds take 5 to 7 business days to process. "
        "Items must be returned in original packaging."
    )
    claims = extract_claims(text)
    assert len(claims) == 3
    assert any("30-day refund policy" in c for c in claims)
    assert any("5 to 7 business days" in c for c in claims)


def test_extract_claims_filters_fillers():
    text = (
        "Hello! Thank you for reaching out. "
        "You can reset your password from the login screen. "
        "Please let me know if you need anything else! "
        "Have a great day."
    )
    claims = extract_claims(text)
    # The conversational greetings and closings should be filtered out
    assert len(claims) == 1
    assert "reset your password" in claims[0]


def test_extract_claims_markdown_bullets():
    text = (
        "- Passwords must be at least 12 characters long.\n"
        "- They must contain at least one uppercase letter.\n"
        "- They must contain at least one special character."
    )
    claims = extract_claims(text)
    assert len(claims) == 3
    for claim in claims:
        assert not claim.startswith("-")


# ============================================================================
# 2. VERIFY CLAIM AGAINST CONTEXT
# ============================================================================


def test_verify_claim_exact_match():
    context = "We offer a 30-day money-back guarantee on all standard purchases."
    claim = "We offer a 30-day money-back guarantee on all standard purchases."
    is_supported, snippet, reasoning = verify_claim_against_context(claim, context)
    assert is_supported is True


def test_verify_claim_high_overlap():
    context = (
        "Customers may cancel their subscription at any time via Account Settings. "
        "Access will continue until the end of the current billing cycle."
    )
    claim = "You can cancel your subscription in Account Settings and keep access until the billing cycle ends."
    is_supported, snippet, reasoning = verify_claim_against_context(claim, context)
    assert is_supported is True


def test_verify_claim_number_mismatch_hallucination():
    context = "Refunds are processed within 30 days of purchase."
    # Hallucinated number: 90 days instead of 30 days
    claim = "Refunds are processed within 90 days of purchase."
    is_supported, snippet, reasoning = verify_claim_against_context(claim, context)
    assert is_supported is False
    assert "numbers" in reasoning.lower() or "not found" in reasoning.lower()


def test_verify_claim_empty_context():
    claim = "Our company offers free express shipping on all orders."
    is_supported, snippet, reasoning = verify_claim_against_context(claim, "")
    assert is_supported is False


# ============================================================================
# 3. FAITHFULNESS COMPUTATION
# ============================================================================


def test_faithfulness_fully_supported():
    context = (
        "Standard shipping takes 3 to 5 business days. "
        "Express courier delivery takes 1 to 2 business days."
    )
    answer = (
        "Standard shipping typically takes 3 to 5 business days. "
        "Express courier takes 1 to 2 business days."
    )
    score, claims = compute_faithfulness(answer, context)
    assert score == 1.0
    assert len(claims) == 2
    assert all(c.supported for c in claims)


def test_faithfulness_partially_supported():
    context = "Standard shipping takes 3 to 5 business days."
    answer = (
        "Standard shipping takes 3 to 5 business days. "
        "All shipments include free gold-plated gift boxes."  # Hallucinated claim
    )
    score, claims = compute_faithfulness(answer, context)
    assert score == 0.5
    assert len(claims) == 2
    assert claims[0].supported is True
    assert claims[1].supported is False


def test_faithfulness_unsupported_all():
    context = "We only sell digital software licenses."
    answer = "We will deliver physical hardware servers to your datacenter in London within 48 hours."
    score, claims = compute_faithfulness(answer, context)
    assert score == 0.0
    assert any(not c.supported for c in claims)


def test_faithfulness_unanswerable_refusal():
    context = ""
    answer = "I do not have sufficient information in the knowledge base to answer your question."
    score, claims = compute_faithfulness(answer, context, is_answerable=False)
    # Refusal without hallucinating is 100% faithful
    assert score == 1.0


# ============================================================================
# 4. FAITHFULNESS EVALUATOR (DETERMINISTIC & MOCK LLM JUDGE)
# ============================================================================


@pytest.mark.asyncio
async def test_faithfulness_evaluator_deterministic():
    evaluator = FaithfulnessEvaluator(llm_service=None)
    sample = EvaluationSample(
        id="s1",
        question="What is the refund timeframe?",
        reference_answer="30 days",
        reference_context=["Refunds are available within 30 days."],
        category="refund",
    )
    score, claims = await evaluator.evaluate_async(
        generated_answer="Refunds are available within 30 days.",
        retrieved_contexts=["Refunds are available within 30 days."],
        sample=sample,
    )
    assert score == 1.0
    assert len(claims) == 1
    assert claims[0].supported is True


@pytest.mark.asyncio
async def test_faithfulness_evaluator_with_mock_llm_judge():
    mock_llm_response = (
        '[{"claim_index": 1, "supported": true, "reasoning": "Directly stated in context."}]'
    )
    mock_llm = MockLLMService(default_response=mock_llm_response)
    evaluator = FaithfulnessEvaluator(llm_service=mock_llm)

    sample = EvaluationSample(
        id="s1",
        question="What is the refund timeframe?",
        reference_answer="30 days",
        category="refund",
    )
    score, claims = await evaluator.evaluate_async(
        generated_answer="Customers can request a refund within 30 days.",
        retrieved_contexts=["Refunds are permitted within 30 days."],
        sample=sample,
    )
    assert score == 1.0
    assert len(claims) == 1
    assert claims[0].supported is True
    assert "Directly stated in context" in claims[0].reasoning


@pytest.mark.asyncio
async def test_faithfulness_evaluator_llm_fallback_on_invalid_json():
    # If LLM produces non-JSON garbage, evaluator safely falls back to deterministic NLP
    mock_llm = MockLLMService(default_response="SORRY I CANNOT OUTPUT JSON")
    evaluator = FaithfulnessEvaluator(llm_service=mock_llm)

    sample = EvaluationSample(
        id="s1",
        question="What is the refund timeframe?",
        reference_answer="30 days",
        category="refund",
    )
    score, claims = await evaluator.evaluate_async(
        generated_answer="Refunds are processed within 30 days.",
        retrieved_contexts=["Refunds are processed within 30 days."],
        sample=sample,
    )
    # Fallback to deterministic verification succeeds
    assert score == 1.0
    assert len(claims) == 1
    assert claims[0].supported is True
