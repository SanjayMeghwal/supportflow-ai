"""Unit tests for Phase 8 — Reciprocal Rank Fusion (RRF) ranking algorithm.

All tests are completely database-free. They exercise the pure ranking
function in backend.app.services.ranking.

Test cases
----------
1. Result ranked highly by both systems → highest fused score.
2. Result appearing only in vector results → still returned.
3. Result appearing only in FTS results → still returned.
4. Different ranking positions → RRF arithmetic is correct.
5. Duplicate chunk (same chunk_id in both lists) → contributions summed.
6. Empty vector results → FTS-only results returned correctly.
7. Empty FTS results → vector-only results returned correctly.
8. Both lists empty → empty result set.
9. top_k slicing → result list bounded to top_k.
10. Tie-breaking → deterministic lexicographic ordering on chunk_id.
"""

import pytest
from backend.app.services.ranking import (
    DEFAULT_RRF_K,
    FusedResult,
    RankedCandidate,
    reciprocal_rank_fusion,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_candidate(
    chunk_id: str,
    rank: int,
    content: str = "test content",
    document_id: str = "doc-1",
    document_title: str = "Test Document",
    chunk_index: int = 0,
) -> RankedCandidate:
    """Construct a RankedCandidate with sensible defaults."""
    return RankedCandidate(
        chunk_id=chunk_id,
        rank=rank,
        document_id=document_id,
        document_title=document_title,
        chunk_index=chunk_index,
        content=content,
        metadata={},
    )


def _rrf(rank: int, k: int = DEFAULT_RRF_K) -> float:
    """Compute expected RRF contribution for a single rank."""
    return 1.0 / (k + rank)


# ---------------------------------------------------------------------------
# Case 1: Same result ranked highly by both systems → highest fused score
# ---------------------------------------------------------------------------


def test_rrf_case1_high_rank_both_systems():
    """A chunk at rank 1 in both vector and FTS should receive the highest score."""
    vector = [_make_candidate("chunk-A", rank=1), _make_candidate("chunk-B", rank=2)]
    fts = [_make_candidate("chunk-A", rank=1), _make_candidate("chunk-C", rank=2)]

    results = reciprocal_rank_fusion(vector, fts, top_k=5)

    assert len(results) >= 1
    top = results[0]
    assert top.chunk_id == "chunk-A"

    expected_score = _rrf(1) + _rrf(1)  # appeared at rank 1 in both
    assert abs(top.rrf_score - round(expected_score, 6)) < 1e-9


def test_rrf_case1_both_rank_metadata_populated():
    """A chunk at rank 1 in both systems should have both vector_rank and fts_rank set."""
    vector = [_make_candidate("chunk-A", rank=1)]
    fts = [_make_candidate("chunk-A", rank=1)]

    results = reciprocal_rank_fusion(vector, fts, top_k=5)

    top = results[0]
    assert top.vector_rank == 1
    assert top.fts_rank == 1


# ---------------------------------------------------------------------------
# Case 2: Result appears only in vector results → still returned
# ---------------------------------------------------------------------------


def test_rrf_case2_vector_only_result_retained():
    """A chunk that only appears in vector results should still appear in output."""
    vector = [
        _make_candidate("chunk-vec-only", rank=1),
        _make_candidate("chunk-shared", rank=2),
    ]
    fts = [_make_candidate("chunk-shared", rank=1)]

    results = reciprocal_rank_fusion(vector, fts, top_k=5)

    chunk_ids = [r.chunk_id for r in results]
    assert "chunk-vec-only" in chunk_ids

    # Find the vector-only result and verify its fts_rank is None
    vec_result = next(r for r in results if r.chunk_id == "chunk-vec-only")
    assert vec_result.vector_rank == 1
    assert vec_result.fts_rank is None


# ---------------------------------------------------------------------------
# Case 3: Result appears only in FTS results → still returned
# ---------------------------------------------------------------------------


def test_rrf_case3_fts_only_result_retained():
    """A chunk that only appears in FTS results should still appear in output."""
    vector = [_make_candidate("chunk-shared", rank=1)]
    fts = [
        _make_candidate("chunk-fts-only", rank=1),
        _make_candidate("chunk-shared", rank=2),
    ]

    results = reciprocal_rank_fusion(vector, fts, top_k=5)

    chunk_ids = [r.chunk_id for r in results]
    assert "chunk-fts-only" in chunk_ids

    fts_result = next(r for r in results if r.chunk_id == "chunk-fts-only")
    assert fts_result.fts_rank == 1
    assert fts_result.vector_rank is None


# ---------------------------------------------------------------------------
# Case 4: Different ranking positions → verify RRF arithmetic
# ---------------------------------------------------------------------------


def test_rrf_case4_arithmetic_correctness():
    """Verify exact RRF score calculation for chunks with known ranks."""
    k = DEFAULT_RRF_K

    # chunk-A: vector rank 2, fts rank 4
    # chunk-B: vector rank 1, fts rank 10
    # chunk-C: fts rank 1 only
    vector = [
        _make_candidate("chunk-B", rank=1),
        _make_candidate("chunk-A", rank=2),
    ]
    fts = [
        _make_candidate("chunk-C", rank=1),
        _make_candidate("chunk-A", rank=4),
        _make_candidate("chunk-B", rank=10),
    ]

    results = reciprocal_rank_fusion(vector, fts, top_k=5)
    scores = {r.chunk_id: r.rrf_score for r in results}

    expected_A = round(_rrf(2, k) + _rrf(4, k), 6)
    expected_B = round(_rrf(1, k) + _rrf(10, k), 6)
    expected_C = round(_rrf(1, k), 6)

    assert abs(scores["chunk-A"] - expected_A) < 1e-9
    assert abs(scores["chunk-B"] - expected_B) < 1e-9
    assert abs(scores["chunk-C"] - expected_C) < 1e-9


def test_rrf_case4_ordering_reflects_scores():
    """Results must be ordered by descending RRF score."""
    vector = [_make_candidate("chunk-low", rank=5)]
    fts = [
        _make_candidate("chunk-high", rank=1),
        _make_candidate("chunk-low", rank=2),
    ]

    results = reciprocal_rank_fusion(vector, fts, top_k=5)
    scores = [r.rrf_score for r in results]

    assert scores == sorted(scores, reverse=True), "Results must be ordered highest score first"


# ---------------------------------------------------------------------------
# Case 5: Duplicate candidate → contributions from both lists are combined
# ---------------------------------------------------------------------------


def test_rrf_case5_duplicate_chunk_contributions_combined():
    """The same chunk_id in both lists must accumulate scores from both ranks."""
    k = DEFAULT_RRF_K

    vector = [_make_candidate("chunk-dup", rank=3)]
    fts = [_make_candidate("chunk-dup", rank=3)]

    results = reciprocal_rank_fusion(vector, fts, top_k=5)

    assert len(results) == 1  # deduplicated
    expected = round(_rrf(3, k) + _rrf(3, k), 6)
    assert abs(results[0].rrf_score - expected) < 1e-9

    # Compare: same chunk from only one system gets lower score
    vector_only = [_make_candidate("chunk-dup", rank=3)]
    results_single = reciprocal_rank_fusion(vector_only, [], top_k=5)
    assert results[0].rrf_score > results_single[0].rrf_score


# ---------------------------------------------------------------------------
# Case 6: Empty vector results → FTS results flow through
# ---------------------------------------------------------------------------


def test_rrf_case6_empty_vector_results():
    """When vector results are empty, FTS results should still be returned."""
    fts = [
        _make_candidate("chunk-A", rank=1),
        _make_candidate("chunk-B", rank=2),
    ]

    results = reciprocal_rank_fusion([], fts, top_k=5)

    assert len(results) == 2
    assert results[0].chunk_id == "chunk-A"
    assert results[1].chunk_id == "chunk-B"

    for r in results:
        assert r.vector_rank is None
        assert r.fts_rank is not None


# ---------------------------------------------------------------------------
# Case 7: Empty FTS results → vector results flow through
# ---------------------------------------------------------------------------


def test_rrf_case7_empty_fts_results():
    """When FTS results are empty, vector results should still be returned."""
    vector = [
        _make_candidate("chunk-A", rank=1),
        _make_candidate("chunk-B", rank=2),
    ]

    results = reciprocal_rank_fusion(vector, [], top_k=5)

    assert len(results) == 2
    assert results[0].chunk_id == "chunk-A"
    assert results[1].chunk_id == "chunk-B"

    for r in results:
        assert r.fts_rank is None
        assert r.vector_rank is not None


# ---------------------------------------------------------------------------
# Case 8: Both lists empty → empty result set
# ---------------------------------------------------------------------------


def test_rrf_case8_both_empty_returns_empty():
    """When both input lists are empty, the result must be empty."""
    results = reciprocal_rank_fusion([], [], top_k=5)
    assert results == []


# ---------------------------------------------------------------------------
# Additional edge cases
# ---------------------------------------------------------------------------


def test_rrf_top_k_slicing():
    """Results are bounded to top_k regardless of candidate pool size."""
    vector = [_make_candidate(f"chunk-{i}", rank=i + 1) for i in range(10)]
    fts = [_make_candidate(f"chunk-{i}", rank=i + 1) for i in range(10)]

    results = reciprocal_rank_fusion(vector, fts, top_k=3)
    assert len(results) == 3


def test_rrf_top_k_larger_than_candidates():
    """top_k larger than total unique candidates returns all candidates."""
    vector = [_make_candidate("chunk-A", rank=1)]
    fts = [_make_candidate("chunk-B", rank=1)]

    results = reciprocal_rank_fusion(vector, fts, top_k=100)
    assert len(results) == 2


def test_rrf_custom_k_parameter():
    """Custom k value should be used in the RRF formula."""
    custom_k = 10
    vector = [_make_candidate("chunk-A", rank=1)]
    fts = [_make_candidate("chunk-A", rank=1)]

    results = reciprocal_rank_fusion(vector, fts, top_k=5, k=custom_k)

    expected = round(1.0 / (custom_k + 1) + 1.0 / (custom_k + 1), 6)
    assert abs(results[0].rrf_score - expected) < 1e-9


def test_rrf_payload_content_preserved():
    """Chunk payload (content, metadata, document info) is preserved in output."""
    vector = [
        RankedCandidate(
            chunk_id="chunk-A",
            rank=1,
            document_id="doc-xyz",
            document_title="Security Policy",
            chunk_index=3,
            content="Password reset instructions go here.",
            metadata={"source": "pdf", "page": 2},
        )
    ]

    results = reciprocal_rank_fusion(vector, [], top_k=5)

    assert len(results) == 1
    r = results[0]
    assert r.chunk_id == "chunk-A"
    assert r.document_id == "doc-xyz"
    assert r.document_title == "Security Policy"
    assert r.chunk_index == 3
    assert r.content == "Password reset instructions go here."
    assert r.metadata == {"source": "pdf", "page": 2}


def test_rrf_deterministic_tie_breaking():
    """When two chunks have identical RRF scores, ordering is deterministic."""
    # Both chunks appear only in one system at the same rank → identical scores
    vector = [_make_candidate("chunk-zzz", rank=1)]
    fts = [_make_candidate("chunk-aaa", rank=1)]

    results_1 = reciprocal_rank_fusion(vector, fts, top_k=5)
    results_2 = reciprocal_rank_fusion(vector, fts, top_k=5)

    # Same call must always produce the same order
    assert [r.chunk_id for r in results_1] == [r.chunk_id for r in results_2]

    # Lexicographically smaller chunk_id should come first on tie
    ids = [r.chunk_id for r in results_1]
    assert ids == sorted(ids)  # "chunk-aaa" < "chunk-zzz"
