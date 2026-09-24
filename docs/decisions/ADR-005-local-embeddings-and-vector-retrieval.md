# ADR-005: Local Dense Vector Embeddings and pgvector Retrieval

## Status
Accepted

## Context
SupportFlow AI requires semantic vector retrieval to retrieve relevant policy, FAQ, and troubleshooting documentation for customer support inquiries.
Common commercial approaches rely on third-party SaaS embedding APIs (e.g., OpenAI `text-embedding-3-small`, Cohere, Google Vertex).
However, proprietary cloud embedding APIs introduce:
1. Recurring per-token monetary costs.
2. External network latency and availability dependencies.
3. Data privacy concerns (sending sensitive customer policy and operational data to external providers).
4. Potential model deprecation or vendor lock-in.

## Decision
We adopt **local open-source sentence-transformers** (`BAAI/bge-small-en-v1.5`) producing 384-dimensional dense vectors, coupled with **PostgreSQL `pgvector` HNSW indexing** using cosine distance (`vector_cosine_ops`).

1. **Embedding Model:** `BAAI/bge-small-en-v1.5` running locally via HuggingFace `sentence-transformers` on CPU/GPU.
2. **Dimensionality:** Fixed at 384 dimensions (`EMBEDDING_DIMENSION = 384`), centrally defined and validated.
3. **Normalization:** All generated vectors are L2-normalized upon inference, allowing cosine similarity to be calculated via distance formula $1 - \text{cosine\_distance}$.
4. **Lifecycle & Persistence:** Embeddings are generated in batches during document ingestion and saved atomically alongside chunk records in `document_chunks.embedding`.
5. **Index:** Hierarchical Navigable Small World (HNSW) index (`ix_document_chunks_embedding_hnsw`) using `vector_cosine_ops` for sub-millisecond approximate nearest neighbor (ANN) retrieval.

## Consequences & Trade-offs

### Positive
- **Zero API Costs:** Unlimited embedding generation and query retrieval without external fees.
- **Privacy & Security:** Document content never leaves the internal system boundaries.
- **Offline & Air-Gapped Capable:** Operates without continuous internet connectivity once model weights are locally cached.
- **Predictable Latency:** In-process inference and local PostgreSQL index scans eliminate WAN overhead.
- **Atomic Operations:** Embeddings are committed within the same database transaction as the document and text chunks.

### Negative / Mitigations
- **Initial Model Download:** First startup downloads ~120MB model weights from HuggingFace Hub.
  - *Mitigation:* Weights are persistently cached locally in `.cache/huggingface/hub`. Model loading is managed via a thread-safe lazy singleton (`EmbeddingService`).
- **CPU Resource Usage:** Batch embedding generation utilizes host CPU cycles during large document ingestion.
  - *Mitigation:* Ingestion is an asynchronous operational action restricted to Support Agents and Admins, bounded by 10MB upload limits and a chunk size of 500 characters.
