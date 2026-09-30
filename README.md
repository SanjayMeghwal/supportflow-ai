# SupportFlow AI

**SupportFlow AI** is an enterprise-grade, production-oriented customer support operations platform. It demonstrates how modern backend engineering and state-of-the-art AI architecture converge to deliver grounded, secure, and auditable support automations.

---

## Key Capabilities

- **Multi-Stage Knowledge Retrieval:**
  - Dense vector similarity search via PostgreSQL `pgvector`
  - Lexical keyword search via PostgreSQL Full-Text Search (`tsvector`)
  - Reciprocal Rank Fusion (RRF) for hybrid score unification
  - Cross-encoder re-ranking (`ms-marco-MiniLM-L-6-v2`) for top-$K$ precision
- **LangGraph RAG Orchestration:**
  - Explicit state transitions, cycle limits, and context assembly
  - Bounded AI tool calling (`get_order_status`, `get_payment_status`) with strict RBAC/IDOR authorization
- **Human-In-The-Loop (HITL) Safety:**
  - Deterministic escalation triggers (low confidence, legal keywords, tool denials, missing context)
  - Pre-delivery review queues preventing ungoverned LLM responses
- **Grounding, Faithfulness & AI Quality Evaluation:**
  - Automated benchmark dataset (20 curated operational QA samples + negative cases)
  - Mathematical retrieval metrics: **Precision@K**, **Recall@K**, **MRR**, **Hit Rate@K**
  - RAG quality metrics: **Context Relevance**, **Answer Relevance**, **Faithfulness**, and **Hallucination Detection**
  - Completely offline-runnable and reproducible without paid API keys

---

## AI Evaluation Subsystem (Phase 13)

SupportFlow AI includes a dedicated evaluation layer to benchmark retrieval and generation quality and prevent regressions when updating chunking, embeddings, or prompts.

### Running the Evaluation Suite

Execute the offline benchmark runner from the command line:

```bash
# Run the full benchmark evaluation
python scripts/run_evaluation.py

# Filter by a specific category (e.g., refund, authentication, orders)
python scripts/run_evaluation.py --category refund

# Customize top-K cutoff
python scripts/run_evaluation.py --top-k 5

# Output in Markdown format
python scripts/run_evaluation.py --format markdown
```

### Benchmark Metrics

| Metric | Category | Description |
|---|---|---|
| **Precision@K** | Retrieval | Ratio of retrieved top-$K$ chunks that are relevant |
| **Recall@K** | Retrieval | Ratio of all relevant ground-truth chunks captured in top-$K$ |
| **MRR** | Retrieval | Mean Reciprocal Rank of the first relevant chunk ($1/\text{rank}$) |
| **Hit Rate@K** | Retrieval | Binary indicator if at least one relevant passage reached top-$K$ |
| **Context Relevance** | RAG Quality | Fraction of retrieved context containing query-relevant facts |
| **Answer Relevance** | RAG Quality | Query intent coverage and token F1 similarity against ground truth |
| **Faithfulness** | RAG Quality | Proportion of factual claims in the answer grounded in context |
| **Hallucination Rate** | RAG Quality | Percentage of generated answers containing unsupported assertions |

Evaluation reports are automatically generated and saved to:
`evaluation/results/latest_report.json`

---

## Running Tests

SupportFlow AI is backed by an automated test suite across unit, integration, and API levels:

```bash
# Run all tests
pytest

# Run Phase 13 evaluation unit tests
pytest tests/unit/test_evaluation_dataset.py tests/unit/test_evaluation_metrics.py tests/unit/test_faithfulness.py tests/unit/test_evaluation_service.py -v
```

---

## Docker Containerization & Local Stack (Phase 16)

SupportFlow AI is fully containerized using multi-stage Docker builds and Docker Compose, providing a reproducible, production-like development environment.

### Services Architecture

```
Browser
  │
  ├──► Frontend (Nginx 1.27 Alpine, port 3000)
  │      ├── Serves React SPA (built with Vite + Node 20)
  │      └── Reverse proxies /api/ ──► Backend (FastAPI, port 8000)
  │
  ├──► Backend (Python 3.12 slim, port 8000)
  │      ├── Non-root runtime (`appuser`, UID 10001)
  │      ├── Connects to PostgreSQL (`db:5432`)
  │      ├── Connects to Redis (`redis:6379`)
  │      └── Auto-runs Alembic migrations on startup (`entrypoint.sh`)
  │
  ├──► PostgreSQL 16 + pgvector (port 5434 -> 5432)
  │      └── Persistent named volume: `supportflow_pgdata`
  │
  └──► Redis 7 Alpine (port 6379)
         └── Persistent named volume: `supportflow_redisdata`
```

### Quickstart Commands

```bash
# Build all container images
docker compose build

# Start the full stack in background
docker compose up -d

# Verify service status and health checks
docker compose ps

# View backend logs (including startup migrations)
docker compose logs -f backend

# View frontend web server logs
docker compose logs -f frontend

# Stop the stack gracefully (preserves database data)
docker compose down

# Controlled rebuild and restart
docker compose up -d --build
```

### Port Mapping Summary

| Service | Internal Port | Host Port | Purpose |
|---|---|---|---|
| **frontend** | 80 | `3000` | React Operations Dashboard & Nginx API proxy |
| **backend** | 8000 | `8000` | FastAPI application, Swagger docs (`/docs`), Healthcheck (`/health`) |
| **db** | 5432 | `5434` | PostgreSQL 16 with pgvector extension |
| **redis** | 6379 | `6379` | Redis cache and session state |

### Health Checks

- **PostgreSQL:** Native `pg_isready -U postgres -d supportflow_db`
- **Redis:** Native `redis-cli ping`
- **Backend:** HTTP `GET /health` validating DB connectivity via SQLAlchemy async session
- **Frontend:** HTTP `GET /healthz` verifying Nginx static server readiness

---

## Architectural Decisions

Detailed Architecture Decision Records (ADRs) are documented in [`docs/decisions/`](docs/decisions/):
- **ADR-005:** Local Embeddings and Vector Retrieval
- **ADR-006:** Hybrid Search with Reciprocal Rank Fusion (RRF)
- **ADR-007:** Cross-Encoder Reranking Engine
- **ADR-008:** LangGraph RAG Orchestration
- **ADR-009:** Bounded AI Tools
- **ADR-010:** Human-In-The-Loop Review and Escalation
- **ADR-011:** AI Evaluation, Grounding, and Faithfulness Verification

