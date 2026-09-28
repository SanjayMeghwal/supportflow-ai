"""Evaluation report generation, formatting, and persistence.

Supports formatted terminal output, markdown summaries, and JSON reports.
"""

import json
from pathlib import Path
from typing import Optional

from backend.app.evaluation.schemas import EvaluationReport


def format_console_report(report: EvaluationReport) -> str:
    """Format an EvaluationReport into a clean, human-readable terminal table."""
    summary = report.summary
    lines: list[str] = []

    lines.append("=" * 64)
    lines.append("         SUPPORTFLOW AI - RAG EVALUATION REPORT         ")
    lines.append("=" * 64)
    lines.append(f"Timestamp:        {report.timestamp}")
    lines.append(f"Dataset Version:  {report.dataset_version}")
    lines.append(f"Total Samples:    {summary.total_samples}")
    lines.append(f"Successful:       {summary.successful_samples} | Failed: {summary.failed_samples}")
    lines.append("-" * 64)
    lines.append("RETRIEVAL METRICS")
    lines.append(f"  Precision@5:      {summary.mean_precision_at_k:.4f}")
    lines.append(f"  Recall@5:         {summary.mean_recall_at_k:.4f}")
    lines.append(f"  MRR:              {summary.mean_mrr:.4f}")
    lines.append("-" * 64)
    lines.append("RAG QUALITY METRICS (RAGAS-STYLE)")
    lines.append(f"  Context Relevance:{summary.mean_context_relevance:.4f}")
    lines.append(f"  Answer Relevance: {summary.mean_answer_relevance:.4f}")
    lines.append(f"  Faithfulness:     {summary.mean_faithfulness:.4f}")
    lines.append(f"  Hallucination Rate:{summary.hallucination_rate:.4f} ({summary.hallucination_rate * 100:.1f}%)")
    lines.append("-" * 64)

    if summary.by_category:
        lines.append("METRICS BY CATEGORY")
        lines.append(f"  {'Category':<16} {'Count':<6} {'P@5':<8} {'R@5':<8} {'MRR':<8} {'Faith':<8}")
        lines.append("  " + "-" * 56)
        for cat, stats in summary.by_category.items():
            lines.append(
                f"  {cat:<16} {stats['sample_count']:<6} "
                f"{stats['precision_at_k']:<8.2f} {stats['recall_at_k']:<8.2f} "
                f"{stats['mrr']:<8.2f} {stats['faithfulness']:<8.2f}"
            )
        lines.append("-" * 64)

    lines.append("=" * 64)
    return "\n".join(lines)


def format_markdown_report(report: EvaluationReport) -> str:
    """Format an EvaluationReport into Markdown suitable for documentation or PR comments."""
    summary = report.summary
    md: list[str] = []

    md.append("# SupportFlow AI — RAG Evaluation Report")
    md.append("")
    md.append(f"- **Timestamp:** `{report.timestamp}`")
    md.append(f"- **Dataset Version:** `{report.dataset_version}`")
    md.append(f"- **Total Samples:** `{summary.total_samples}` (Success: `{summary.successful_samples}`, Failed: `{summary.failed_samples}`)")
    md.append("")
    md.append("## Overall Summary")
    md.append("")
    md.append("| Metric | Score | Description |")
    md.append("|---|---|---|")
    md.append(f"| **Precision@5** | `{summary.mean_precision_at_k:.4f}` | Fraction of retrieved chunks that are relevant |")
    md.append(f"| **Recall@5** | `{summary.mean_recall_at_k:.4f}` | Fraction of known relevant chunks retrieved |")
    md.append(f"| **MRR** | `{summary.mean_mrr:.4f}` | Mean reciprocal rank of first relevant chunk |")
    md.append(f"| **Context Relevance** | `{summary.mean_context_relevance:.4f}` | Proportion of retrieved context relevant to query |")
    md.append(f"| **Answer Relevance** | `{summary.mean_answer_relevance:.4f}` | Alignment between answer and question intent |")
    md.append(f"| **Faithfulness** | `{summary.mean_faithfulness:.4f}` | Proportion of claims grounded in retrieved context |")
    md.append(f"| **Hallucination Rate** | `{summary.hallucination_rate:.4f}` | Percentage of answers containing ungrounded claims |")
    md.append("")

    if summary.by_category:
        md.append("## Category Breakdown")
        md.append("")
        md.append("| Category | Count | Precision@5 | Recall@5 | MRR | Faithfulness |")
        md.append("|---|---|---|---|---|---|")
        for cat, stats in summary.by_category.items():
            md.append(
                f"| `{cat}` | {stats['sample_count']} | {stats['precision_at_k']:.2f} | "
                f"{stats['recall_at_k']:.2f} | {stats['mrr']:.2f} | {stats['faithfulness']:.2f} |"
            )
        md.append("")

    return "\n".join(md)


def save_report_to_json(report: EvaluationReport, output_path: str | Path) -> Path:
    """Save an EvaluationReport as a pretty-printed JSON file."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(report.model_dump_json(indent=2))
    return path
