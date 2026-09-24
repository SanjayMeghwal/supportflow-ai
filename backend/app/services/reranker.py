"""Local Cross-Encoder reranking service using sentence-transformers.

Provides deep cross-attention relevance scoring for retrieved candidate chunks.
Unlike bi-encoder embeddings that compute vector cosine similarity independently,
the cross-encoder performs joint self-attention over the query and candidate chunk
simultaneously, yielding significantly higher relevance accuracy.

Design guarantees:
- Completely open-source & local (zero external API calls or costs).
- Lazy singleton model initialization (avoids reloading weights per request).
- Batched inference for efficiency over candidate pools.
- Preserves upstream retrieval metadata (vector_rank, fts_rank, rrf_score).
- Pluggable/mockable architecture for deterministic unit testing.
"""

from __future__ import annotations

import os
from typing import Any, Optional
from sentence_transformers import CrossEncoder

from backend.app.core.config import settings

# Disable harmless symlinks warning on Windows when running unprivileged
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


class RerankerService:
    """Manages local cross-encoder models for scoring and reordering candidate chunks."""

    def __init__(self, model_name: Optional[str] = None) -> None:
        self.model_name = model_name or settings.RERANKER_MODEL_NAME
        self._model: Optional[CrossEncoder] = None

    @property
    def model(self) -> CrossEncoder:
        """Lazy loader for the CrossEncoder model."""
        if self._model is None:
            self._model = CrossEncoder(self.model_name)
        return self._model

    def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        top_k: int = 5,
        batch_size: int = 32,
    ) -> list[dict[str, Any]]:
        """Rerank a list of candidate chunk dictionaries against a user query.

        Parameters
        ----------
        query:
            User natural language query.
        candidates:
            List of candidate dictionaries from hybrid retrieval. Each candidate must
            contain a 'content' key (the chunk text). Upstream fields ('chunk_id',
            'document_id', 'document_title', 'chunk_index', 'vector_rank', 'fts_rank',
            'metadata', and 'score' representing the RRF score) are preserved.
        top_k:
            Maximum number of top-scoring reranked results to return.
        batch_size:
            Batch size for cross-encoder inference.

        Returns
        -------
        list[dict[str, Any]]
            Top ``top_k`` candidates sorted by descending cross-encoder relevance score.
            Each dictionary contains:
            - chunk_id, document_id, document_title, chunk_index, content, metadata
            - vector_rank: rank from vector retrieval (or None)
            - fts_rank: rank from FTS lexical search (or None)
            - rrf_score: previous RRF score from hybrid retrieval
            - rerank_score: raw cross-encoder relevance score (rounded to 6 decimals)
            - score: equal to rerank_score for unified sorting
        """
        if not query or not query.strip():
            raise ValueError("Query string cannot be empty or whitespace-only.")

        if top_k < 1:
            raise ValueError("top_k must be at least 1.")

        if not candidates:
            return []

        cleaned_query = query.strip()

        # Build (query, document) pairs for joint scoring
        pairs: list[tuple[str, str]] = []
        for idx, cand in enumerate(candidates):
            content = cand.get("content", "")
            if not isinstance(content, str):
                raise TypeError(f"Candidate at index {idx} has non-string content.")
            pairs.append((cleaned_query, content.strip()))

        # Score candidates in batch
        scores = self.model.predict(
            pairs,
            batch_size=batch_size,
            show_progress_bar=False,
        )

        # CrossEncoder.predict can return a numpy array or float
        scored_candidates: list[dict[str, Any]] = []
        for cand, raw_score in zip(candidates, scores):
            float_score = round(float(raw_score), 6)
            # Retain original RRF score if present in 'score' or 'rrf_score'
            orig_rrf_score = cand.get("rrf_score", cand.get("score"))
            if orig_rrf_score is not None:
                orig_rrf_score = round(float(orig_rrf_score), 6)

            item = {
                "chunk_id": cand["chunk_id"],
                "document_id": cand["document_id"],
                "document_title": cand["document_title"],
                "chunk_index": cand["chunk_index"],
                "content": cand["content"],
                "score": float_score,
                "rerank_score": float_score,
                "rrf_score": orig_rrf_score,
                "vector_rank": cand.get("vector_rank"),
                "fts_rank": cand.get("fts_rank"),
                "metadata": cand.get("metadata", {}),
            }
            scored_candidates.append(item)

        # Sort by descending reranker score; break ties deterministically by chunk_id
        scored_candidates.sort(
            key=lambda c: (-c["rerank_score"], str(c.get("chunk_id", "")))
        )

        return scored_candidates[:top_k]


# Global singleton instance
_reranker_service_instance: Optional[RerankerService] = None


def get_reranker_service() -> RerankerService:
    """Dependency / accessor for the singleton RerankerService."""
    global _reranker_service_instance
    if _reranker_service_instance is None:
        _reranker_service_instance = RerankerService()
    return _reranker_service_instance
