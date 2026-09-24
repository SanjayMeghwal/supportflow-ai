# ADR-006: Hybrid Search with PostgreSQL Full-Text Search and Reciprocal Rank Fusion (RRF)

## Status
Accepted

## Context
SupportFlow AI's Knowledge Base was initially indexed with dense vector embeddings (`BAAI/bge-small-en-v1.5`, 384 dimensions) and pgvector HNSW indexing (ADR-005). While dense retrieval excels at conceptual similarity and paraphrasing (e.g., mapping "I want my money back" to a refund policy), it suffers from notable limitations in enterprise support contexts:
1. **Technical Identifiers & Error Codes:** Exact strings like `ERR_AUTH_TIMEOUT`, `HTTP 409`, or order formats are poorly captured by dense embedding models, which fragment tokens or conflate them with generic syntax.
2. **Product Names & Domain Nomenclature:** Exact part numbers, feature flags, and specific nouns require exact lexical matching.
3. **Out-of-Vocabulary (OOV) Terms:** Specialized terminology absent from embedding pre-training cannot be retrieved reliably via semantic distance alone.

Conversely, standard Lexical Search (PostgreSQL Full-Text Search) is brittle against colloquial phrasing, synonyms, or conceptual queries where customers do not use official policy wording.

## Decision
We implement a **Hybrid Search** engine combining PostgreSQL Full-Text Search (FTS) and dense vector retrieval via **Reciprocal Rank Fusion (RRF)** directly over PostgreSQL without introducing external search engines (e.g., Elasticsearch, OpenSearch, Pinecone).

### 1. PostgreSQL Full-Text Search (FTS)
- **Engine:** Native PostgreSQL Full-Text Search using English dictionary configurations (`english`).
- **Query Parser:** `websearch_to_tsquery('english', query)` is used for natural language queries, supporting implicit AND, quoted phrases, and clean handling of stopword-only or punctuation-heavy input without syntax errors.
- **Scoring:** `ts_rank(to_tsvector('english', chunk_text), websearch_to_tsquery('english', query))` executed entirely in PostgreSQL.
- **Index:** Expression-based Generalized Inverted Index (GIN) on `to_tsvector('english', chunk_text)`:
  ```sql
  CREATE INDEX ix_document_chunks_fts_gin
  ON document_chunks
  USING gin (to_tsvector('english', chunk_text));
  ```
  This provides sub-millisecond lexical lookup without requiring an additional stored column or duplicate storage.

### 2. Candidate Retrieval Strategy
- Dense vector search and FTS execute independently over the identical authorized search space (`kd.is_active = TRUE`).
- Candidate pool per system is bounded by a $4\times$ multiplier up to a maximum ceiling:
  $$\text{candidate\_limit} = \min(\text{top\_k} \times 4, 100)$$
- This ensures documents ranking moderately in one system can still surface when reinforced by the other, while bounding database result sets and preventing $O(N)$ memory transfer.

### 3. Ranking Fusion via Reciprocal Rank Fusion (RRF)
- **Why RRF over Linear Score Blending:**
  - Dense cosine similarity yields bounded scores in $[-1, 1]$ (transformed to $[0, 1]$).
  - PostgreSQL `ts_rank` yields unbounded, scale-dependent positive floats based on term frequencies and document lengths.
  - Linear score combination ($\alpha \cdot S_{\text{vector}} + (1-\alpha) \cdot S_{\text{fts}}$) requires continuous re-tuning, dataset-specific normalizations, and is fragile under distribution shifts.
  - **RRF is scale-invariant:** It operates solely on ordinal rank positions $r \in \{1, 2, \dots\}$, neutralizing score distribution differences.
- **Formula:**
  $$\text{RRF\_Score}(d) = \sum_{m \in \{\text{vector}, \text{fts}\}} \frac{1}{k + r_m(d)}$$
  where smoothing constant $k = 60$ (empirically validated standard by Cormack et al., 2009).
- **Implementation:** Implemented as a database-independent, framework-free pure service (`backend.app.services.ranking.reciprocal_rank_fusion`) with deterministic lexicographic tie-breaking.

### 4. Search Architecture Diagram
```text
                           User Query
                               │
               ┌───────────────┴───────────────┐
               ▼                               ▼
       Dense Vector Search             PostgreSQL FTS
   (bge-small-en-v1.5 + HNSW)         (ts_rank + GIN)
               │                               │
               ▼                               ▼
      Vector Ranked Pool                FTS Ranked Pool
     [Rank 1..N candidates]          [Rank 1..N candidates]
               │                               │
               └───────────────┬───────────────┘
                               ▼
                   Reciprocal Rank Fusion
                    (RRF with k = 60)
                               │
                               ▼
                     Unified Top-K Results
                 (Score + vector/fts rank tags)
```

### 5. API Design & Backward Compatibility
- The `POST /api/v1/knowledge/search` endpoint is extended with an optional `search_type` field:
  - `"vector"` (default): Preserves Phase 7 semantics and backward compatibility.
  - `"full_text"`: Direct PostgreSQL FTS search with `ts_rank` score.
  - `"hybrid"`: Fused candidate retrieval with RRF scoring and rank attribution (`vector_rank`, `fts_rank`).

## Consequences & Trade-offs

### Positive
- **Optimal Retrieval Quality:** Excels across both natural-language conversational queries and exact keyword/error-code lookups.
- **No External Infrastructure:** Leverages native PostgreSQL features without adding Elasticsearch, OpenSearch, or managed vector services.
- **Robust & Calibrated:** RRF eliminates manual score-weight tuning and handles single-system empty result states gracefully.
- **Observability:** Fused results expose individual `vector_rank` and `fts_rank` fields, allowing retrieval diagnostics and ranking evaluation.
- **Backward Compatible:** Existing clients and automated agents continue working without schema breaks.

### Negative / Mitigations
- **Dual Query Execution:** Hybrid search performs two queries (vector ANN and FTS lexical search) per request.
  - *Mitigation:* Both queries are indexed (HNSW for vectors, GIN for FTS) and limited to bounded candidate limits ($\le 100$), keeping response times under tens of milliseconds.
- **GIN Index Write Overhead:** GIN indexes require additional disk updates on document ingestion.
  - *Mitigation:* Document ingestion is a batch administrative workflow, not a high-frequency real-time path.
