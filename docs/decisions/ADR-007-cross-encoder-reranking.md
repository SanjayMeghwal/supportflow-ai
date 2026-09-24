# ADR-007: Local Cross-Encoder Reranking for Precision Knowledge Retrieval

## Status
Accepted

## Context
In Phase 8 (ADR-006), SupportFlow AI introduced Hybrid Search combining dense vector retrieval (`bge-small-en-v1.5` over pgvector HNSW) and PostgreSQL Full-Text Search (ts_rank over GIN), fused via Reciprocal Rank Fusion (RRF).

While Phase 8 achieves high recall by fetching candidates across both semantic concepts and exact keywords, dual-encoder and lexical scoring share inherent ranking limitations:
1. **Bi-Encoder Information Bottleneck:** Dense vector search maps queries and chunks into fixed 384-dimensional representations independently. It cannot perform token-level cross-attention between specific query terms and context passages.
2. **Lexical Disconnect:** FTS relies on surface term frequencies without semantic understanding of syntax or intent.
3. **Rank-Only Heuristic Fusion:** While RRF normalizes heterogeneous scoring distributions, it remains an unweighted ordinal heuristic that treats rank positions uniformly across dissimilar query types.

To achieve enterprise-grade retrieval precision without hallucinations, candidate passages require a second-stage reranker that evaluates full query-document interactions.

## Decision
We implement a **Two-Stage Retrieval Pipeline** using a local, open-source Cross-Encoder model (`cross-encoder/ms-marco-MiniLM-L-6-v2`) to score and reorder candidates retrieved from the Phase 8 hybrid search pipeline.

### 1. Two-Stage Retrieval Pipeline Architecture
```text
                         User Query
                             │
            ┌────────────────┴────────────────┐
            ▼                                 ▼
    Dense Vector Search               PostgreSQL FTS
 (bge-small-en-v1.5 + HNSW)          (ts_rank + GIN)
            │                                 │
            ▼                                 ▼
   Vector Candidates                 FTS Candidates
            │                                 │
            └────────────────┬────────────────┘
                             ▼
                  Reciprocal Rank Fusion
                    (RRF with k = 60)
                             │
                             ▼
                 Bounded Candidate Pool
             [min(top_k * 4, 50) candidates]
                             │
                             ▼
                 Cross-Encoder Reranker
           (ms-marco-MiniLM-L-6-v2, batched)
                             │
                             ▼
                   Final Top-K Results
             (Score + rerank/rrf/system ranks)
```

### 2. Model Selection: `cross-encoder/ms-marco-MiniLM-L-6-v2`
- **Architecture:** 6-layer MiniLM trained on MS MARCO passage ranking.
- **Inference Mechanism:** Joint self-attention over the concatenated `[CLS] query [SEP] chunk [SEP]` tokens, allowing every query token to attend directly to every chunk token.
- **Local & Open-Source:** Runs locally in-process via HuggingFace `sentence-transformers` on CPU/GPU without external API keys, egress costs, or third-party data transmission.
- **Lazy Singleton Lifecycle:** Managed via `backend.app.services.reranker.RerankerService` to eliminate model reloading across requests.

### 3. Bounded Candidate Pool Strategy
Cross-encoder joint attention scales quadratically with sequence length, making full-corpus cross-encoding computationally infeasible. We bound the candidate pool passed from hybrid retrieval:
$$\text{candidate\_pool\_size} = \min(\text{top\_k} \times 4, 50)$$
- For default `top_k = 5`, the cross-encoder scores 20 candidates in a single vectorized batch (`batch_size = 32`).
- A hard ceiling of 50 candidates guarantees bounded latency (< 100ms on modern CPUs) even for maximum allowed `top_k = 50`.

### 4. Metadata Preservation & Score Semantics
Upstream retrieval signals from Phase 7 and Phase 8 are preserved in the response schema:
- `score`: Represents the final ranking score. In `reranked` mode, this equals the cross-encoder logit relevance score.
- `rerank_score`: Explicit cross-encoder output score.
- `rrf_score`: Pre-reranking RRF score from Phase 8.
- `vector_rank` & `fts_rank`: Ordinal ranks from the first-stage retrieval systems.

### 5. API Coexistence
The search endpoint `POST /api/v1/knowledge/search` supports four search modes:
- `search_type="vector"` (default): Phase 7 dense semantic search (100% backward compatible).
- `search_type="full_text"`: Phase 8 PostgreSQL FTS.
- `search_type="hybrid"`: Phase 8 Vector + FTS + RRF.
- `search_type="reranked"`: Phase 9 Hybrid + Cross-Encoder Reranking.

## Consequences & Trade-offs

### Positive
- **Maximum Precision:** Resolves complex, subtle nuances and false-positive semantic matches that escape bi-encoder cosine distance.
- **Zero API Ingestion/Query Fees:** Operates entirely locally with zero recurring inference costs.
- **Data Privacy & Compliance:** Customer queries and proprietary operational documentation never leave internal network boundaries.
- **Transparent Observability:** Retaining `vector_rank`, `fts_rank`, and `rrf_score` alongside `rerank_score` allows complete diagnostic visibility into why a document was selected.

### Negative / Mitigations
- **Computational Cost & Latency:** Cross-encoder inference consumes host CPU cycles and adds ~30–80ms per query.
  - *Mitigation:* The candidate pool is strictly capped at $\le 50$ items, inference uses optimized batching, and lightweight 6-layer MiniLM (`ms-marco-MiniLM-L-6-v2`, ~80MB) is used instead of heavy 12/24-layer models.
- **Initial Model Loading:** The first reranked search request downloads and caches model weights (~80MB).
  - *Mitigation:* Managed via thread-safe lazy singleton with pre-caching capability on startup.
