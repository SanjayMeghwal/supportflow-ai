# SupportFlow AI — Architecture Documentation

> **Version:** 0.1.0  
> **Branch:** `feature/architecture-documentation`  
> **Status:** Production-ready (Phases 0–20 complete)

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [High-Level Component Architecture](#2-high-level-component-architecture)
3. [Request Flow](#3-request-flow)
4. [Backend Application Layout](#4-backend-application-layout)
5. [Authentication & Authorization](#5-authentication--authorization)
6. [RAG Pipeline Architecture](#6-rag-pipeline-architecture)
7. [Knowledge Ingestion Pipeline](#7-knowledge-ingestion-pipeline)
8. [Data Model Summary](#8-data-model-summary)
9. [Observability & Middleware Stack](#9-observability--middleware-stack)
10. [Security Hardening](#10-security-hardening)
11. [Infrastructure & Docker Services](#11-infrastructure--docker-services)
12. [Configuration Reference](#12-configuration-reference)
13. [API Surface](#13-api-surface)
14. [Testing Architecture](#14-testing-architecture)
15. [Architecture Decision Records](#15-architecture-decision-records)

---

## 1. System Overview

SupportFlow AI is a production-oriented, AI-augmented customer-support and operations platform. It combines a FastAPI async backend, a RAG (Retrieval-Augmented Generation) pipeline orchestrated with LangGraph, hybrid semantic + full-text search over a pgvector-enabled PostgreSQL database, and a Vue.js frontend served by Nginx — all packaged as a multi-container Docker application.

**Core capabilities:**

| Capability | Implementation |
|---|---|
| Ticket management | CRUD REST API; role-scoped access |
| AI answer generation | LangGraph RAG pipeline + Groq (Llama 3.3 70B) |
| Semantic search | pgvector cosine similarity; BAAI/bge-small-en-v1.5 embeddings |
| Full-text search | PostgreSQL `tsvector` / `to_tsquery` |
| Hybrid search | Reciprocal Rank Fusion (RRF) over both retrieval systems |
| Cross-encoder reranking | `cross-encoder/ms-marco-MiniLM-L-6-v2` |
| Bounded tool execution | ToolRegistry pattern; tools: `get_order_status`, `get_payment_status` |
| Human-in-the-loop (HITL) | Deterministic escalation detection + HumanReview record |
| RBAC | JWT + DB-authoritative role enforcement |
| Observability | Structured JSON logs; request correlation IDs; latency metrics |

---

## 2. High-Level Component Architecture

```
 ┌─────────────────────────────────────────────────────────────────────┐
 │                         Docker Network: supportflow-network          │
 │                                                                       │
 │  ┌───────────────┐     ┌──────────────────────────────────────────┐  │
 │  │   Frontend     │     │              Backend (FastAPI)            │  │
 │  │  (Nginx/SPA)  │────▶│                                          │  │
 │  │   Port: 3000  │     │  ObservabilityMiddleware                 │  │
 │  └───────────────┘     │  SecurityHeadersMiddleware               │  │
 │                         │  CORSMiddleware                          │  │
 │                         │  ─────────────────────────────────────  │  │
 │                         │  API v1 Router (/api/v1)                 │  │
 │                         │    /auth  /tickets  /knowledge           │  │
 │                         │    /reviews  /analytics                  │  │
 │                         │  ─────────────────────────────────────  │  │
 │                         │  LangGraph RAG Pipeline                  │  │
 │                         │    retrieve → context_assembly →         │  │
 │                         │    generate_answer_or_tool_call →        │  │
 │                         │    [execute_tool → synthesize_with_tool] │  │
 │                         │    → validate_format → check_escalation  │  │
 │                         │  Port: 8000                              │  │
 │                         └──────────────┬───────────────────────────┘  │
 │                                         │                              │
 │              ┌──────────────────────────┼──────────────────┐          │
 │              │                          │                   │          │
 │   ┌──────────▼──────────┐   ┌───────────▼─────────┐        │          │
 │   │  PostgreSQL 16      │   │   Redis 7 Alpine     │        │          │
 │   │  + pgvector         │   │   Rate limiting      │        │          │
 │   │  Port: 5434 (host)  │   │   Port: 6379         │        │          │
 │   └─────────────────────┘   └─────────────────────┘        │          │
 └─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Request Flow

Every inbound HTTP request traverses the following layers in order:

```
Client Request
  │
  ▼
[1] ObservabilityMiddleware
    ├─ Resolve or generate X-Request-ID (UUID)
    ├─ Record start time (perf_counter)
    └─ On response: inject X-Request-ID, X-Response-Time-Ms, rate-limit headers; record metrics

  │
  ▼
[2] SecurityHeadersMiddleware
    ├─ Content-Length check → 413 if body > MAX_REQUEST_BODY_SIZE (10 MB)
    └─ Inject security headers: X-Content-Type-Options, X-Frame-Options,
       Referrer-Policy, Permissions-Policy, Content-Security-Policy

  │
  ▼
[3] CORSMiddleware
    └─ Validate Origin against CORS_ORIGINS allowlist

  │
  ▼
[4] FastAPI Router (/api/v1/...)
    ├─ RateLimitDependency (Redis-backed sliding window; per-route limits)
    ├─ get_current_user (JWT decode → DB user lookup → is_active check)
    ├─ require_roles (DB-authoritative role enforcement)
    └─ Route handler

  │
  ▼
[5] Service / RAG layer
    ├─ KnowledgeService / TicketService / etc.
    └─ run_rag_pipeline (LangGraph)

  │
  ▼
[6] Database (PostgreSQL + pgvector) / Redis
```

**Middleware registration order in `main.py`:**

```python
app.add_middleware(ObservabilityMiddleware)    # outermost
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(CORSMiddleware, ...)        # innermost
```

> Starlette processes middleware in reverse registration order: `CORSMiddleware` executes first on the way in; `ObservabilityMiddleware` executes first on the way out (response path), which is why it stamps timing headers.

---

## 4. Backend Application Layout

```
backend/
└── app/
    ├── main.py              # FastAPI app factory, middleware, lifespan, health probes
    ├── api/
    │   ├── deps.py          # get_current_user, require_roles, resource ownership helpers
    │   └── v1/
    │       ├── api.py       # Central router aggregating all sub-routers
    │       ├── auth.py      # /auth/register, /auth/login, /auth/refresh, /auth/me
    │       ├── tickets.py   # Ticket CRUD + AI assistant endpoint
    │       ├── knowledge.py # Document upload, list, delete, search, AI query
    │       ├── reviews.py   # HumanReview queue and review actions
    │       └── analytics.py # LLM analytics + observability metrics
    ├── core/
    │   ├── config.py        # Pydantic Settings (env-file + env vars)
    │   ├── database.py      # SQLAlchemy 2.x async engine + get_db dependency
    │   ├── security.py      # bcrypt hash/verify, JWT create/decode (python-jose)
    │   ├── middleware.py    # ObservabilityMiddleware, SecurityHeadersMiddleware
    │   ├── rate_limit.py    # Redis-backed sliding-window rate limiter
    │   ├── logging.py       # Structured JSON logging (structlog compatible)
    │   ├── metrics.py       # In-process request metrics collector
    │   ├── tracing.py       # PipelineTrace, trace_span, trace_buffer
    │   └── request_context.py  # ContextVar-based X-Request-ID propagation
    ├── models/
    │   ├── base.py          # DeclarativeBase, UUIDPrimaryKeyMixin, TimestampMixin
    │   ├── user.py          # User, Customer, UserRole (ADMIN/SUPPORT_AGENT/CUSTOMER)
    │   ├── ticket.py        # Ticket, TicketMessage, enums
    │   ├── order.py         # Order, Payment, enums
    │   ├── knowledge.py     # KnowledgeDocument, DocumentChunk (pgvector column)
    │   ├── ai.py            # AIRun, AIToolInvocation, HumanReview, AuditLog
    │   └── analytics.py     # LLMAnalyticsRecord
    ├── schemas/             # Pydantic v2 request/response schemas
    └── services/
        ├── rag_graph.py     # LangGraph RAG + tool + HITL pipeline
        ├── knowledge.py     # Document ingestion, hybrid search, reranked retrieval
        ├── llm.py           # BaseLLMService; GroqLLMService adapter
        ├── llm_analytics.py # Token usage and latency recording
        ├── embedding.py     # EmbeddingService (sentence-transformers)
        ├── chunking.py      # RecursiveTextChunker
        ├── extractors.py    # PDF/MD/TXT/JSON text extraction
        ├── ranking.py       # Reciprocal Rank Fusion (RRF)
        ├── reranker.py      # Cross-encoder reranker (sentence-transformers)
        ├── tool_registry.py # Bounded tool dispatcher (dispatch_tool, MAX_TOOL_CALLS)
        ├── tools.py         # get_order_status, get_payment_status tool implementations
        └── review_service.py # check_escalation_triggers, review queue management
```

---

## 5. Authentication & Authorization

### Authentication

- **Token type:** HS256 JWT (via `python-jose`)
- **Token claims:** `sub` (user UUID), `type: "access"`, `iat`, `exp`
- **Password hashing:** bcrypt (direct, via `bcrypt` library)
- **Access token lifetime:** 60 minutes (configurable)
- **Refresh token lifetime:** 7 days (configurable)

**Security invariants (enforced in `deps.py`):**

1. JWT must be a valid, non-expired `access` type token.
2. The `user_id` from the `sub` claim must exist in the database.
3. The user must have `is_active == True`.
4. **Role is always read from the database — never from JWT claims.**

### Role-Based Access Control (RBAC)

Three roles are defined in `UserRole` enum:

| Role | Scope |
|---|---|
| `ADMIN` | Full system access; cross-customer oversight |
| `SUPPORT_AGENT` | Ticket management; cross-customer read access |
| `CUSTOMER` | Own tickets, own orders, AI query only |

**Convenience dependency factories:**

```python
require_admin          = require_roles(UserRole.ADMIN)
require_support_agent  = require_roles(UserRole.SUPPORT_AGENT, UserRole.ADMIN)
require_customer       = require_roles(UserRole.CUSTOMER)
```

### Resource Ownership (IDOR Prevention)

`verify_resource_ownership()` in `deps.py` enforces:
- ADMIN and SUPPORT_AGENT roles may access any customer's resources.
- CUSTOMER role may only access resources where `resource.customer_id == authenticated_customer.id`.
- UUID in a URL path **is an identifier, never an authorization token**.

---

## 6. RAG Pipeline Architecture

The AI answer pipeline is implemented as a compiled **LangGraph `StateGraph`** in `services/rag_graph.py`.

### State Schema (`AgentState`)

```python
class AgentState(TypedDict, total=False):
    query: str
    top_k: int
    current_user: Optional[User]      # from API layer; never from LLM output
    retrieved_docs: list[dict]
    context_text: str
    sources: list[dict]
    context_available: bool
    tool_call_request: Optional[ToolCallRequest]
    tool_result: Optional[ToolResult]
    tool_calls_count: int             # guard against loops
    answer: str
    is_valid: bool
    error: Optional[str]
    escalation_triggered: bool
    escalation_reason: Optional[str]
    escalation_status: Optional[str]
```

### Graph Topology

```
START
  │
  ▼
retrieve ─────────────────────── (hybrid search → RRF fusion → cross-encoder rerank)
  │
  ▼
context_assembly ──────────────── (format context blocks + build citations)
  │
  ├─ context_available? NO ──────▶ insufficient_context
  │                                    │
  └─ context_available? YES ──────▶ generate_answer_or_tool_call
                                        │
                              ┌─────────┴──────────┐
                              │                     │
                    tool requested?          no tool requested
                        YES                        │
                         │                         ▼
                    execute_tool           validate_format
                         │                         │
                         ▼                         │
               synthesize_with_tool ───────────────┘
                                                   │
                                                   ▼
                                          check_escalation
                                                   │
                                                  END
```

### Graph Nodes

| Node | Responsibility |
|---|---|
| `retrieve` | Calls `KnowledgeService.search_reranked()`; returns ranked docs |
| `context_assembly` | Formats context blocks; extracts citation metadata |
| `insufficient_context` | Returns safe refusal message; sets `context_available=False` |
| `generate_answer_or_tool_call` | Calls Groq LLM; detects tool-call JSON in output |
| `execute_tool` | Dispatches to `ToolRegistry`; enforces `MAX_TOOL_CALLS` cap |
| `synthesize_with_tool` | Re-synthesizes answer using authoritative tool result |
| `validate_format` | Deterministic cleanup; empty-answer guard |
| `check_escalation` | Deterministic HITL trigger evaluation |

### Security Invariants in the RAG Pipeline

- `current_user` is injected at graph build time from the API layer — the LLM **cannot** supply or override it.
- Tool calls are bounded by `MAX_TOOL_CALLS` (configured in `tool_registry.py`).
- Only registered tool names pass the `ToolRegistry` check; Pydantic validates all arguments before execution.
- Escalation decisions are **deterministic and application-enforced** — the LLM has no access to the `check_escalation` node and cannot approve, edit, or reject its own output.
- User query length is capped at `MAX_AI_INPUT_CHARS` (4000 chars) before graph invocation.
- LangGraph recursion is capped at `MAX_GRAPH_STEPS` (15).

### LLM Provider

| Setting | Value |
|---|---|
| Provider | Groq API |
| Model | `llama-3.3-70b-versatile` |
| Temperature | `0.0` (deterministic) |
| Interface | `BaseLLMService` → `GroqLLMService` |

---

## 7. Knowledge Ingestion Pipeline

Document ingestion is handled by `KnowledgeService.ingest_document()` in `services/knowledge.py`.

```
Upload (PDF / MD / TXT / JSON)
  │
  ▼
SHA-256 checksum → DuplicateDocumentError if already exists
  │
  ▼
Text extraction (extractors.py)
  │
  ▼
RecursiveTextChunker (chunk_size=500, chunk_overlap=50)
  │
  ▼
EmbeddingService (BAAI/bge-small-en-v1.5, dim=384)
  │
  ▼
Persist KnowledgeDocument + DocumentChunk rows
  └── DocumentChunk.embedding: pgvector column (vector(384))
```

### Retrieval at Query Time

`KnowledgeService.search_reranked()` runs:

1. **Vector search** — pgvector cosine similarity (`<=>` operator) on `DocumentChunk.embedding`
2. **Full-text search** — PostgreSQL `tsvector` / `to_tsquery` on `DocumentChunk.content`
3. **RRF fusion** — `reciprocal_rank_fusion()` merges both result sets; candidate pool = `top_k × 4` (max 100 per system)
4. **Cross-encoder reranking** — `cross-encoder/ms-marco-MiniLM-L-6-v2` scores merged candidates; candidate pool = `top_k × 4` (max 50)
5. Returns top-`k` reranked chunks with scores

---

## 8. Data Model Summary

All models inherit `UUIDPrimaryKeyMixin` (UUID v4 PK) and `TimestampMixin` (`created_at`, `updated_at`).

| Model | Table | Key Fields |
|---|---|---|
| `User` | `users` | `email`, `hashed_password`, `role` (UserRole), `is_active` |
| `Customer` | `customers` | `user_id` (FK), `tier` (CustomerTier), `company_name` |
| `Ticket` | `tickets` | `customer_id`, `status`, `priority`, `category`, `assigned_agent_id` |
| `TicketMessage` | `ticket_messages` | `ticket_id`, `content`, `sender_type` (CUSTOMER/AGENT/AI) |
| `Order` | `orders` | `customer_id`, `status` (OrderStatus), `total_amount` |
| `Payment` | `payments` | `order_id`, `status` (PaymentStatus), `method` (PaymentMethod) |
| `KnowledgeDocument` | `knowledge_documents` | `title`, `source_type`, `sha256_checksum`, `chunk_count` |
| `DocumentChunk` | `document_chunks` | `document_id`, `content`, `embedding` (vector(384)), `tsvector_content` |
| `AIRun` | `ai_runs` | `ticket_id`, `query`, `answer`, `status` (AIRunStatus), `escalation_triggered` |
| `AIToolInvocation` | `ai_tool_invocations` | `run_id`, `tool_name`, `arguments`, `result`, `success` |
| `HumanReview` | `human_reviews` | `run_id`, `status` (ReviewStatus), `escalation_reason`, `reviewer_id` |
| `AuditLog` | `audit_logs` | `actor_id`, `action`, `resource_type`, `resource_id`, `details` |
| `LLMAnalyticsRecord` | `llm_analytics` | `operation`, `model`, `prompt_tokens`, `completion_tokens`, `latency_ms` |

---

## 9. Observability & Middleware Stack

### ObservabilityMiddleware

- **Request correlation:** Reads `X-Request-ID` header; generates a UUID if absent. Stored via `contextvars` (`request_context.py`) for access anywhere in the call stack.
- **Latency measurement:** `time.perf_counter()` around the full request cycle.
- **Response headers injected:** `X-Request-ID`, `X-Response-Time-Ms`, rate-limit headers (`X-RateLimit-*`).
- **Metrics:** `metrics_collector.record_request()` called on every request.
- **Structured logs:** One `INFO` log per request (skipped for `/health`, `/healthz`) including `request_id`, `method`, `route`, `status_code`, `duration_ms`.

### SecurityHeadersMiddleware

- **Request size enforcement:** Rejects `Content-Length > MAX_REQUEST_BODY_SIZE` (10 MB) with HTTP 413.
- **Security headers set on every response:**
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `Referrer-Policy: strict-origin-when-cross-origin`
  - `Permissions-Policy: geolocation=(), camera=(), microphone=(), payment=()`
  - `Content-Security-Policy` (configurable; restrictive default)
  - `Strict-Transport-Security` (disabled by default; enabled via `HSTS_ENABLED=True`)

### Structured Logging

All logs are emitted as structured JSON with fields: `event`, `request_id`, `method`, `route`, `status_code`, `duration_ms`. Security events use `log_security_event()` with an additional `user_id` field.

### Tracing

`core/tracing.py` provides `PipelineTrace` and `trace_span` / `async_trace_span` context managers. Each RAG pipeline invocation produces a trace with per-node spans (retrieval, llm_generation, tool_execution, check_escalation, etc.) recorded to an in-process `trace_buffer`. Traces are returned in the pipeline result dict.

### Rate Limiting

Redis-backed sliding-window rate limiter (`core/rate_limit.py`):

| Route group | Limit (per minute) |
|---|---|
| Default | 100 |
| Auth endpoints | 10 |
| AI / RAG endpoints | 20 |
| Upload endpoints | 10 |

Rate limit headers (`X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`) are propagated by `ObservabilityMiddleware` from `request.state.rate_limit_headers`.

### Health Probes

| Endpoint | Purpose | Healthy condition |
|---|---|---|
| `GET /health/live` | Liveness | Process is responsive → 200 |
| `GET /health/ready` | Readiness | PostgreSQL `SELECT 1` + Redis `PING` both succeed → 200; 503 otherwise |
| `GET /health` | General | PostgreSQL `SELECT 1` succeeds → 200 |

---

## 10. Security Hardening

| Control | Implementation |
|---|---|
| Password hashing | `bcrypt` direct (adaptive cost; salt per hash) |
| JWT | HS256; minimal claims; role excluded from token |
| Role enforcement | DB-authoritative; never from JWT claims |
| IDOR prevention | `verify_resource_ownership()` in every resource endpoint |
| Rate limiting | Redis sliding window; per-route limits |
| Request size | 10 MB hard limit via `SecurityHeadersMiddleware` |
| File upload | Extension + MIME type allowlist (PDF, MD, TXT, JSON) |
| AI input | `MAX_AI_INPUT_CHARS = 4000` query length cap |
| Tool execution | `ToolRegistry` allowlist; `MAX_TOOL_CALLS` cap per run |
| LLM injection | Tool calls validated by Pydantic before dispatch; LLM cannot bypass registry |
| Security headers | CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy |
| CORS | Explicit origin allowlist |
| Error handling | Global exception handler returns generic 500 + `request_id`; no stack trace leakage |
| Security logging | `log_security_event()` for auth failures, IDOR attempts, role denials |

---

## 11. Infrastructure & Docker Services

### Development Stack (`docker-compose.yml`)

| Service | Image | Host Port | Internal Port |
|---|---|---|---|
| `db` | `pgvector/pgvector:pg16` | 5434 | 5432 |
| `redis` | `redis:7-alpine` | 6379 | 6379 |
| `backend` | `./backend/Dockerfile` | 8000 | 8000 |
| `frontend` | `./frontend/Dockerfile` | 3000 | 80 |

All services share the `supportflow-network` bridge network. Internal services communicate by container name (e.g., `db`, `redis`). Host-exposed ports allow local development access.

Startup ordering is enforced via `depends_on` + `condition: service_healthy` health checks.

### Production Stack (`docker-compose.prod.yml`)

The production compose file hardens the development stack:
- `db` and `redis` ports are **not exposed** on the host (internal only).
- Backend runs behind Nginx as reverse proxy.
- Resource limits applied.

### Database

- **Engine:** PostgreSQL 16 with `pgvector` extension
- **Connection:** SQLAlchemy 2.x async (`asyncpg` driver)
- **Pool:** `pool_size=10`, `max_overflow=20`, `pool_timeout=30s`, `pool_recycle=1800s`
- **Migrations:** Alembic (migration scripts in `alembic/versions/`)
- **Isolation:** Test suite uses a separate `supportflow_test_db` database

### Frontend

- **Framework:** Vite/Vue.js SPA
- **Container:** Nginx Alpine (serves static assets; Nginx config hardened with body limits, buffer tuning, caching headers)

---

## 12. Configuration Reference

All configuration is managed by `core/config.py` (`pydantic-settings`). Values are loaded from `.env` file or environment variables.

| Variable | Default | Description |
|---|---|---|
| `APP_ENV` | `development` | Runtime environment |
| `DEBUG` | `True` | Enables verbose logging |
| `DATABASE_URL` | `postgresql+asyncpg://...@localhost:5434/supportflow_db` | Async DB connection string |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `JWT_SECRET_KEY` | (must override in production) | HMAC signing secret |
| `JWT_ALGORITHM` | `HS256` | JWT algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | Access token TTL |
| `GROQ_API_KEY` | `""` | Groq API key (required for AI) |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Groq model ID |
| `EMBEDDING_MODEL_NAME` | `BAAI/bge-small-en-v1.5` | Sentence-transformers embedding model |
| `EMBEDDING_DIMENSION` | `384` | Vector dimension |
| `RERANKER_MODEL_NAME` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Cross-encoder reranker |
| `RAG_TOP_K` | `5` | Retrieved passages per query |
| `CONFIDENCE_THRESHOLD` | `0.75` | Escalation confidence floor |
| `MAX_AI_INPUT_CHARS` | `4000` | Query length cap |
| `MAX_GRAPH_STEPS` | `15` | LangGraph recursion limit |
| `MAX_REQUEST_BODY_SIZE` | `10485760` (10 MB) | HTTP request size limit |
| `RATE_LIMIT_DEFAULT` | `100` | Default rate limit (req/min) |
| `RATE_LIMIT_AUTH` | `10` | Auth endpoint rate limit |
| `RATE_LIMIT_AI` | `20` | AI endpoint rate limit |
| `ENABLE_DOCS` | `True` | Enable `/docs` and `/redoc` |
| `ENABLE_SECURITY_HEADERS` | `True` | Enable security header injection |
| `HSTS_ENABLED` | `False` | Enable HSTS header |

---

## 13. API Surface

Base path: `/api/v1`

| Router | Prefix | Key Endpoints |
|---|---|---|
| Auth | `/auth` | `POST /register`, `POST /login`, `POST /refresh`, `GET /me` |
| Tickets | `/tickets` | CRUD; `POST /{id}/ask` (AI assistant) |
| Knowledge | `/knowledge` | `POST /upload`, `GET /`, `DELETE /{id}`, `POST /search`, `POST /ask` |
| Reviews | `/reviews` | `GET /queue`, `POST /{id}/approve`, `POST /{id}/reject` |
| Analytics | `/analytics` | LLM token usage, latency histograms, observability metrics |

Full OpenAPI spec is available at `/api/v1/openapi.json` when `ENABLE_DOCS=True`.

---

## 14. Testing Architecture

```
tests/
├── conftest.py           # Async test DB setup; isolated supportflow_test_db
├── unit/                 # Pure unit tests (no DB/Redis)
├── integration/          # Tests using real async DB via httpx.AsyncClient
└── security/
    ├── test_auth_tokens.py     # JWT validation edge cases
    ├── test_rbac_idor.py       # Role isolation, cross-tenant access attempts
    ├── test_rate_limiting.py   # Rate limit enforcement
    ├── test_input_validation.py # Payload size, upload type rejection
    └── test_error_handling.py  # 500 error safe response; no stack trace leakage
```

**Key testing conventions:**

- Tests use a dedicated `supportflow_test_db`; migrations are applied fresh per test session.
- ASGI error-handling tests use `raise_app_exceptions=False` on the `AsyncClient` to test HTTP error responses without raising exceptions in the test process.
- CI pipeline runs: backend unit/integration tests, security tests, Docker build validation, and Alembic migration check.

---

## 15. Architecture Decision Records

All ADRs are in [`docs/decisions/`](./decisions/).

| ADR | Decision |
|---|---|
| [ADR-001](./decisions/ADR-001-postgresql-pgvector.md) | PostgreSQL 16 + pgvector for primary storage and vector search |
| [ADR-002](./decisions/ADR-002-async-sqlalchemy-2.md) | SQLAlchemy 2.x async + asyncpg for non-blocking I/O |
| [ADR-003](./decisions/ADR-003-uuid-primary-keys.md) | UUID v4 primary keys on all domain models |
| [ADR-004](./decisions/ADR-004-docker-local-infrastructure.md) | Docker Compose for local and production infrastructure |
| [ADR-005](./decisions/ADR-005-local-embeddings-and-vector-retrieval.md) | Local sentence-transformers embeddings (BAAI/bge-small-en-v1.5) |
| [ADR-006](./decisions/ADR-006-hybrid-search-with-rrf.md) | Hybrid search (vector + full-text) fused with Reciprocal Rank Fusion |
| [ADR-007](./decisions/ADR-007-cross-encoder-reranking.md) | Cross-encoder reranking (ms-marco-MiniLM-L-6-v2) after RRF fusion |
| [ADR-008](./decisions/ADR-008-langgraph-rag-orchestration.md) | LangGraph `StateGraph` for RAG pipeline orchestration |
| [ADR-009](./decisions/ADR-009-bounded-ai-tools.md) | Bounded tool execution via ToolRegistry pattern |
| [ADR-010](./decisions/ADR-010-human-in-the-loop-review.md) | Deterministic HITL escalation detection |
| [ADR-011](./decisions/ADR-011-ai-evaluation-and-groundedness.md) | AI evaluation and groundedness scoring |
