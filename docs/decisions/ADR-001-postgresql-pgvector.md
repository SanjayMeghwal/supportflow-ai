# ADR-001: Unified Relational and Vector Storage via PostgreSQL + pgvector

## Status
Accepted

## Context
SupportFlow AI requires transactional relational persistence (users, tickets, messages, orders, payments, audit logs) and dense vector similarity search for Knowledge-Base retrieval (RAG).
Many AI projects adopt specialized, standalone vector databases (e.g., Pinecone, Milvus, Qdrant, Chroma).

## Decision
We adopt **PostgreSQL 16+ with the `pgvector` extension** as our single unified data store for both relational data and vector embeddings.

## Consequences & Trade-offs
### Positive
- **Single Source of Truth:** Eliminates data drift and dual-write synchronization issues between an external vector DB and the operational database.
- **Transactional Integrity:** Knowledge documents and their vector chunks are written within the same ACID transaction.
- **Cost & Simplicity:** Open-source and free; eliminates recurring vector SaaS costs.
- **Hybrid Search Capability:** Allows native SQL joins between relational customer filters (e.g., ticket categories) and vector distance calculations (`<->`, `<=>`), plus PostgreSQL full-text search (`tsvector`).
- **HNSW Indexing:** Modern `pgvector` supports fast hierarchical navigable small world (HNSW) indexing for sub-millisecond similarity queries.

### Negative / Mitigations
- Vector operations place memory/CPU demands on the PostgreSQL instance. 
- *Mitigation:* We use compact 384-dimensional embeddings (`all-MiniLM-L6-v2`) and HNSW index tuning (`m`, `ef_construction`), which easily supports tens of thousands of support documents on modest hardware.
