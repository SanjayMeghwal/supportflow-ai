"""Unit tests for evaluation dataset loading, validation, and filtering."""

import json
from pathlib import Path
import pytest
from backend.app.evaluation.dataset import DatasetError, EvaluationDataset
from backend.app.evaluation.schemas import EvaluationSample


def test_valid_dataset_loading(tmp_path: Path):
    """Verify loading and validating a proper JSON benchmark dataset."""
    sample_data = [
        {
            "id": "sample_001",
            "question": "How do I reset my password?",
            "reference_answer": "Click forgot password on login screen.",
            "relevant_document_ids": ["doc_auth"],
            "relevant_chunk_ids": ["chunk_01"],
            "reference_context": ["Password reset instructions are available."],
            "category": "authentication",
            "difficulty": "easy",
            "is_answerable": True,
        },
        {
            "id": "sample_002",
            "question": "What is the return window?",
            "reference_answer": "30 days from purchase.",
            "relevant_document_ids": ["doc_returns"],
            "relevant_chunk_ids": ["chunk_02"],
            "reference_context": ["Items can be returned within 30 days."],
            "category": "returns",
            "difficulty": "medium",
            "is_answerable": True,
        },
    ]
    file_path = tmp_path / "test_dataset.json"
    file_path.write_text(json.dumps(sample_data), encoding="utf-8")

    dataset = EvaluationDataset.load_from_json(file_path)
    assert len(dataset) == 2
    assert dataset.get_sample("sample_001") is not None
    assert dataset.get_sample("sample_001").category == "authentication"
    assert dataset.categories() == ["authentication", "returns"]


def test_default_benchmark_dataset_loads_properly():
    """Verify that the repository's built-in benchmark dataset loads and validates cleanly."""
    dataset = EvaluationDataset.load_from_json()
    assert len(dataset) >= 15
    # Ensure sample IDs are unique and present
    sample_ids = [s.id for s in dataset]
    assert len(sample_ids) == len(set(sample_ids))
    # Ensure categories include auth, refund, orders, shipping, payments
    cats = dataset.categories()
    for required_cat in ["authentication", "refund", "orders", "shipping", "payments"]:
        assert required_cat in cats
    # Check that unanswerable / negative samples exist
    unanswerable = [s for s in dataset if not s.is_answerable]
    assert len(unanswerable) >= 2


def test_duplicate_sample_id_rejected(tmp_path: Path):
    """Verify that duplicate sample IDs cause a DatasetError."""
    data = [
        {
            "id": "dup_001",
            "question": "Question 1",
            "reference_answer": "Answer 1",
        },
        {
            "id": "dup_001",
            "question": "Question 2",
            "reference_answer": "Answer 2",
        },
    ]
    file_path = tmp_path / "dup.json"
    file_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(DatasetError, match="Duplicate sample ID"):
        EvaluationDataset.load_from_json(file_path)


def test_missing_required_fields_rejected(tmp_path: Path):
    """Verify that samples lacking required fields fail schema validation."""
    data = [
        {
            "id": "missing_q",
            # missing question and reference_answer
        }
    ]
    file_path = tmp_path / "invalid.json"
    file_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(DatasetError, match="Sample validation failed"):
        EvaluationDataset.load_from_json(file_path)


def test_malformed_json_rejected(tmp_path: Path):
    """Verify that corrupt JSON syntax raises DatasetError."""
    file_path = tmp_path / "corrupt.json"
    file_path.write_text("NOT VALID JSON", encoding="utf-8")

    with pytest.raises(DatasetError, match="Malformed JSON"):
        EvaluationDataset.load_from_json(file_path)


def test_empty_dataset_rejected(tmp_path: Path):
    """Verify that an empty JSON array raises DatasetError."""
    file_path = tmp_path / "empty.json"
    file_path.write_text("[]", encoding="utf-8")

    with pytest.raises(DatasetError, match="zero samples"):
        EvaluationDataset.load_from_json(file_path)


def test_nonexistent_dataset_file():
    """Verify that pointing to a non-existent file raises DatasetError."""
    with pytest.raises(DatasetError, match="not found"):
        EvaluationDataset.load_from_json("nonexistent_path/fake_dataset.json")


def test_dataset_filtering():
    """Verify filtering by category, difficulty, answerability, and limit."""
    samples = [
        EvaluationSample(
            id="s1",
            question="Q1",
            reference_answer="A1",
            category="refund",
            difficulty="easy",
            is_answerable=True,
        ),
        EvaluationSample(
            id="s2",
            question="Q2",
            reference_answer="A2",
            category="refund",
            difficulty="hard",
            is_answerable=True,
        ),
        EvaluationSample(
            id="s3",
            question="Q3",
            reference_answer="A3",
            category="auth",
            difficulty="easy",
            is_answerable=False,
        ),
    ]
    dataset = EvaluationDataset(samples)

    # Filter by category
    refunds = dataset.filter(category="refund")
    assert len(refunds) == 2
    assert all(s.category == "refund" for s in refunds)

    # Filter by difficulty
    easy_only = dataset.filter(difficulty="easy")
    assert len(easy_only) == 2

    # Filter by answerability
    unanswerable = dataset.filter(is_answerable=False)
    assert len(unanswerable) == 1
    assert unanswerable.get_sample("s3") is not None

    # Filter with limit
    limited = dataset.filter(limit=1)
    assert len(limited) == 1
