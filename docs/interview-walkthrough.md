# SupportFlow AI — Engineering Interview Walkthrough

> **Audience:** Technical interviewers, senior engineers, or staff engineers evaluating the depth and production-readiness of this project.
> **Goal:** Explain every significant engineering decision and demonstrate that this is NOT a tutorial clone — it is a production-oriented AI backend built with the same patterns used at scale.

---

## 1. Why This Project Exists

Most AI portfolio projects are thin wrappers: take a user message, call `openai.chat.completions.create()`, return the text. This project asks a harder question:

> *What does a production AI-powered backend actually look like?*

The answer requires:
- A real async web framework with middleware, dependency injection, and structured error handling
- A database layer that can do both semantic and keyword search — and knows when to use each
- A stateful agent graph (not a chain) that can call tools, check permissions, and decide when to escalate
- Security controls that are enforced at the data layer, not just middleware
- Observability that works without a third-party APM vendor
- A CI pipeline that gates on tests, linting, type-checking, and a Docker build

Each of these is explained below.

---

## 2. Technology Stack Decisions

### 2.1 FastAPI + Pydantic v2

**Why FastAPI over Flask/Django?**

FastAPI provides native `async/await` support, automatic OpenAPI generation, and Pydantic v2 integration for request/response validation. The entire API surface is type-safe: if the schema is wrong, the request fails at the boundary — not deep in business logic.

Pydantic v2 is 5–10× faster than v1 for validation-heavy workloads. The RAG pipeline processes multiple search results and reranker scores per request; validation cost matters.

See: [`backend/app/schemas/`](../backend/app/schemas/)

### 2.2 SQLAlchemy 2.x Async + PostgreSQL

**Why not an ORM-free approach?**

SQLAlchemy 2.x with async engine gives us:
- Type-annotated models (Mapped[], mapped_column()) — no magic attribute access
- Explicit transaction boundaries — no implicit commits
- Connection pooling with `pool_size`, `max_overflow`, and `pool_recycle` tuned for production

```python
# backend/app/core/database.py
engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_recycle=settings.DB_POOL_RECYCLE,
)
```

All queries use explicit `select()` expressions, not `session.query()`. This is the SQLAlchemy 2.x idiomatic style.

### 2.3 pgvector for Embeddings

Embeddings are stored as `vector(1536)` columns in PostgreSQL using the pgvector extension. This avoids the operational burden of a separate vector database while staying within the ACID boundary of PostgreSQL.

```sql
-- Simplified schema
CREATE TABLE knowledge_chunks (
    id UUID PRIMARY KEY,
    document_id UUID REFERENCES knowledge_documents(id),
    content TEXT,
    embedding vector(1536),
    ...
);
CREATE INDEX ON knowledge_chunks USING ivfflat (embedding vector_cosine_ops);
```

See: [`docs/architecture/data-models.md`](architecture/data-models.md)

### 2.4 Redis for Rate Limiting

Redis is used exclusively for rate-limit state (sliding-window counters via `slowapi`). It is not used as a general cache. This is intentional — using Redis for general caching adds consistency risk without a proven cache-invalidation strategy.

Rate limiting is enforced per-user (authenticated routes) and per-IP (unauthenticated routes), with different limits for sensitive operations.

See: [`backend/app/core/rate_limit.py`](../backend/app/core/rate_limit.py)

---

## 3. Authentication & Authorization Deep Dive

### 3.1 JWT Flow

```
POST /api/v1/auth/login
  → Validates credentials (bcrypt verify)
  → Issues access token (HS256, 30 min TTL) + refresh token (7 day TTL)
  → Tokens stored in HttpOnly cookies (XSS resistant)

All protected routes:
  → FastAPI dependency `get_current_user` extracts + verifies JWT
  → Loads user record from DB (not just trust the token payload)
  → Attaches user to request state
```

**Why load the user from DB on every request?**

Because JWTs cannot be revoked. By reloading the user record, we can detect disabled/deleted accounts immediately. The performance cost is mitigated by the connection pool.

See: [`backend/app/api/deps.py`](../backend/app/api/deps.py)

### 3.2 RBAC

Three roles: `customer`, `support_agent`, `admin`.

RBAC is enforced at the FastAPI dependency level using composable guards:

```python
# Example: require_support_agent
async def require_support_agent(
    current_user: User = Depends(get_current_user),
) -> User:
    if current_user.role not in (UserRole.SUPPORT_AGENT, UserRole.ADMIN):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return current_user
```

These dependencies are declared in the route signature — they cannot be bypassed by the route handler.

### 3.3 IDOR Prevention

Insecure Direct Object Reference (IDOR) protection is enforced at the **database query level**, not middleware:

```python
# Bad (checks after fetch):
ticket = await db.get(Ticket, ticket_id)
if ticket.customer_id != current_user.id:
    raise 403

# Correct (enforced in query):
stmt = select(Ticket).where(
    Ticket.id == ticket_id,
    Ticket.customer_id == current_user.id,  # ← ownership in WHERE clause
)
```

If the ownership predicate fails, the query returns no rows and the API returns 404 — the same as "not found". This prevents confirming resource existence to unauthorised callers.

See: [`docs/architecture/auth-and-rbac.md`](architecture/auth-and-rbac.md)

---

## 4. RAG Pipeline Architecture

### 4.1 Why LangGraph?

LangGraph is used for the RAG pipeline because the agent needs to make **branching decisions**:

- Should it answer from the knowledge base?
- Should it call a tool (e.g., `check_order_status`)?
- Should it escalate to a human agent?

A simple chain (`retriever → LLM → response`) cannot branch. LangGraph provides a DAG of nodes with conditional edges, persisted state, and explicit tool-call routing.

### 4.2 Graph Topology

```
retrieve_documents
       │
rerank_results
       │
  ┌────┴────┐
  │         │
has_docs?  no_docs
  │         │
select_tool  escalate
  │
  ├── knowledge_base → generate_answer
  ├── check_order_status → tool_result → generate_answer
  ├── check_ticket_status → tool_result → generate_answer
  └── no_tool → generate_answer
```

Each node is a pure Python async function that receives and returns `AgentState` (a TypedDict). State is immutable per-node; LangGraph handles the merge.

See: [`backend/app/services/rag_graph.py`](../backend/app/services/rag_graph.py), [`docs/architecture/rag-pipeline.md`](architecture/rag-pipeline.md)

### 4.3 Hybrid Search

Every RAG query runs two searches in parallel:

```python
# Semantic search (pgvector ANN)
semantic_results = await vector_search(query_embedding, top_k=10)

# Full-text search (PostgreSQL tsvector + tsquery)
fts_results = await fulltext_search(query_text, top_k=10)

# Merge (Reciprocal Rank Fusion)
merged = reciprocal_rank_fusion([semantic_results, fts_results])
```

**Why hybrid?** Semantic search excels at paraphrase and concept matching. FTS excels at exact-term matching (product codes, names, IDs). Neither alone is sufficient.

### 4.4 Cross-Encoder Reranking

The merged ~20 candidates are reranked using a cross-encoder model that scores (query, passage) pairs jointly — producing a much more accurate relevance signal than the ANN distance used for retrieval.

**Why not rerank all chunks?** Cross-encoders are O(n) in inference cost. Retrieval narrows the candidate set from millions to ~20; reranking is then tractable.

### 4.5 ToolRegistry — The Security Boundary

All LLM-triggered tool calls go through the `ToolRegistry`:

```python
# backend/app/services/tool_registry.py
class ToolRegistry:
    _tools: Dict[str, Callable] = {}

    def register(self, name: str, fn: Callable) -> None: ...

    async def execute(
        self,
        tool_name: str,
        args: dict,
        current_user: User,  # ← always injected — LLM cannot override
        db: AsyncSession,
    ) -> ToolResult: ...
```

The `current_user` is **always injected from the authenticated request context** — not from the LLM's response. This means a prompt injection attack cannot make a tool execute on behalf of another user.

See: [`backend/app/services/tool_registry.py`](../backend/app/services/tool_registry.py)

---

## 5. Observability Without a Vendor

### 5.1 Middleware Stack

Request → `SecurityHeadersMiddleware` → `ObservabilityMiddleware` → route handler → response.

`ObservabilityMiddleware` captures:
- Request ID (UUID, propagated in response headers)
- Authenticated user ID (if present)
- Method, path, status code
- Request duration (wall time)
- Error type (if any)

All captured as structured JSON log lines. No APM agent required.

### 5.2 In-Process Analytics

A `MetricsCollector` singleton accumulates per-endpoint statistics in memory:

```python
# Approximate structure
{
  "GET /api/v1/tickets": {
    "count": 142,
    "p50_ms": 18,
    "p95_ms": 87,
    "p99_ms": 201,
    "error_rate": 0.007,
  },
  ...
}
```

These are exposed at `/api/v1/analytics/performance` (admin-only). In production, this data would be scraped by Prometheus; the in-process store means the system works without any external infrastructure.

### 5.3 LLM Pipeline Tracing

The `rag_graph.py` pipeline populates a `trace_buffer` per request:

```python
trace = {
  "retrieval_ms": 45,
  "rerank_ms": 120,
  "tool_name": "check_order_status",
  "tool_ms": 12,
  "total_ms": 201,
  "escalated": False,
  "chunk_count": 8,
}
```

This trace is returned in the API response (`metadata` field) and rendered in the AI Assistant UI — interviewers can see exactly what happened for every query.

See: [`docs/architecture/observability.md`](architecture/observability.md)

---

## 6. Testing Strategy

### 6.1 Test Layers

| Layer | Tool | What It Tests |
|---|---|---|
| Unit | Pytest | Pure business logic: auth, RBAC, search ranking, tool registry |
| Integration | Pytest + HTTPX TestClient | Full request/response cycle with a real async DB (SQLite in-memory for CI) |
| Security | Pytest (dedicated suite) | Rate limiting, IDOR, token forgery, role escalation, SQL injection surface |
| Frontend | Vitest | Component rendering, route guards, API contract types |

### 6.2 Security Test Suite

The security test suite in `tests/security/` is the most important differentiator. It tests:

- **IDOR**: Can user A access user B's ticket? (expected: 404, not 403 — to avoid confirming existence)
- **Role escalation**: Can a `customer` call a `support_agent` endpoint? (expected: 403)
- **Token forgery**: Does a tampered JWT (different signing key) get rejected? (expected: 401)
- **Rate limiting**: Does the rate limiter trigger after N requests? (expected: 429 with `Retry-After` header)
- **Format rejection**: Does the knowledge-base endpoint reject non-allowed MIME types? (expected: 400 with the security message)

These tests run in CI on every push. A failing security test blocks merge.

See: [`tests/security/`](../tests/security/)

### 6.3 CI Pipeline

GitHub Actions runs on every push and pull request:

```
lint (ruff) → type-check (mypy) → backend tests → security tests → frontend build → docker build
```

The pipeline is defined in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml).

---

## 7. Production Deployment Model

### 7.1 Docker Compose for Local / Small VPS

All services are containerised. Production uses the multi-stage Dockerfile:

```dockerfile
# Stage 1: build dependencies
FROM python:3.11-slim AS builder
...
# Stage 2: minimal runtime image (~200 MB)
FROM python:3.11-slim AS runtime
COPY --from=builder /app /app
...
```

The frontend is a static Nginx container serving the Vite build output.

### 7.2 Database Migrations

Alembic manages schema migrations with `autogenerate` disabled — all migrations are explicit. Running migrations:

```bash
docker compose exec backend alembic upgrade head
```

Migrations are run at startup in a pre-flight hook, not inside the application process. This is the correct pattern for containerised apps — it avoids the migration running twice on multi-replica deploys.

### 7.3 Secrets

All secrets are injected via environment variables from `.env` (local) or a secret manager (production). No secrets are committed. `.env.example` documents every variable with descriptions and safe defaults.

See: [`docs/deployment.md`](deployment.md)

---

## 8. What I Would Do Differently at Scale

Honest limitations and the next engineering steps at 10× scale:

| Current | At Scale |
|---|---|
| In-process metrics collector | Replace with Prometheus + Grafana |
| SQLite test DB | Dedicated test PostgreSQL with pgvector |
| JWT with DB reload on every request | Introduce a token introspection cache (Redis, short TTL) |
| Single Alembic migration head | Introduce migration locking (`pg_advisory_lock`) for multi-replica deploys |
| Cross-encoder reranker in-process | Move to a dedicated reranker service (GPU-backed) |
| LangGraph in-process | Consider LangGraph Cloud or a dedicated agent worker queue |
| Docker Compose | Kubernetes with HPA, resource limits, and a proper secrets operator |

---

## 9. Key Files for Reviewers

| File | What to Look At |
|---|---|
| [`backend/app/services/rag_graph.py`](../backend/app/services/rag_graph.py) | LangGraph pipeline: node functions, conditional edges, AgentState |
| [`backend/app/services/tool_registry.py`](../backend/app/services/tool_registry.py) | ToolRegistry: user injection, execution contract |
| [`backend/app/api/deps.py`](../backend/app/api/deps.py) | `get_current_user`, `require_support_agent`, `require_admin` |
| [`backend/app/api/v1/knowledge.py`](../backend/app/api/v1/knowledge.py) | RAG query endpoint: hybrid search, reranking, tool dispatch |
| [`backend/app/middleware.py`](../backend/app/middleware.py) | `ObservabilityMiddleware`, `SecurityHeadersMiddleware` |
| [`backend/app/core/rate_limit.py`](../backend/app/core/rate_limit.py) | Rate limiting with Redis, per-user and per-IP |
| [`tests/security/`](../tests/security/) | Security test suite |
| [`docs/decisions/`](decisions/) | ADR-001 through ADR-011: every major decision explained |
| [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) | Full CI pipeline definition |

---

*For the quick demo guide, see [`docs/demo-walkthrough.md`](demo-walkthrough.md).*
*For architecture diagrams and ADRs, see [`docs/architecture.md`](architecture.md).*
