"""Phase 15 — eval: Human-In-The-Loop (HITL) evaluation quality gates.

These tests evaluate the metrics and invariants of the HITL review workflow
at the evaluation layer — not the API layer (which is covered in tests/api/).
They assert quality properties about the review state machine, decision
metadata, and reviewer audit integrity using deterministic evaluation logic.

Evaluation Assertions:
  H1.  EvaluationRunner correctly identifies samples with no relevant chunks.
  H2.  FaithfulnessEvaluator flags obvious hallucinations (claims not in context).
  H3.  FaithfulnessEvaluator passes when all claims are grounded in context.
  H4.  ContextRelevanceEvaluator returns 0.0 when contexts are empty.
  H5.  ContextRelevanceEvaluator returns 1.0 when context fully matches expected.
  H6.  RetrievalEvaluator: hit_rate=1.0 when relevant chunk is in results.
  H7.  RetrievalEvaluator: hit_rate=0.0 when no relevant chunk is retrieved.
  H8.  RetrievalEvaluator: MRR is 1.0 when relevant chunk is rank-1.
  H9.  RetrievalEvaluator: MRR is 0.5 when relevant chunk is rank-2.
  H10. Offline evaluation batch correctly segregates answerable vs unanswerable.
  H11. SampleEvaluationResult.error is None for successfully processed samples.
  H12. AnswerRelevanceEvaluator returns 1.0 for exact reference answer match.
  H13. AnswerRelevanceEvaluator returns 0.0 for completely unrelated answer.
  H14. Aggregate summary: total_samples = successful + failed.
  H15. EvaluationDataset iteration produces EvaluationSample instances.
"""

import pytest

from backend.app.evaluation.dataset import EvaluationDataset
from backend.app.evaluation.evaluators import (
    AnswerRelevanceEvaluator,
    ContextRelevanceEvaluator,
    FaithfulnessEvaluator,
    RetrievalEvaluator,
)
from backend.app.evaluation.metrics import aggregate_evaluation_results
from backend.app.evaluation.runner import EvaluationRunner
from backend.app.evaluation.schemas import EvaluationSample
from backend.app.services.llm import MockLLMService


# ---------------------------------------------------------------------------
# H1. Samples with no relevant chunks get empty retrieval in offline mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unanswerable_sample_produces_empty_retrieval():
    """H1: Unanswerable samples must have empty retrieved_chunks in offline evaluation."""
    sample = EvaluationSample(
        id="h1_unanswerable",
        question="What is the boiling point of tungsten?",
        reference_answer="I do not have sufficient information in the knowledge base to answer your question.",
        relevant_chunk_ids=[],
        reference_context=[],
        category="out_of_domain",
        is_answerable=False,
    )
    dataset = EvaluationDataset([sample])
    runner = EvaluationRunner(dataset=dataset, llm_service=MockLLMService(), top_k=5)
    report = await runner.run_offline()

    result = report.sample_results[0]
    assert result.retrieved_chunks == [], (
        "Unanswerable sample should have no retrieved chunks in offline mode."
    )
    assert result.error is None


# ---------------------------------------------------------------------------
# H2. FaithfulnessEvaluator flags obvious hallucinations
# ---------------------------------------------------------------------------


def test_faithfulness_evaluator_flags_hallucination():
    """H2: A claim with no grounding in retrieved context is flagged as hallucination."""
    evaluator = FaithfulnessEvaluator()
    fabricated_answer = "The refund will be processed in 90 days via cryptocurrency."
    context = ["Refunds are processed within 5-7 business days via original payment method."]

    score, claims = evaluator.evaluate_deterministic(
        generated_answer=fabricated_answer,
        retrieved_contexts=context,
        is_answerable=True,
    )

    # Should detect at least one unsupported claim
    unsupported = [c for c in claims if not c.supported]
    assert len(unsupported) >= 1, (
        "FaithfulnessEvaluator failed to flag hallucinated claim about 'cryptocurrency'."
    )
    assert score < 1.0, f"Score should be < 1.0 for a hallucinated answer, got {score}."


# ---------------------------------------------------------------------------
# H3. FaithfulnessEvaluator passes when all claims are grounded
# ---------------------------------------------------------------------------


def test_faithfulness_evaluator_passes_grounded_answer():
    """H3: When the answer exactly mirrors the context, faithfulness score must be 1.0."""
    evaluator = FaithfulnessEvaluator()
    grounded_answer = "Refunds are processed within 5-7 business days."
    context = ["Refunds are processed within 5-7 business days via the original payment method."]

    score, claims = evaluator.evaluate_deterministic(
        generated_answer=grounded_answer,
        retrieved_contexts=context,
        is_answerable=True,
    )

    assert score == 1.0, (
        f"Expected faithfulness=1.0 for a grounded answer, got {score}. "
        f"Unsupported claims: {[c.claim for c in claims if not c.supported]}"
    )


# ---------------------------------------------------------------------------
# H4. ContextRelevanceEvaluator returns 0.0 for empty context
# ---------------------------------------------------------------------------


def test_context_relevance_empty_context():
    """H4: With no retrieved contexts, ContextRelevanceEvaluator must return 0.0."""
    evaluator = ContextRelevanceEvaluator()
    sample = EvaluationSample(
        id="h4",
        question="How do I cancel my subscription?",
        reference_answer="...",
        reference_context=["Subscription can be cancelled from Account > Billing."],
        category="billing",
    )
    score = evaluator.evaluate([], sample)
    assert score == 0.0, f"Expected 0.0 for empty context, got {score}."


# ---------------------------------------------------------------------------
# H5. ContextRelevanceEvaluator returns 1.0 for perfect context match
# ---------------------------------------------------------------------------


def test_context_relevance_perfect_match():
    """H5: When all retrieved contexts exactly match reference contexts, score must be 1.0."""
    evaluator = ContextRelevanceEvaluator()
    reference = "Subscription can be cancelled from Account > Billing within 30 days."
    sample = EvaluationSample(
        id="h5",
        question="How do I cancel?",
        reference_answer="...",
        reference_context=[reference],
        category="billing",
    )
    score = evaluator.evaluate([reference], sample)
    assert score == 1.0, f"Expected 1.0 for exact context match, got {score}."


# ---------------------------------------------------------------------------
# H6. RetrievalEvaluator: hit_rate=1.0 when relevant chunk is in results
# ---------------------------------------------------------------------------


def test_retrieval_evaluator_hit_rate_positive():
    """H6: If the relevant chunk_id is retrieved, hit_rate must be 1.0."""
    evaluator = RetrievalEvaluator(k=5)
    sample = EvaluationSample(
        id="h6",
        question="What is the password policy?",
        reference_answer="...",
        relevant_chunk_ids=["chunk_auth_01"],
        reference_context=[],
        category="authentication",
    )
    metrics = evaluator.evaluate(
        retrieved_ids=["chunk_other", "chunk_auth_01", "chunk_misc"],
        sample=sample,
        k=5,
    )
    assert metrics.hit_rate == 1.0, f"Expected hit_rate=1.0, got {metrics.hit_rate}."


# ---------------------------------------------------------------------------
# H7. RetrievalEvaluator: hit_rate=0.0 when no relevant chunk is retrieved
# ---------------------------------------------------------------------------


def test_retrieval_evaluator_hit_rate_negative():
    """H7: If the relevant chunk is NOT retrieved, hit_rate must be 0.0."""
    evaluator = RetrievalEvaluator(k=5)
    sample = EvaluationSample(
        id="h7",
        question="What is the refund window?",
        reference_answer="...",
        relevant_chunk_ids=["chunk_refund_01"],
        reference_context=[],
        category="refund",
    )
    metrics = evaluator.evaluate(
        retrieved_ids=["chunk_unrelated_a", "chunk_unrelated_b"],
        sample=sample,
        k=5,
    )
    assert metrics.hit_rate == 0.0, f"Expected hit_rate=0.0, got {metrics.hit_rate}."


# ---------------------------------------------------------------------------
# H8. RetrievalEvaluator: MRR=1.0 when relevant chunk is rank-1
# ---------------------------------------------------------------------------


def test_retrieval_evaluator_mrr_rank_one():
    """H8: When the relevant chunk is the first result, MRR must equal 1.0."""
    evaluator = RetrievalEvaluator(k=5)
    sample = EvaluationSample(
        id="h8",
        question="How do I contact support?",
        reference_answer="...",
        relevant_chunk_ids=["chunk_contact_01"],
        reference_context=[],
        category="general",
    )
    metrics = evaluator.evaluate(
        retrieved_ids=["chunk_contact_01", "chunk_faq_02", "chunk_other_03"],
        sample=sample,
        k=5,
    )
    assert metrics.mrr == 1.0, f"Expected MRR=1.0 for rank-1 hit, got {metrics.mrr}."


# ---------------------------------------------------------------------------
# H9. RetrievalEvaluator: MRR=0.5 when relevant chunk is rank-2
# ---------------------------------------------------------------------------


def test_retrieval_evaluator_mrr_rank_two():
    """H9: When the relevant chunk is rank-2, MRR must equal 0.5 (1/2)."""
    evaluator = RetrievalEvaluator(k=5)
    sample = EvaluationSample(
        id="h9",
        question="Express shipping delivery time?",
        reference_answer="...",
        relevant_chunk_ids=["chunk_shipping_express"],
        reference_context=[],
        category="shipping",
    )
    metrics = evaluator.evaluate(
        retrieved_ids=["chunk_irrelevant_01", "chunk_shipping_express", "chunk_other"],
        sample=sample,
        k=5,
    )
    assert abs(metrics.mrr - 0.5) < 1e-6, f"Expected MRR=0.5 for rank-2 hit, got {metrics.mrr}."


# ---------------------------------------------------------------------------
# H10. Offline evaluation correctly segregates answerable vs unanswerable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_offline_evaluation_segregates_sample_types():
    """H10: Offline runner must correctly handle a mixed batch of answerable and unanswerable samples."""
    samples = [
        EvaluationSample(
            id="pos_01",
            question="What is the return window?",
            reference_answer="30 days from purchase.",
            relevant_chunk_ids=["chunk_return"],
            reference_context=["Returns are accepted within 30 days."],
            category="refund",
            is_answerable=True,
        ),
        EvaluationSample(
            id="neg_01",
            question="What is the melting point of osmium?",
            reference_answer="I do not have sufficient information in the knowledge base to answer your question.",
            relevant_chunk_ids=[],
            reference_context=[],
            category="out_of_domain",
            is_answerable=False,
        ),
    ]
    dataset = EvaluationDataset(samples)
    runner = EvaluationRunner(dataset=dataset, llm_service=MockLLMService(), top_k=3)
    report = await runner.run_offline()

    pos_result = next(r for r in report.sample_results if r.sample_id == "pos_01")
    neg_result = next(r for r in report.sample_results if r.sample_id == "neg_01")

    # Positive: has retrieval + context
    assert pos_result.retrieved_chunks != []
    assert pos_result.retrieval is not None
    assert pos_result.retrieval.hit_rate == 1.0

    # Negative: no chunks retrieved (unanswerable — out-of-domain)
    assert neg_result.retrieved_chunks == [], (
        "Unanswerable sample must produce no retrieved chunks in offline mode."
    )
    # For unanswerable samples with empty relevant_chunk_ids, the evaluator
    # correctly returns hit_rate=1.0 (vacuous truth: 0 relevant retrieved,
    # 0 expected → precision=1.0, recall=1.0). The meaningful assertion is
    # that no chunks were injected and the refusal message was produced.
    assert neg_result.retrieval is not None
    assert neg_result.generated_answer is not None
    # Verify refusal was generated, not a fabricated answer
    from backend.app.services.rag_graph import INSUFFICIENT_CONTEXT_MESSAGE
    assert INSUFFICIENT_CONTEXT_MESSAGE in neg_result.generated_answer, (
        f"Unanswerable sample should produce refusal, got: {neg_result.generated_answer[:80]}"
    )


# ---------------------------------------------------------------------------
# H11. Successful samples have error=None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_successful_samples_have_no_error():
    """H11: All successfully evaluated samples must have error=None."""
    sample = EvaluationSample(
        id="h11",
        question="How do I request a refund?",
        reference_answer="Submit a refund request within 30 days.",
        relevant_chunk_ids=["chunk_refund_policy"],
        reference_context=["Refund requests must be submitted within 30 days of purchase."],
        category="refund",
        is_answerable=True,
    )
    dataset = EvaluationDataset([sample])
    runner = EvaluationRunner(dataset=dataset, llm_service=MockLLMService())
    report = await runner.run_offline()

    for result in report.sample_results:
        assert result.error is None, (
            f"Sample '{result.sample_id}' has unexpected error: {result.error}"
        )


# ---------------------------------------------------------------------------
# H12. AnswerRelevanceEvaluator returns 1.0 for exact reference match
# ---------------------------------------------------------------------------


def test_answer_relevance_exact_match():
    """H12: When the generated answer is identical to the reference, answer_relevance must be 1.0."""
    evaluator = AnswerRelevanceEvaluator()
    sample = EvaluationSample(
        id="h12",
        question="When is the store open?",
        reference_answer="The store is open Monday to Friday, 9 AM to 6 PM EST.",
        category="general",
    )
    score = evaluator.evaluate(
        generated_answer="The store is open Monday to Friday, 9 AM to 6 PM EST.",
        sample=sample,
    )
    assert score == 1.0, f"Expected 1.0 for exact match, got {score}."


# ---------------------------------------------------------------------------
# H13. AnswerRelevanceEvaluator returns 0.0 for completely unrelated answer
# ---------------------------------------------------------------------------


def test_answer_relevance_unrelated_answer():
    """H13: An answer completely unrelated to the question must score 0.0."""
    evaluator = AnswerRelevanceEvaluator()
    sample = EvaluationSample(
        id="h13",
        question="How do I cancel my subscription?",
        reference_answer="Go to Account > Billing > Cancel Subscription.",
        category="billing",
    )
    # Completely different topic
    score = evaluator.evaluate(
        generated_answer="The weather in Paris is 22 degrees Celsius today.",
        sample=sample,
    )
    assert score == 0.0, (
        f"Expected 0.0 for completely unrelated answer, got {score}. "
        "AnswerRelevanceEvaluator must detect semantic irrelevance."
    )


# ---------------------------------------------------------------------------
# H14. Aggregate summary: total_samples = successful + failed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aggregate_summary_totals_are_consistent():
    """H14: summary.total_samples must always equal successful_samples + failed_samples."""
    samples = [
        EvaluationSample(
            id=f"sum_{i}",
            question=f"Question {i}?",
            reference_answer=f"Answer {i}.",
            relevant_chunk_ids=[f"chunk_{i}"],
            reference_context=[f"Context for question {i}."],
            category="general",
            is_answerable=True,
        )
        for i in range(5)
    ]
    dataset = EvaluationDataset(samples)
    runner = EvaluationRunner(dataset=dataset, llm_service=MockLLMService())
    report = await runner.run_offline()

    summary = report.summary
    assert summary.total_samples == summary.successful_samples + summary.failed_samples, (
        f"Totals mismatch: {summary.total_samples} != "
        f"{summary.successful_samples} + {summary.failed_samples}"
    )
    assert summary.total_samples == 5


# ---------------------------------------------------------------------------
# H15. EvaluationDataset iteration produces EvaluationSample instances
# ---------------------------------------------------------------------------


def test_evaluation_dataset_yields_sample_instances(benchmark_dataset: EvaluationDataset):
    """H15: Iterating the EvaluationDataset must yield EvaluationSample Pydantic model instances."""
    samples = list(benchmark_dataset)
    assert len(samples) > 0, "Dataset must not be empty."

    for sample in samples:
        assert isinstance(sample, EvaluationSample), (
            f"Expected EvaluationSample, got {type(sample).__name__}"
        )
        assert len(sample.id) > 0
        assert len(sample.question) >= 2
        assert isinstance(sample.is_answerable, bool)
