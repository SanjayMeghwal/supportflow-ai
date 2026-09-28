#!/usr/bin/env python3
"""CLI utility to execute the SupportFlow AI RAG benchmark evaluation suite.

Usage:
    python scripts/run_evaluation.py
    python scripts/run_evaluation.py --category refund --top-k 5
    python scripts/run_evaluation.py --output evaluation/results/custom_report.json
"""

import argparse
import asyncio
from pathlib import Path
import sys

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.evaluation.dataset import EvaluationDataset
from backend.app.evaluation.report import (
    format_console_report,
    format_markdown_report,
    save_report_to_json,
)
from backend.app.evaluation.runner import EvaluationRunner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run SupportFlow AI RAG grounding, faithfulness, and retrieval quality evaluation."
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default=None,
        help="Path to custom benchmark dataset JSON file.",
    )
    parser.add_argument(
        "--category",
        type=str,
        default=None,
        help="Filter evaluation to a specific category (e.g. 'refund', 'authentication', 'orders').",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Top-K cutoff for retrieval metrics (default: 5).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit evaluation to first N samples.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="evaluation/results/latest_report.json",
        help="Output path for the generated JSON report.",
    )
    parser.add_argument(
        "--format",
        choices=["console", "markdown", "json"],
        default="console",
        help="Output display format (default: console).",
    )
    return parser.parse_args()


async def main() -> int:
    args = parse_args()

    # Load dataset
    try:
        dataset = EvaluationDataset.load_from_json(args.dataset)
        if args.category or args.limit:
            dataset = dataset.filter(category=args.category, limit=args.limit)
    except Exception as exc:
        print(f"Error loading dataset: {exc}", file=sys.stderr)
        return 1

    runner = EvaluationRunner(dataset=dataset, top_k=args.top_k)
    report = await runner.run_offline(top_k=args.top_k)

    # Save JSON report
    out_path = Path(args.output)
    save_report_to_json(report, out_path)

    # Print requested output format
    if args.format == "console":
        print(format_console_report(report))
        print(f"\nReport written to: {out_path.resolve()}\n")
    elif args.format == "markdown":
        print(format_markdown_report(report))
    elif args.format == "json":
        print(report.model_dump_json(indent=2))

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
