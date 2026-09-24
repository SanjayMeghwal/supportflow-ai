"""Reciprocal Rank Fusion (RRF) ranking algorithm.

This module is intentionally database-free and framework-free.
It can be imported and unit-tested without any database connection,
FastAPI instance, or embedding model.

Algorithm
---------
RRF combines ranked result lists from heterogeneous retrieval systems
without requiring their raw scores to be on a comparable scale.
Given N ranked lists, the fused score for a document d is:

    RRF_score(d) = Σᵢ  1 / (k + rankᵢ(d))

where:
    rankᵢ(d)  = 1-indexed rank of d in system i  (1 = best match)
    k         = smoothing constant (default 60, from Cormack et al. 2009)
    Σᵢ        = sum over all retrieval systems that contain d

The constant k = 60 is the standard empirically-validated value.
It prevents very highly-ranked documents from dominating the fused score
and ensures that results appearing in only one system can still surface.

Rationale for RRF over weighted score combination
--------------------------------------------------
Vector cosine similarity scores and PostgreSQL ts_rank scores are produced
by fundamentally different scoring functions:
- Cosine similarity: bounded [−1, 1], typically [0.5, 1.0] for normalized
  embeddings after the 1-distance transform.
- ts_rank: unbounded positive float, dependent on term frequency, document
  length, and normalization options.

Combining these scores directly with weights would require careful
per-system calibration and would be fragile under distribution shifts.
RRF sidesteps this by operating only on ordinal rank positions, making it
robust and parameter-free beyond k.

Reference
---------
Cormack, Clarke, Buettcher (2009). "Reciprocal Rank Fusion Outperforms
Condorcet and Individual Rank Learning Methods." SIGIR 2009.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RankedCandidate:
    """A single search result from one retrieval system, carrying its rank.

    Attributes
    ----------
    chunk_id:
        Stable identifier used to match the same chunk across systems.
        Should be a string representation of the UUID to keep this module
        framework-independent.
    rank:
        1-indexed rank position within the result list for this system.
        Rank 1 = best match.
    document_id:
        Parent document UUID string (preserved for downstream assembly).
    document_title:
        Human-readable document title (preserved for response assembly).
    chunk_index:
        Sequential position of the chunk within its parent document.
    content:
        Raw chunk text (preserved for response assembly).
    metadata:
        Arbitrary key-value metadata stored alongside the chunk.
    """

    chunk_id: str
    rank: int
    document_id: str
    document_title: str
    chunk_index: int
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FusedResult:
    """A single hybrid search result produced by RRF fusion.

    Attributes
    ----------
    chunk_id:       Stable chunk identifier.
    document_id:    Parent document identifier.
    document_title: Human-readable document title.
    chunk_index:    Sequential chunk position within the document.
    content:        Raw chunk text.
    rrf_score:      Fused RRF score (higher = more relevant overall).
    vector_rank:    Rank from dense vector search, or None if absent.
    fts_rank:       Rank from full-text search, or None if absent.
    metadata:       Arbitrary chunk metadata.
    """

    chunk_id: str
    document_id: str
    document_title: str
    chunk_index: int
    content: str
    rrf_score: float
    vector_rank: int | None
    fts_rank: int | None
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# RRF implementation
# ---------------------------------------------------------------------------

#: Standard RRF smoothing constant (Cormack et al. 2009).
DEFAULT_RRF_K: int = 60


def reciprocal_rank_fusion(
    vector_results: list[RankedCandidate],
    fts_results: list[RankedCandidate],
    *,
    top_k: int,
    k: int = DEFAULT_RRF_K,
) -> list[FusedResult]:
    """Fuse vector and full-text search ranked lists using Reciprocal Rank Fusion.

    Parameters
    ----------
    vector_results:
        Ranked candidates from dense vector (pgvector) retrieval.
        The list must already be ordered best-first (rank 1 = index 0).
    fts_results:
        Ranked candidates from PostgreSQL full-text search.
        The list must already be ordered best-first (rank 1 = index 0).
    top_k:
        Number of final results to return.
    k:
        RRF smoothing constant.  Default: 60.

    Returns
    -------
    list[FusedResult]
        Up to ``top_k`` results ordered by descending RRF score.
        Ties are broken deterministically by chunk_id (lexicographic).

    Edge cases handled
    ------------------
    * Empty vector_results   → FTS-only results are returned.
    * Empty fts_results      → Vector-only results are returned.
    * Both empty             → Empty list is returned.
    * Same chunk in both     → Contributions from both ranks are summed.
    """
    if not vector_results and not fts_results:
        return []

    # Accumulate RRF scores: chunk_id → running score
    scores: dict[str, float] = {}

    # Track per-chunk ranks and payload data
    vector_ranks: dict[str, int] = {}
    fts_ranks: dict[str, int] = {}
    payloads: dict[str, RankedCandidate] = {}

    # Process vector results
    for candidate in vector_results:
        cid = candidate.chunk_id
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + candidate.rank)
        vector_ranks[cid] = candidate.rank
        payloads[cid] = candidate

    # Process FTS results
    for candidate in fts_results:
        cid = candidate.chunk_id
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + candidate.rank)
        fts_ranks[cid] = candidate.rank
        # FTS result is the authoritative payload if chunk not in vector results
        # (vector payload takes priority for content since it's always present)
        if cid not in payloads:
            payloads[cid] = candidate

    # Sort by descending RRF score; break ties lexicographically by chunk_id
    sorted_ids = sorted(
        scores.keys(),
        key=lambda cid: (-scores[cid], cid),
    )

    fused: list[FusedResult] = []
    for cid in sorted_ids[:top_k]:
        payload = payloads[cid]
        fused.append(
            FusedResult(
                chunk_id=cid,
                document_id=payload.document_id,
                document_title=payload.document_title,
                chunk_index=payload.chunk_index,
                content=payload.content,
                rrf_score=round(scores[cid], 6),
                vector_rank=vector_ranks.get(cid),
                fts_rank=fts_ranks.get(cid),
                metadata=payload.metadata,
            )
        )

    return fused
