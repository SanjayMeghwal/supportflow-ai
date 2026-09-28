"""Unit tests for the EvaluationRunner, report generation, and failure isolation."""

import json
from pathlib import Path
import pytest

from backend.app.evaluation.dataset import EvaluationDataset
from backend.app.evaluation.report import (
    format_console_report,
    format_markdown_report,
    save_report_to_json,
)
from backend.app.evaluation.runner import EvaluationRunner
from backend.app.evaluation.schemas import EvaluationReport, EvaluationSample
from backend.app.services.llm import MockLLMService


@pytest.mark.asyncio
async def test_evaluation_runner_offline_flow():
    """Verify that EvaluationRunner runs offline across samples and aggregates metrics."""
    samples = [
        EvaluationSample(
            id="test_01",
            question="What is the refund window?",
            reference_answer="30 days from purchase.",
            relevant_chunk_ids=["chunk_refund"],
            reference_context=["Customers have 30 days to request a refund."],
            category="refund",
            is_answerable=True,
        ),
        EvaluationSample(
            id="test_02",
            question="What is the weather in Paris?",
            reference_answer="I do not have sufficient information in the knowledge base to answer your question.",
            relevant_chunk_ids=[],
            reference_context=[],
            category="out_of_domain",
            is_answerable=False,
        ),
    ]
    dataset = EvaluationDataset(samples)
    runner = EvaluationRunner(dataset=dataset, top_k=3)

    report = await runner.run_offline(top_k=3)
    assert isinstance(report, EvaluationReport)
    assert report.summary.total_samples == 2
    assert report.summary.successful_samples == 2
    assert report.summary.failed_samples == 0
    assert report.summary.mean_precision_at_k > 0.0
    assert report.summary.mean_faithfulness == 1.0


@pytest.mark.asyncio
async def test_evaluation_runner_failure_isolation():
    """Verify that an exception on one sample is isolated and does not abort the run."""
    samples = [
        EvaluationSample(
            id="good_sample",
            question="Good question",
            reference_answer="Good answer",
            relevant_chunk_ids=["c1"],
            reference_context=["Context 1"],
            category="test",
        ),
        EvaluationSample(
            id="bad_sample",
            question="Bad question",
            reference_answer="Bad answer",
            category="test",
        ),
    ]
    dataset = EvaluationDataset(samples)
    runner = EvaluationRunner(dataset=dataset)

    # Monkeypatch evaluate_sample to raise on 'bad_sample'
    original_eval = runner.evaluate_sample

    def faulty_evaluate_sample(sample, *args, **kwargs):
        if sample.id == "bad_sample":
            raise RuntimeError("Simulated evaluator failure")
        return original_eval(sample, *args, **kwargs)

    runner.evaluate_sample = faulty_evaluate_sample  # type: ignore[assignment]

    report = await runner.run_offline()
    assert report.summary.total_samples == 2
    assert report.summary.successful_samples == 1
    assert report.summary.failed_samples == 1

    bad_res = next(r for r in report.sample_results if r.sample_id == "bad_sample")
    assert bad_res.error is not None
    assert "Simulated evaluator failure" in bad_res.error


def test_report_formatting(tmp_path: Path):
    """Verify console, markdown, and JSON report generation."""
    samples = [
        EvaluationSample(
            id="s1",
            question="How do I reset password?",
            reference_answer="Click forgot password.",
            relevant_chunk_ids=["chunk_1"],
            reference_context=["Password instructions."],
            category="auth",
        )
    ]
    runner = EvaluationRunner(dataset=EvaluationDataset(samples))
    sample = samples[0]

    result = runner.evaluate_sample(
        sample=sample,
        retrieved_ids=["chunk_1", "d1"],
        retrieved_contexts=["Password instructions."],
        generated_answer="Click forgot password.",
        execution_time_ms=12.5,
    )

    from backend.app.evaluation.metrics import aggregate_evaluation_results
    summary = aggregate_evaluation_results([result])
    report = EvaluationReport(
        summary=summary,
        sample_results=[result],
        dataset_version="1.0.0",
        configuration={"mode": "test"},
    )

    # Test Console output format
    console_out = format_console_report(report)
    assert "SUPPORTFLOW AI" in console_out
    assert "RETRIEVAL METRICS" in console_out
    assert "auth" in console_out

    # Test Markdown format
    md_out = format_markdown_report(report)
    assert "# SupportFlow AI — RAG Evaluation Report" in md_out
    assert "| **Precision@5** |" in md_out
    assert "| `auth` |" in md_out

    # Test JSON persistence
    out_file = tmp_path / "test_report.json"
    saved = save_report_to_json(report, out_file)
    assert saved.exists()

    with open(saved, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded["dataset_version"] == "1.0.0"
    assert loaded["summary"]["total_samples"] == 1
