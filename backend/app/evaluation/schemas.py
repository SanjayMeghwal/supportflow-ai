"""Pydantic schemas for SupportFlow AI evaluation layer.

Covers benchmark dataset samples, retrieval metrics (Precision@K, Recall@K, MRR),
RAG quality metrics (Context Relevance, Answer Relevance, Faithfulness),
and machine-readable evaluation reports.
"""

from datetime import datetime, timezone
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


class EvaluationSample(BaseModel):
    """A single deterministic customer support benchmark sample."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(description="Unique benchmark sample identifier", min_length=1)
    question: str = Field(description="Customer inquiry or prompt to test", min_length=2)
    reference_answer: str = Field(description="Authoritative ground truth answer")
    relevant_document_ids: list[str] = Field(
        default_factory=list,
        description="IDs of documents that contain the answer",
    )
    relevant_chunk_ids: list[str] = Field(
        default_factory=list,
        description="IDs of chunks that contain the ground truth context",
    )
    reference_context: list[str] = Field(
        default_factory=list,
        description="Text passages providing ground truth facts",
    )
    category: str = Field(default="general", description="Domain category (e.g. refund, auth)")
    difficulty: str = Field(default="medium", description="Subjective difficulty: easy, medium, hard")
    is_answerable: bool = Field(
        default=True,
        description="True if the knowledge base should contain the answer; False for out-of-domain/negative samples",
    )
    metadata: Optional[dict[str, Any]] = Field(default=None, description="Optional extra metadata")


class RetrievalMetrics(BaseModel):
    """Retrieval evaluation metrics computed against expected relevant items."""

    model_config = ConfigDict(from_attributes=True)

    k: int = Field(default=5, ge=1, description="Top-K cutoff used for precision and recall")
    precision_at_k: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Proportion of retrieved top-K items that are relevant",
    )
    recall_at_k: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Proportion of all known relevant items retrieved in top-K",
    )
    mrr: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Mean Reciprocal Rank: 1 / rank of the first relevant result",
    )
    hit_rate: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Binary indicator: 1.0 if at least one relevant item is in top-K, else 0.0",
    )


class ClaimSupport(BaseModel):
    """Individual factual claim extracted from generated answer and its verification status."""

    claim: str = Field(description="Factual assertion extracted from response")
    supported: bool = Field(description="Whether the claim is grounded in retrieved context")
    supporting_passage: Optional[str] = Field(default=None, description="Passage supporting the claim if any")
    reasoning: Optional[str] = Field(default=None, description="Explanation of verification")


class RAGMetrics(BaseModel):
    """RAG generation quality metrics (RAGAS-style evaluation)."""

    model_config = ConfigDict(from_attributes=True)

    context_relevance: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Ratio of relevant context to total retrieved context",
    )
    answer_relevance: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Alignment between generated answer and the customer question/intent",
    )
    faithfulness: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Proportion of claims in the generated answer supported by retrieved context",
    )
    hallucination_detected: bool = Field(
        default=False,
        description="True if one or more claims lack grounding in retrieved context",
    )
    supported_claims_count: int = Field(default=0, ge=0)
    total_claims_count: int = Field(default=0, ge=0)
    claims: list[ClaimSupport] = Field(default_factory=list)


class SampleEvaluationResult(BaseModel):
    """Per-sample benchmark execution and evaluation record."""

    model_config = ConfigDict(from_attributes=True)

    sample_id: str = Field(description="Unique identifier matching benchmark dataset")
    question: str = Field(description="Customer question tested")
    category: str = Field(description="Category tag")
    is_answerable: bool = Field(description="Whether question was expected to have context")
    retrieval: Optional[RetrievalMetrics] = Field(default=None)
    rag: Optional[RAGMetrics] = Field(default=None)
    generated_answer: Optional[str] = Field(default=None)
    retrieved_chunks: list[str] = Field(default_factory=list)
    execution_time_ms: float = Field(default=0.0)
    error: Optional[str] = Field(default=None)


class EvaluationSummary(BaseModel):
    """Aggregated benchmark metrics across all evaluated samples."""

    model_config = ConfigDict(from_attributes=True)

    total_samples: int = Field(default=0)
    successful_samples: int = Field(default=0)
    failed_samples: int = Field(default=0)
    mean_precision_at_k: float = Field(default=0.0)
    mean_recall_at_k: float = Field(default=0.0)
    mean_mrr: float = Field(default=0.0)
    mean_context_relevance: float = Field(default=0.0)
    mean_answer_relevance: float = Field(default=0.0)
    mean_faithfulness: float = Field(default=0.0)
    hallucination_rate: float = Field(default=0.0)
    by_category: dict[str, dict[str, float]] = Field(default_factory=dict)


class EvaluationReport(BaseModel):
    """Complete machine-readable evaluation run report."""

    model_config = ConfigDict(from_attributes=True)

    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    dataset_version: str = Field(default="1.0.0")
    configuration: dict[str, Any] = Field(default_factory=dict)
    summary: EvaluationSummary
    sample_results: list[SampleEvaluationResult] = Field(default_factory=list)
