"""Mathematical, lexical, and semantic metric calculations for AI evaluation.

Implements:
- Retrieval metrics: Precision@K, Recall@K, Mean Reciprocal Rank (MRR), Hit Rate@K
- RAG quality metrics: Context Relevance, Answer Relevance, Claim-based Faithfulness
- Metric aggregation across benchmark runs
"""

import re
from typing import Any, Optional, Sequence
from backend.app.evaluation.schemas import (
    ClaimSupport,
    EvaluationSummary,
    RAGMetrics,
    RetrievalMetrics,
    SampleEvaluationResult,
)

STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "aren't", "as", "at", "be", "because", "been", "before", "being",
    "below", "between", "both", "but", "by", "can", "cannot", "could", "did", "do",
    "does", "doing", "don't", "down", "during", "each", "few", "for", "from", "further",
    "had", "has", "have", "having", "he", "her", "here", "hers", "herself", "him",
    "himself", "his", "how", "i", "if", "in", "into", "is", "isn't", "it", "its",
    "itself", "just", "me", "more", "most", "my", "myself", "no", "nor", "not", "of",
    "off", "on", "once", "only", "or", "other", "our", "ours", "ourselves", "out",
    "over", "own", "same", "she", "should", "so", "some", "such", "than", "that",
    "the", "their", "theirs", "them", "themselves", "then", "there", "these", "they",
    "this", "those", "through", "to", "too", "under", "until", "up", "very", "was",
    "we", "were", "what", "when", "where", "which", "while", "who", "whom", "why",
    "with", "would", "you", "your", "yours", "yourself", "yourselves"
}

CONVERSATIONAL_PHRASES = (
    "please contact our support team",
    "if you have any other questions",
    "please let me know",
    "let me know if this helps",
    "let me know if you need",
    "i hope this helps",
    "have a great day",
    "thank you for",
    "thanks for",
)


def _is_conversational_filler(text: str) -> bool:
    """Determine if a sentence is purely pleasantries or conversational closing."""
    clean = text.lower().strip(".!? ")
    words = clean.split()
    if not words:
        return True
    # Greeting / short pleasantry
    if words[0] in {"hello", "hi", "hey", "greetings", "thanks", "thank"}:
        if len(words) <= 4:
            return True
    for phrase in CONVERSATIONAL_PHRASES:
        if phrase in clean:
            return True
    return False

INSUFFICIENT_CONTEXT_INDICATORS = (
    "do not have sufficient information",
    "insufficient information",
    "cannot answer",
    "not mentioned in the knowledge base",
    "not found in the provided context",
)


def _tokenize(text: str) -> list[str]:
    """Tokenize text into lowercase alphanumeric words."""
    return re.findall(r"\b[a-zA-Z0-9_\-\$]+\b", text.lower())


def _content_words(text: str) -> set[str]:
    """Extract informative non-stopword tokens from text."""
    tokens = _tokenize(text)
    return {t for t in tokens if t not in STOPWORDS and len(t) > 1}


# ============================================================================
# 1. RETRIEVAL METRICS
# ============================================================================


def compute_precision_at_k(
    retrieved_ids: Sequence[str],
    relevant_ids: Sequence[str] | set[str],
    k: int = 5,
) -> float:
    """Compute Precision@K.

    Formula:
        Precision@K = (number of relevant items in top-K) / K

    Edge cases:
        - If k <= 0: returns 0.0
        - If relevant_ids is empty and no items retrieved: 1.0 (negative query handled cleanly)
        - If relevant_ids is empty and items retrieved: 0.0
    """
    if k <= 0:
        return 0.0

    relevant_set = set(relevant_ids)
    if not relevant_set:
        return 1.0 if not retrieved_ids[:k] else 0.0

    top_k_retrieved = retrieved_ids[:k]
    hits = sum(1 for item in top_k_retrieved if item in relevant_set)
    return round(float(hits) / float(k), 4)


def compute_recall_at_k(
    retrieved_ids: Sequence[str],
    relevant_ids: Sequence[str] | set[str],
    k: int = 5,
) -> float:
    """Compute Recall@K.

    Formula:
        Recall@K = (number of relevant items in top-K) / (total relevant items)

    Edge cases:
        - If k <= 0: returns 0.0
        - If relevant_ids is empty: returns 1.0 if no items retrieved in top-K, else 0.0
    """
    if k <= 0:
        return 0.0

    relevant_set = set(relevant_ids)
    if not relevant_set:
        return 1.0 if not retrieved_ids[:k] else 0.0

    top_k_retrieved = retrieved_ids[:k]
    hits = sum(1 for item in top_k_retrieved if item in relevant_set)
    return round(float(hits) / float(len(relevant_set)), 4)


def compute_mrr(
    retrieved_ids: Sequence[str],
    relevant_ids: Sequence[str] | set[str],
) -> float:
    """Compute Mean Reciprocal Rank (MRR).

    Formula:
        MRR = 1 / rank of the first relevant retrieved item
        If no relevant item is found: 0.0

    Edge cases:
        - If relevant_ids is empty: returns 1.0 if retrieved_ids is empty, else 0.0
    """
    relevant_set = set(relevant_ids)
    if not relevant_set:
        return 1.0 if not retrieved_ids else 0.0

    for rank, item in enumerate(retrieved_ids, start=1):
        if item in relevant_set:
            return round(1.0 / float(rank), 4)

    return 0.0


def compute_hit_rate(
    retrieved_ids: Sequence[str],
    relevant_ids: Sequence[str] | set[str],
    k: int = 5,
) -> float:
    """Compute Hit Rate @ K (binary hit indicator).

    Returns 1.0 if any relevant item appears in top-K, else 0.0.
    """
    if k <= 0:
        return 0.0

    relevant_set = set(relevant_ids)
    if not relevant_set:
        return 1.0 if not retrieved_ids[:k] else 0.0

    top_k_retrieved = retrieved_ids[:k]
    hit = any(item in relevant_set for item in top_k_retrieved)
    return 1.0 if hit else 0.0


def evaluate_retrieval(
    retrieved_ids: Sequence[str],
    relevant_ids: Sequence[str] | set[str],
    k: int = 5,
) -> RetrievalMetrics:
    """Calculate all standard retrieval metrics for a single sample."""
    return RetrievalMetrics(
        k=k,
        precision_at_k=compute_precision_at_k(retrieved_ids, relevant_ids, k=k),
        recall_at_k=compute_recall_at_k(retrieved_ids, relevant_ids, k=k),
        mrr=compute_mrr(retrieved_ids, relevant_ids),
        hit_rate=compute_hit_rate(retrieved_ids, relevant_ids, k=k),
    )


# ============================================================================
# 2. CONTEXT RELEVANCE
# ============================================================================


def compute_context_relevance(
    retrieved_contexts: Sequence[str],
    reference_contexts: Sequence[str],
    query: str = "",
) -> float:
    """Compute context relevance score in [0.0, 1.0].

    Measures what proportion of retrieved passages contain information relevant
    to the reference context and customer query.

    Formula:
        Context Relevance = (count of relevant retrieved passages) / len(retrieved_passages)
    """
    if not retrieved_contexts and not reference_contexts:
        return 1.0
    if not retrieved_contexts and reference_contexts:
        return 0.0
    if retrieved_contexts and not reference_contexts:
        return 0.0

    # Build reference token pool
    ref_tokens: set[str] = set()
    for ref in reference_contexts:
        ref_tokens.update(_content_words(ref))
    query_tokens = _content_words(query)

    relevant_passages = 0
    for passage in retrieved_contexts:
        passage_tokens = _content_words(passage)
        if not passage_tokens:
            continue

        # Overlap with reference context
        ref_overlap = len(passage_tokens & ref_tokens)
        query_overlap = len(passage_tokens & query_tokens)

        # A passage is deemed relevant if it shares significant informative tokens
        # with the ground truth reference context (>= 3 words or >= 25% overlap)
        if ref_overlap >= 3 or (len(passage_tokens) > 0 and (ref_overlap / len(passage_tokens)) >= 0.20):
            relevant_passages += 1
        elif query_overlap >= 3:
            relevant_passages += 1

    return round(float(relevant_passages) / float(len(retrieved_contexts)), 4)


# ============================================================================
# 3. ANSWER RELEVANCE
# ============================================================================


def compute_answer_relevance(
    question: str,
    generated_answer: str,
    reference_answer: Optional[str] = None,
    is_answerable: bool = True,
) -> float:
    """Evaluate how relevant and comprehensive the generated answer is.

    Considers:
    1. Question intent coverage (informative query words addressed in answer)
    2. Reference answer alignment (token F1 score against ground truth)
    3. Proper handling of negative/unsupported questions
    """
    if not generated_answer or not generated_answer.strip():
        return 0.0

    gen_lower = generated_answer.lower()

    # Handle negative / unsupported cases
    if not is_answerable:
        is_refusal = any(ind in gen_lower for ind in INSUFFICIENT_CONTEXT_INDICATORS)
        return 1.0 if is_refusal else 0.2

    # If question was answerable but generated answer is an empty refusal:
    is_refusal = any(ind in gen_lower for ind in INSUFFICIENT_CONTEXT_INDICATORS)
    if is_refusal:
        return 0.1

    q_words = _content_words(question)
    gen_words = _content_words(generated_answer)

    if not gen_words:
        return 0.0

    # Query alignment: how many query keywords are addressed
    query_coverage = len(q_words & gen_words) / float(len(q_words)) if q_words else 1.0

    # Reference alignment: token F1 score between generated and reference
    if reference_answer:
        ref_words = _content_words(reference_answer)
        if ref_words:
            intersection = len(gen_words & ref_words)
            prec = intersection / float(len(gen_words)) if gen_words else 0.0
            rec = intersection / float(len(ref_words)) if ref_words else 0.0
            f1 = (2 * prec * rec) / (prec + rec) if (prec + rec) > 0 else 0.0
            # Blend 40% query coverage + 60% reference alignment
            score = (0.4 * query_coverage) + (0.6 * f1)
            # Add small bonus if key entities/numbers match
            ref_numbers = set(re.findall(r"\b\d+\b", reference_answer))
            gen_numbers = set(re.findall(r"\b\d+\b", generated_answer))
            if ref_numbers and (ref_numbers & gen_numbers):
                score = min(1.0, score + 0.15)
            return round(min(1.0, max(0.0, score)), 4)

    return round(min(1.0, max(0.0, query_coverage)), 4)


# ============================================================================
# 4. FAITHFULNESS / GROUNDEDNESS (RAGAS-STYLE)
# ============================================================================


def extract_claims(text: str) -> list[str]:
    """Extract individual factual claims/statements from an answer.

    Splits by punctuation, removes bullet formatting and conversational filler.
    """
    raw_sentences = re.split(r"(?<=[.!?])\s+|\n+", text)
    claims: list[str] = []

    for raw in raw_sentences:
        clean = raw.strip()
        # Clean markdown bullets (e.g. '-', '*', '1.') without removing factual numbers (e.g. '30 days')
        clean = re.sub(r"^\s*(?:[-*•]|\d+\.)\s*", "", clean).strip()
        if not clean or len(clean) < 10:
            continue

        if _is_conversational_filler(clean):
            continue

        claims.append(clean)

    return claims


def verify_claim_against_context(
    claim: str,
    context_text: str,
) -> tuple[bool, Optional[str], Optional[str]]:
    """Verify whether a single claim is supported by the context text.

    Checks:
    - Informative token containment
    - Numerical / entity alignment (if claim has numbers, they must exist in context)
    - Key phrase presence
    """
    if not context_text or not context_text.strip():
        return False, None, "No context provided to ground the claim"

    claim_words = _content_words(claim)
    if not claim_words:
        return True, None, "Non-factual or empty assertion"

    context_lower = context_text.lower()
    claim_lower = claim.lower()

    # 1. Direct substring match
    if claim_lower in context_lower:
        return True, claim, "Exact match in context"

    # 2. Number / Entity check: If claim has numbers (e.g. 30 days, $50, 12 characters),
    # context must have those numbers.
    claim_numbers = set(re.findall(r"\b\d+(?:\.\d+)?\b", claim))
    context_numbers = set(re.findall(r"\b\d+(?:\.\d+)?\b", context_text))
    if claim_numbers and not claim_numbers.issubset(context_numbers):
        missing = claim_numbers - context_numbers
        return False, None, f"Claim contains numbers {missing} not found in reference context"

    # 3. Informative word overlap
    context_words = _content_words(context_text)
    overlap = claim_words & context_words
    overlap_ratio = len(overlap) / float(len(claim_words))

    # A claim is supported if >= 65% of its informative words appear in context
    if overlap_ratio >= 0.65 or len(overlap) >= 5:
        # Find the best matching snippet
        snippet = next((line for line in context_text.splitlines() if any(w in line.lower() for w in overlap)), None)
        return True, snippet, f"Supported by context (overlap ratio: {overlap_ratio:.2f})"

    return False, None, f"Insufficient grounding in context (overlap ratio: {overlap_ratio:.2f})"


def compute_faithfulness(
    generated_answer: str,
    retrieved_contexts: Sequence[str] | str,
    is_answerable: bool = True,
) -> tuple[float, list[ClaimSupport]]:
    """Compute RAGAS-style faithfulness score.

    Formula:
        Faithfulness = (number of supported claims) / (total factual claims)

    Returns:
        (faithfulness_score, list_of_claims_with_status)
    """
    if isinstance(retrieved_contexts, str):
        context_text = retrieved_contexts
    else:
        context_text = "\n".join(retrieved_contexts)

    # If unanswerable and the model states insufficient context, it is 100% faithful
    gen_lower = generated_answer.lower()
    is_refusal = any(ind in gen_lower for ind in INSUFFICIENT_CONTEXT_INDICATORS)
    if is_refusal:
        return 1.0, [
            ClaimSupport(
                claim=generated_answer[:100],
                supported=True,
                reasoning="System correctly issued refusal without hallucinating.",
            )
        ]

    claims = extract_claims(generated_answer)
    if not claims:
        # No claims to evaluate
        return 1.0, []

    claim_supports: list[ClaimSupport] = []
    supported_count = 0

    for claim in claims:
        is_supported, snippet, reasoning = verify_claim_against_context(claim, context_text)
        if is_supported:
            supported_count += 1

        claim_supports.append(
            ClaimSupport(
                claim=claim,
                supported=is_supported,
                supporting_passage=snippet,
                reasoning=reasoning,
            )
        )

    faithfulness_score = round(float(supported_count) / float(len(claims)), 4)
    return faithfulness_score, claim_supports


def evaluate_rag_quality(
    question: str,
    generated_answer: str,
    retrieved_contexts: Sequence[str],
    reference_answer: Optional[str] = None,
    reference_contexts: Optional[Sequence[str]] = None,
    is_answerable: bool = True,
) -> RAGMetrics:
    """Evaluate context relevance, answer relevance, and faithfulness for a single sample."""
    ctx_rel = compute_context_relevance(
        retrieved_contexts=retrieved_contexts,
        reference_contexts=reference_contexts or [],
        query=question,
    )
    ans_rel = compute_answer_relevance(
        question=question,
        generated_answer=generated_answer,
        reference_answer=reference_answer,
        is_answerable=is_answerable,
    )
    faithfulness_score, claim_supports = compute_faithfulness(
        generated_answer=generated_answer,
        retrieved_contexts=retrieved_contexts,
        is_answerable=is_answerable,
    )
    total_claims = len(claim_supports)
    supported_claims = sum(1 for c in claim_supports if c.supported)
    hallucination_detected = any(not c.supported for c in claim_supports)

    return RAGMetrics(
        context_relevance=ctx_rel,
        answer_relevance=ans_rel,
        faithfulness=faithfulness_score,
        hallucination_detected=hallucination_detected,
        supported_claims_count=supported_claims,
        total_claims_count=total_claims,
        claims=claim_supports,
    )


# ============================================================================
# 5. AGGREGATION
# ============================================================================


def aggregate_evaluation_results(
    results: Sequence[SampleEvaluationResult],
) -> EvaluationSummary:
    """Aggregate individual sample evaluation results into a comprehensive summary."""
    total = len(results)
    if total == 0:
        return EvaluationSummary()

    successful = [r for r in results if r.error is None]
    failed = [r for r in results if r.error is not None]

    precisions: list[float] = []
    recalls: list[float] = []
    mrrs: list[float] = []
    context_rels: list[float] = []
    answer_rels: list[float] = []
    faithfulness_scores: list[float] = []
    hallucination_flags: list[bool] = []

    category_buckets: dict[str, list[SampleEvaluationResult]] = {}

    for r in successful:
        cat = r.category or "general"
        category_buckets.setdefault(cat, []).append(r)

        if r.retrieval:
            precisions.append(r.retrieval.precision_at_k)
            recalls.append(r.retrieval.recall_at_k)
            mrrs.append(r.retrieval.mrr)

        if r.rag:
            context_rels.append(r.rag.context_relevance)
            answer_rels.append(r.rag.answer_relevance)
            faithfulness_scores.append(r.rag.faithfulness)
            hallucination_flags.append(r.rag.hallucination_detected)

    def _mean(vals: list[float]) -> float:
        return round(sum(vals) / float(len(vals)), 4) if vals else 0.0

    by_category: dict[str, dict[str, float]] = {}
    for cat, cat_results in category_buckets.items():
        cat_p = [res.retrieval.precision_at_k for res in cat_results if res.retrieval]
        cat_r = [res.retrieval.recall_at_k for res in cat_results if res.retrieval]
        cat_m = [res.retrieval.mrr for res in cat_results if res.retrieval]
        cat_cr = [res.rag.context_relevance for res in cat_results if res.rag]
        cat_ar = [res.rag.answer_relevance for res in cat_results if res.rag]
        cat_f = [res.rag.faithfulness for res in cat_results if res.rag]
        by_category[cat] = {
            "sample_count": len(cat_results),
            "precision_at_k": _mean(cat_p),
            "recall_at_k": _mean(cat_r),
            "mrr": _mean(cat_m),
            "context_relevance": _mean(cat_cr),
            "answer_relevance": _mean(cat_ar),
            "faithfulness": _mean(cat_f),
        }

    hallucination_rate = (
        round(sum(1 for h in hallucination_flags if h) / float(len(hallucination_flags)), 4)
        if hallucination_flags
        else 0.0
    )

    return EvaluationSummary(
        total_samples=total,
        successful_samples=len(successful),
        failed_samples=len(failed),
        mean_precision_at_k=_mean(precisions),
        mean_recall_at_k=_mean(recalls),
        mean_mrr=_mean(mrrs),
        mean_context_relevance=_mean(context_rels),
        mean_answer_relevance=_mean(answer_rels),
        mean_faithfulness=_mean(faithfulness_scores),
        hallucination_rate=hallucination_rate,
        by_category=by_category,
    )
