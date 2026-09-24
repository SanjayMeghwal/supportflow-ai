"""Unit tests for Phase 9 — Local Cross-Encoder Reranker Service.

All unit tests (except the isolated real-model smoke test) mock the CrossEncoder
to ensure fast, deterministic execution without downloading or reloading weights.
"""

from typing import Any
from unittest.mock import MagicMock, patch
import pytest

from backend.app.services.reranker import RerankerService, get_reranker_service


# ---------------------------------------------------------------------------
# Helpers & Fixtures
# ---------------------------------------------------------------------------


def _make_candidate(
    chunk_id: str,
    content: str,
    score: float = 0.02,
    document_id: str = "doc-1",
    document_title: str = "Test Document",
    chunk_index: int = 0,
    vector_rank: int | None = 1,
    fts_rank: int | None = 2,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a mock candidate dictionary mimicking hybrid search output."""
    return {
        "chunk_id": chunk_id,
        "document_id": document_id,
        "document_title": document_title,
        "chunk_index": chunk_index,
        "content": content,
        "score": score,
        "vector_rank": vector_rank,
        "fts_rank": fts_rank,
        "metadata": metadata or {"tag": "unit-test"},
    }


# ---------------------------------------------------------------------------
# Unit Tests (Mocked CrossEncoder)
# ---------------------------------------------------------------------------


def test_reranker_empty_candidates_returns_empty():
    """Empty candidate list must return an empty list immediately without calling model."""
    service = RerankerService(model_name="mock-model")
    service._model = MagicMock()

    results = service.rerank("any query", [], top_k=5)

    assert results == []
    service._model.predict.assert_not_called()


def test_reranker_single_candidate():
    """Single candidate is scored and returned with metadata preserved."""
    service = RerankerService(model_name="mock-model")
    mock_model = MagicMock()
    mock_model.predict.return_value = [0.85]
    service._model = mock_model

    cand = _make_candidate("c-1", "Authentication portal instructions", score=0.016)
    results = service.rerank("how to log in", [cand], top_k=5)

    assert len(results) == 1
    res = results[0]
    assert res["chunk_id"] == "c-1"
    assert res["rerank_score"] == 0.85
    assert res["score"] == 0.85
    assert res["rrf_score"] == 0.016
    assert res["vector_rank"] == 1
    assert res["fts_rank"] == 2
    assert res["document_title"] == "Test Document"
    assert res["metadata"] == {"tag": "unit-test"}


def test_reranker_sorts_by_descending_relevance():
    """Candidates must be sorted by cross-encoder score descending, regardless of input order."""
    service = RerankerService(model_name="mock-model")
    mock_model = MagicMock()
    # Mock scores: cand-1 gets -2.5, cand-2 gets 5.1, cand-3 gets 1.2
    mock_model.predict.return_value = [-2.5, 5.1, 1.2]
    service._model = mock_model

    candidates = [
        _make_candidate("c-1", "Low relevance content"),
        _make_candidate("c-2", "High relevance content"),
        _make_candidate("c-3", "Medium relevance content"),
    ]

    results = service.rerank("target query", candidates, top_k=3)

    assert len(results) == 3
    assert results[0]["chunk_id"] == "c-2"
    assert results[0]["rerank_score"] == 5.1
    assert results[1]["chunk_id"] == "c-3"
    assert results[1]["rerank_score"] == 1.2
    assert results[2]["chunk_id"] == "c-1"
    assert results[2]["rerank_score"] == -2.5


def test_reranker_slices_to_top_k():
    """Output length is bounded by top_k."""
    service = RerankerService(model_name="mock-model")
    mock_model = MagicMock()
    mock_model.predict.return_value = [0.9, 0.8, 0.7, 0.6, 0.5]
    service._model = mock_model

    candidates = [_make_candidate(f"c-{i}", f"content {i}") for i in range(5)]

    results = service.rerank("query", candidates, top_k=2)

    assert len(results) == 2
    assert results[0]["chunk_id"] == "c-0"
    assert results[1]["chunk_id"] == "c-1"


def test_reranker_batch_inference_called():
    """Verify that model.predict receives candidate pairs and batch_size."""
    service = RerankerService(model_name="mock-model")
    mock_model = MagicMock()
    mock_model.predict.return_value = [0.1, 0.2]
    service._model = mock_model

    candidates = [
        _make_candidate("c-1", "First chunk"),
        _make_candidate("c-2", "Second chunk"),
    ]

    service.rerank("search prompt", candidates, top_k=5, batch_size=16)

    mock_model.predict.assert_called_once_with(
        [("search prompt", "First chunk"), ("search prompt", "Second chunk")],
        batch_size=16,
        show_progress_bar=False,
    )


def test_reranker_deterministic_tie_breaking():
    """When candidates have identical rerank scores, ordering is deterministic by chunk_id."""
    service = RerankerService(model_name="mock-model")
    mock_model = MagicMock()
    mock_model.predict.return_value = [2.0, 2.0]
    service._model = mock_model

    candidates = [
        _make_candidate("chunk-zzz", "Content Z"),
        _make_candidate("chunk-aaa", "Content A"),
    ]

    results = service.rerank("query", candidates, top_k=2)

    assert results[0]["chunk_id"] == "chunk-aaa"
    assert results[1]["chunk_id"] == "chunk-zzz"


def test_reranker_invalid_query_raises_value_error():
    """Empty or whitespace-only query raises ValueError."""
    service = RerankerService(model_name="mock-model")
    with pytest.raises(ValueError, match="empty or whitespace-only"):
        service.rerank("", [_make_candidate("c-1", "content")])

    with pytest.raises(ValueError, match="empty or whitespace-only"):
        service.rerank("   ", [_make_candidate("c-1", "content")])


def test_reranker_invalid_top_k_raises_value_error():
    """top_k < 1 raises ValueError."""
    service = RerankerService(model_name="mock-model")
    with pytest.raises(ValueError, match="top_k must be at least 1"):
        service.rerank("query", [_make_candidate("c-1", "content")], top_k=0)


def test_reranker_non_string_content_raises_type_error():
    """Candidate with non-string content raises TypeError."""
    service = RerankerService(model_name="mock-model")
    candidates = [{"chunk_id": "c-1", "content": 12345}]
    with pytest.raises(TypeError, match="non-string content"):
        service.rerank("query", candidates)


def test_reranker_lazy_model_loading():
    """Model is not instantiated until .model property is accessed."""
    service = RerankerService(model_name="test-model")
    assert service._model is None

    with patch("backend.app.services.reranker.CrossEncoder") as mock_ce_class:
        mock_instance = MagicMock()
        mock_ce_class.return_value = mock_instance

        loaded = service.model
        assert loaded == mock_instance
        assert service._model == mock_instance
        mock_ce_class.assert_called_once_with("test-model")


def test_reranker_singleton_accessor():
    """get_reranker_service returns a singleton instance."""
    s1 = get_reranker_service()
    s2 = get_reranker_service()
    assert s1 is s2


# ---------------------------------------------------------------------------
# Controlled Reranking Behavior Test (Part 15)
# ---------------------------------------------------------------------------


def test_controlled_reranking_behavior():
    """Verify password recovery candidate is ranked above refund and 2FA candidates.

    Query: 'I forgot my password and cannot access my account'
    Candidate A: To reset your account password, verify your registered email address.
    Candidate B: Refunds are processed within five business days.
    Candidate C: Two-factor authentication protects account login.
    """
    service = RerankerService(model_name="mock-model")
    mock_model = MagicMock()
    # High score for password reset, low for refund, moderate for 2FA
    mock_model.predict.return_value = [5.4, -4.1, 0.8]
    service._model = mock_model

    query = "I forgot my password and cannot access my account"
    candidates = [
        _make_candidate("cand-pw", "To reset your account password, verify your registered email address."),
        _make_candidate("cand-refund", "Refunds are processed within five business days."),
        _make_candidate("cand-2fa", "Two-factor authentication protects account login."),
    ]

    results = service.rerank(query, candidates, top_k=3)

    assert results[0]["chunk_id"] == "cand-pw"
    assert results[0]["rerank_score"] > results[1]["rerank_score"]
    assert results[1]["chunk_id"] == "cand-2fa"
    assert results[2]["chunk_id"] == "cand-refund"


# ---------------------------------------------------------------------------
# Real Model Local Smoke Test (Part 17)
# ---------------------------------------------------------------------------


def test_real_model_smoke_test():
    """Smoke test verifying actual inference with the cached local cross-encoder model.

    Confirms:
    - sentence_transformers.CrossEncoder imports and initializes
    - Local cached weights load properly
    - Predict produces float scores without exceptions
    """
    service = RerankerService()  # uses default settings.RERANKER_MODEL_NAME
    query = "How to reset account password"
    candidates = [
        _make_candidate("pw-chunk", "Click the link in your email to reset your account password."),
        _make_candidate("refund-chunk", "Items returned within 30 days receive a full refund to credit card."),
    ]

    results = service.rerank(query, candidates, top_k=2)

    assert len(results) == 2
    # Verify both returned scores are real numbers
    assert isinstance(results[0]["rerank_score"], float)
    assert isinstance(results[1]["rerank_score"], float)

    # Password chunk should have a significantly higher relevance score than refund chunk
    pw_result = next(r for r in results if r["chunk_id"] == "pw-chunk")
    refund_result = next(r for r in results if r["chunk_id"] == "refund-chunk")
    assert pw_result["rerank_score"] > refund_result["rerank_score"]
