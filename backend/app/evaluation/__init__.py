"""SupportFlow AI evaluation and quality metrics package.

Exposes benchmark dataset, evaluation metrics, evaluators, runner, and reporting.
"""

from backend.app.evaluation.dataset import DatasetError, EvaluationDataset
from backend.app.evaluation.evaluators import (
    AnswerRelevanceEvaluator,
    BaseEvaluator,
    ContextRelevanceEvaluator,
    FaithfulnessEvaluator,
    RetrievalEvaluator,
)
from backend.app.evaluation.metrics import (
    aggregate_evaluation_results,
    compute_answer_relevance,
    compute_context_relevance,
    compute_faithfulness,
    compute_hit_rate,
    compute_mrr,
    compute_precision_at_k,
    compute_recall_at_k,
    evaluate_rag_quality,
    evaluate_retrieval,
    extract_claims,
    verify_claim_against_context,
)
from backend.app.evaluation.report import (
    format_console_report,
    format_markdown_report,
    save_report_to_json,
)
from backend.app.evaluation.runner import EvaluationRunner
from backend.app.evaluation.schemas import (
    ClaimSupport,
    EvaluationReport,
    EvaluationSample,
    EvaluationSummary,
    RAGMetrics,
    RetrievalMetrics,
    SampleEvaluationResult,
)

__all__ = [
    "AnswerRelevanceEvaluator",
    "BaseEvaluator",
    "ClaimSupport",
    "ContextRelevanceEvaluator",
    "DatasetError",
    "EvaluationDataset",
    "EvaluationReport",
    "EvaluationRunner",
    "EvaluationSample",
    "EvaluationSummary",
    "FaithfulnessEvaluator",
    "RAGMetrics",
    "RetrievalEvaluator",
    "RetrievalMetrics",
    "SampleEvaluationResult",
    "aggregate_evaluation_results",
    "compute_answer_relevance",
    "compute_context_relevance",
    "compute_faithfulness",
    "compute_hit_rate",
    "compute_mrr",
    "compute_precision_at_k",
    "compute_recall_at_k",
    "evaluate_rag_quality",
    "evaluate_retrieval",
    "extract_claims",
    "format_console_report",
    "format_markdown_report",
    "save_report_to_json",
    "verify_claim_against_context",
]
