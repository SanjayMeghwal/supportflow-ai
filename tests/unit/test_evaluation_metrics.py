"""Unit tests for retrieval metrics, context relevance, answer relevance, and aggregation."""

import pytest
from backend.app.evaluation.metrics import (
    aggregate_evaluation_results,
    compute_answer_relevance,
    compute_context_relevance,
    compute_hit_rate,
    compute_mrr,
    compute_precision_at_k,
    compute_recall_at_k,
    evaluate_retrieval,
)
from backend.app.evaluation.schemas import (
    RAGMetrics,
    RetrievalMetrics,
    SampleEvaluationResult,
)


# ============================================================================
# 1. PRECISION@K TESTS
# ============================================================================


def test_precision_at_k_perfect():
    retrieved = ["doc_1", "doc_2", "doc_3", "doc_4", "doc_5"]
    relevant = {"doc_1", "doc_2", "doc_3", "doc_4", "doc_5"}
    assert compute_precision_at_k(retrieved, relevant, k=5) == 1.0


def test_precision_at_k_partial():
    retrieved = ["doc_1", "doc_2", "distractor_1", "distractor_2", "distractor_3"]
    relevant = {"doc_1", "doc_2"}
    # 2 out of 5 are relevant
    assert compute_precision_at_k(retrieved, relevant, k=5) == 0.4


def test_precision_at_k_zero():
    retrieved = ["d1", "d2", "d3", "d4", "d5"]
    relevant = {"target_a", "target_b"}
    assert compute_precision_at_k(retrieved, relevant, k=5) == 0.0


def test_precision_at_k_fewer_than_k():
    retrieved = ["doc_1", "doc_2"]
    relevant = {"doc_1", "doc_2"}
    # Only 2 retrieved, but evaluated at k=5: 2 / 5 = 0.4
    assert compute_precision_at_k(retrieved, relevant, k=5) == 0.4


def test_precision_at_k_empty_retrieved():
    assert compute_precision_at_k([], {"doc_1"}, k=5) == 0.0


def test_precision_at_k_invalid_k():
    assert compute_precision_at_k(["doc_1"], {"doc_1"}, k=0) == 0.0
    assert compute_precision_at_k(["doc_1"], {"doc_1"}, k=-1) == 0.0


def test_precision_at_k_unanswerable_negative():
    # If no documents are relevant, and none are retrieved -> 1.0
    assert compute_precision_at_k([], set(), k=5) == 1.0
    # If no documents are relevant, but items were retrieved -> 0.0
    assert compute_precision_at_k(["doc_1"], set(), k=5) == 0.0


# ============================================================================
# 2. RECALL@K TESTS
# ============================================================================


def test_recall_at_k_all_retrieved():
    retrieved = ["doc_1", "doc_2", "doc_3", "d4", "d5"]
    relevant = {"doc_1", "doc_2", "doc_3"}
    # 3 retrieved out of 3 total relevant
    assert compute_recall_at_k(retrieved, relevant, k=5) == 1.0


def test_recall_at_k_partial():
    retrieved = ["doc_1", "doc_2", "d3", "d4", "d5"]
    relevant = {"doc_1", "doc_2", "doc_3", "doc_4"}
    # 2 out of 4 retrieved in top-5
    assert compute_recall_at_k(retrieved, relevant, k=5) == 0.5


def test_recall_at_k_zero():
    retrieved = ["d1", "d2", "d3"]
    relevant = {"target_1", "target_2"}
    assert compute_recall_at_k(retrieved, relevant, k=5) == 0.0


def test_recall_at_k_beyond_k_ignored():
    # Relevant item is at index 6 (beyond k=5)
    retrieved = ["d1", "d2", "d3", "d4", "d5", "target_1"]
    relevant = {"target_1"}
    assert compute_recall_at_k(retrieved, relevant, k=5) == 0.0


def test_recall_at_k_empty_relevant():
    assert compute_recall_at_k([], set(), k=5) == 1.0
    assert compute_recall_at_k(["d1"], set(), k=5) == 0.0


# ============================================================================
# 3. MRR TESTS
# ============================================================================


def test_mrr_first_result_relevant():
    retrieved = ["hit_1", "d2", "d3"]
    relevant = {"hit_1"}
    assert compute_mrr(retrieved, relevant) == 1.0


def test_mrr_second_result_relevant():
    retrieved = ["d1", "hit_1", "d3"]
    relevant = {"hit_1"}
    assert compute_mrr(retrieved, relevant) == 0.5


def test_mrr_third_result_relevant():
    retrieved = ["d1", "d2", "hit_1"]
    relevant = {"hit_1"}
    assert compute_mrr(retrieved, relevant) == 0.3333


def test_mrr_no_relevant_result():
    retrieved = ["d1", "d2", "d3"]
    relevant = {"missing"}
    assert compute_mrr(retrieved, relevant) == 0.0


def test_mrr_multiple_relevant_takes_first():
    retrieved = ["d1", "hit_first", "d3", "hit_second"]
    relevant = {"hit_first", "hit_second"}
    # First hit is at rank 2 -> 1/2 = 0.5
    assert compute_mrr(retrieved, relevant) == 0.5


# ============================================================================
# 4. HIT RATE TESTS
# ============================================================================


def test_hit_rate_in_top_k():
    retrieved = ["d1", "d2", "target", "d4", "d5"]
    assert compute_hit_rate(retrieved, {"target"}, k=5) == 1.0


def test_hit_rate_outside_top_k():
    retrieved = ["d1", "d2", "d3", "d4", "d5", "target"]
    assert compute_hit_rate(retrieved, {"target"}, k=5) == 0.0


def test_evaluate_retrieval_bundle():
    res = evaluate_retrieval(["d1", "target"], {"target"}, k=2)
    assert res.k == 2
    assert res.precision_at_k == 0.5
    assert res.recall_at_k == 1.0
    assert res.mrr == 0.5
    assert res.hit_rate == 1.0


# ============================================================================
# 5. CONTEXT RELEVANCE TESTS
# ============================================================================


def test_context_relevance_perfect():
    retrieved = [
        "Customers can request a refund within 30 days of purchase for unused items.",
        "Approved refunds are credited to the original payment method in 5 to 7 days.",
    ]
    reference = [
        "We offer a 30-day refund policy on all purchases. Refunds take 5 to 7 business days.",
    ]
    score = compute_context_relevance(retrieved, reference, query="What is the refund policy?")
    assert score == 1.0


def test_context_relevance_mixed():
    retrieved = [
        "We offer a 30-day refund policy on all standard purchases.",
        "Our warehouse operates in Ohio and ships globally via air freight container vessels.",
    ]
    reference = [
        "We offer a 30-day refund policy on all standard purchases.",
    ]
    score = compute_context_relevance(retrieved, reference, query="What is the refund policy?")
    # 1 of 2 passages is relevant
    assert score == 0.5


def test_context_relevance_irrelevant():
    retrieved = [
        "The quick brown fox jumps over the lazy dog.",
        "Unrelated astrophysics passage about black holes and quasars.",
    ]
    reference = [
        "Password must be at least 12 characters with one uppercase letter.",
    ]
    score = compute_context_relevance(retrieved, reference, query="How do I reset password?")
    assert score == 0.0


def test_context_relevance_empty():
    # Both empty (correct for negative questions)
    assert compute_context_relevance([], []) == 1.0
    # Missing retrieved
    assert compute_context_relevance([], ["Some reference text"]) == 0.0
    # Unwanted retrieved when reference is empty
    assert compute_context_relevance(["Some text"], []) == 0.0


# ============================================================================
# 6. ANSWER RELEVANCE TESTS
# ============================================================================


def test_answer_relevance_good_answer():
    question = "What is the return window for a product?"
    reference = "Customers can return products within 30 days of delivery."
    generated = "You can return your product within 30 days of delivery for a full refund."
    score = compute_answer_relevance(question, generated, reference)
    assert score >= 0.70


def test_answer_relevance_irrelevant_answer():
    question = "What is the return window for a product?"
    reference = "Customers can return products within 30 days of delivery."
    generated = "Our company was founded in 2021 and we love making delicious ice cream."
    score = compute_answer_relevance(question, generated, reference)
    assert score < 0.35


def test_answer_relevance_empty_answer():
    assert compute_answer_relevance("Question?", "") == 0.0
    assert compute_answer_relevance("Question?", "   ") == 0.0


def test_answer_relevance_negative_refusal():
    question = "What is the weather in Tokyo tomorrow?"
    generated = "I do not have sufficient information in the knowledge base to answer your question."
    score = compute_answer_relevance(question, generated, is_answerable=False)
    # Refusal on an unanswerable question receives a full 1.0
    assert score == 1.0


def test_answer_relevance_refusal_on_answerable_penalized():
    question = "How do I reset my password?"
    reference = "Click forgot password on login screen."
    generated = "I do not have sufficient information in the knowledge base to answer your question."
    score = compute_answer_relevance(question, generated, reference, is_answerable=True)
    assert score <= 0.15


# ============================================================================
# 7. AGGREGATION TESTS
# ============================================================================


def test_aggregate_results_empty():
    summary = aggregate_evaluation_results([])
    assert summary.total_samples == 0
    assert summary.successful_samples == 0
    assert summary.mean_precision_at_k == 0.0


def test_aggregate_results_mixed():
    r1 = SampleEvaluationResult(
        sample_id="s1",
        question="Q1",
        category="auth",
        is_answerable=True,
        retrieval=RetrievalMetrics(k=5, precision_at_k=1.0, recall_at_k=1.0, mrr=1.0, hit_rate=1.0),
        rag=RAGMetrics(context_relevance=1.0, answer_relevance=1.0, faithfulness=1.0, hallucination_detected=False),
    )
    r2 = SampleEvaluationResult(
        sample_id="s2",
        question="Q2",
        category="auth",
        is_answerable=True,
        retrieval=RetrievalMetrics(k=5, precision_at_k=0.0, recall_at_k=0.0, mrr=0.0, hit_rate=0.0),
        rag=RAGMetrics(context_relevance=0.0, answer_relevance=0.5, faithfulness=0.5, hallucination_detected=True),
    )
    r3 = SampleEvaluationResult(
        sample_id="s3",
        question="Q3",
        category="refund",
        is_answerable=False,
        error="Simulation error",
    )

    summary = aggregate_evaluation_results([r1, r2, r3])
    assert summary.total_samples == 3
    assert summary.successful_samples == 2
    assert summary.failed_samples == 1

    # Means over successful samples
    assert summary.mean_precision_at_k == 0.5
    assert summary.mean_recall_at_k == 0.5
    assert summary.mean_mrr == 0.5
    assert summary.mean_context_relevance == 0.5
    assert summary.mean_answer_relevance == 0.75
    assert summary.mean_faithfulness == 0.75
    # 1 of 2 successful had hallucination -> 0.5
    assert summary.hallucination_rate == 0.5

    # Check by_category breakdown
    assert "auth" in summary.by_category
    assert summary.by_category["auth"]["sample_count"] == 2
    assert summary.by_category["auth"]["precision_at_k"] == 0.5
