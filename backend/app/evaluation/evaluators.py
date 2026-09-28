"""Modular evaluators for retrieval, context relevance, answer relevance, and faithfulness.

Supports both deterministic offline evaluation (fast, reproducible, no API required)
and optional LLM-as-a-judge evaluation via the swappable BaseLLMService abstraction.
"""

from abc import ABC, abstractmethod
import json
import re
from typing import Any, Optional, Sequence

from backend.app.evaluation.metrics import (
    compute_answer_relevance,
    compute_context_relevance,
    compute_faithfulness,
    evaluate_retrieval,
    extract_claims,
)
from backend.app.evaluation.schemas import (
    ClaimSupport,
    EvaluationSample,
    RAGMetrics,
    RetrievalMetrics,
)
from backend.app.services.llm import BaseLLMService


class BaseEvaluator(ABC):
    """Abstract base class for all evaluation components."""
    pass


class RetrievalEvaluator(BaseEvaluator):
    """Evaluates retrieval quality against benchmark ground truth relevant IDs."""

    def __init__(self, k: int = 5) -> None:
        self.k = k

    def evaluate(
        self,
        retrieved_ids: Sequence[str],
        sample: EvaluationSample,
        k: Optional[int] = None,
    ) -> RetrievalMetrics:
        """Calculate Precision@K, Recall@K, MRR, HitRate@K for a retrieved result list."""
        cutoff = k if k is not None else self.k
        relevant_targets = set(sample.relevant_chunk_ids) | set(sample.relevant_document_ids)
        return evaluate_retrieval(retrieved_ids, relevant_targets, k=cutoff)


class ContextRelevanceEvaluator(BaseEvaluator):
    """Evaluates how relevant the retrieved context chunks are to the user query."""

    def evaluate(
        self,
        retrieved_contexts: Sequence[str],
        sample: EvaluationSample,
    ) -> float:
        """Compute context relevance score in [0.0, 1.0]."""
        return compute_context_relevance(
            retrieved_contexts=retrieved_contexts,
            reference_contexts=sample.reference_context,
            query=sample.question,
        )


class AnswerRelevanceEvaluator(BaseEvaluator):
    """Evaluates whether the generated response properly answers the user question."""

    def evaluate(
        self,
        generated_answer: str,
        sample: EvaluationSample,
    ) -> float:
        """Compute answer relevance score in [0.0, 1.0]."""
        return compute_answer_relevance(
            question=sample.question,
            generated_answer=generated_answer,
            reference_answer=sample.reference_answer,
            is_answerable=sample.is_answerable,
        )


class FaithfulnessEvaluator(BaseEvaluator):
    """RAGAS-style faithfulness and hallucination evaluator.

    Extracts factual claims and determines if each claim is entailed by the retrieved context.
    Can operate deterministically (offline mode) or via an LLM judge.
    """

    def __init__(self, llm_service: Optional[BaseLLMService] = None) -> None:
        self.llm_service = llm_service

    async def evaluate_async(
        self,
        generated_answer: str,
        retrieved_contexts: Sequence[str],
        sample: Optional[EvaluationSample] = None,
    ) -> tuple[float, list[ClaimSupport]]:
        """Evaluate faithfulness asynchronously, using LLM judge if provided, else deterministic NLP."""
        is_answerable = sample.is_answerable if sample else True

        if self.llm_service is not None:
            return await self._evaluate_with_llm(generated_answer, retrieved_contexts, is_answerable)

        return self.evaluate_deterministic(generated_answer, retrieved_contexts, is_answerable)

    def evaluate_deterministic(
        self,
        generated_answer: str,
        retrieved_contexts: Sequence[str],
        is_answerable: bool = True,
    ) -> tuple[float, list[ClaimSupport]]:
        """Run fast, deterministic claim-based faithfulness verification."""
        return compute_faithfulness(
            generated_answer=generated_answer,
            retrieved_contexts=retrieved_contexts,
            is_answerable=is_answerable,
        )

    async def _evaluate_with_llm(
        self,
        generated_answer: str,
        retrieved_contexts: Sequence[str],
        is_answerable: bool = True,
    ) -> tuple[float, list[ClaimSupport]]:
        """LLM-as-a-judge claim evaluation via swappable BaseLLMService."""
        assert self.llm_service is not None

        claims = extract_claims(generated_answer)
        if not claims:
            return 1.0, []

        context_text = "\n".join(retrieved_contexts)

        # Handle refusal
        if not is_answerable and ("insufficient information" in generated_answer.lower() or "cannot" in generated_answer.lower()):
            return 1.0, [
                ClaimSupport(
                    claim=generated_answer[:80],
                    supported=True,
                    reasoning="Correct refusal for unanswerable question.",
                )
            ]

        prompt = (
            "You are an impartial AI evaluation judge assessing the faithfulness of a generated answer.\n"
            "Given the reference context and list of claims, determine for EACH claim whether it is directly supported by the context.\n\n"
            f"Context:\n{context_text}\n\n"
            f"Claims:\n" + "\n".join(f"{i+1}. {c}" for i, c in enumerate(claims)) + "\n\n"
            "Respond in JSON format as a list of objects:\n"
            '[{"claim_index": 1, "supported": true/false, "reasoning": "brief explanation"}]'
        )

        try:
            response = await self.llm_service.generate(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=1000,
            )
            # Parse JSON
            match = re.search(r"\[.*\]", response, re.DOTALL)
            if match:
                parsed = json.loads(match.group(0))
                claim_supports: list[ClaimSupport] = []
                supported_count = 0
                for item in parsed:
                    idx = int(item.get("claim_index", 1)) - 1
                    supp = bool(item.get("supported", False))
                    reas = item.get("reasoning", "")
                    claim_text = claims[idx] if 0 <= idx < len(claims) else "Unknown claim"
                    if supp:
                        supported_count += 1
                    claim_supports.append(
                        ClaimSupport(
                            claim=claim_text,
                            supported=supp,
                            reasoning=reas,
                        )
                    )
                score = round(supported_count / float(len(claims)), 4) if claims else 1.0
                return score, claim_supports
        except Exception:
            # Fall back to deterministic evaluation if LLM judge parsing fails
            pass

        return self.evaluate_deterministic(generated_answer, retrieved_contexts, is_answerable)
