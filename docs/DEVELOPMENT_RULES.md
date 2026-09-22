# SupportFlow AI — Development Rules & Engineering Philosophy

## 1. Engineering Philosophy
SupportFlow AI is built to demonstrate real-world AI software engineering excellence. We adhere to the following core tenets:

1. **Free & Open-Source First:**
   - Prefer `open-source + local/free + simple` over `paid + proprietary + complex`.
   - Never add dependencies or external SaaS without concrete justification.
   - Core embeddings and reranking run locally. Primary LLM uses Groq's high-performance inference through a swappable interface.

2. **The LLM is an Untrusted Worker:**
   - The LLM never touches the raw database.
   - The LLM cannot mutate application state directly; it can only invoke vetted, authorization-checked tools that execute bounded actions.
   - Grounded responses require evidence. When evidence or confidence is lacking, default to human escalation.

3. **Vertical Slice Development:**
   - Deliver end-to-end, working functional slices rather than horizontal scaffolding.
   - Example slice: User Auth → Create Ticket → View Ticket → Basic RAG Context → AI Draft → Human Review.
   - Every slice must be runnable and verifiable.

4. **Code Cleanliness & Explainability:**
   - Strict modularity: separated router, service layer, data-access/repository, and AI integration boundaries.
   - No monolithic files or giant catch-all functions.
   - Strict typing with Python type hints and Pydantic schemas.
   - Clean exception hierarchies and consistent HTTP error formatting.
   - Zero tutorial-grade shortcuts or hardcoded secrets.

---

## 2. Collaborative Pedagogical Workflow
Because this project serves as both a production codebase and a portfolio/learning instrument, every major implementation step must adhere to this review structure:

- **Goal:** Clear definition of what we are building.
- **Design:** Architectural structure, schemas, and control flows.
- **Why:** Trade-offs analyzed, alternatives considered, and rationale for the decision.
- **Files:** Specific files to be created, modified, or migrated.
- **Implementation:** Clean, robust, production-grade code.
- **Run:** Exact local commands to execute the feature.
- **Test:** Automated testing steps (unit, integration, or API) to verify behavior.
- **Engineering Notes:** Deep-dive explanations of concepts relevant to system design, interviews, and operations.

---

## 3. Phased Implementation Roadmap

- **Phase 0: Requirements & Domain Invariants** *(Active)*
- **Phase 1: Architecture & System Design** *(Active)*
- **Phase 2: Database Modeling & Alembic Migrations**
- **Phase 3: FastAPI Core Foundation & App Factory**
- **Phase 4: Authentication, Password Hashing & RBAC**
- **Phase 5: Ticket Lifecycle Management & Operations**
- **Phase 6: Knowledge Base Ingestion Pipeline (PDF/Text/Markdown)**
- **Phase 7: Vector Retrieval with pgvector & Local Embeddings**
- **Phase 8: Hybrid Search (pgvector + Full-Text Search)**
- **Phase 9: Cross-Encoder Reranking Engine**
- **Phase 10: LangGraph Core Orchestration & State Graph**
- **Phase 11: Sandboxed Controlled Agent Tools**
- **Phase 12: Human-In-The-Loop (HITL) Review & Escalation Workflow**
- **Phase 13: Grounding, Faithfulness & AI Quality Evaluation**
- **Phase 14: React + TypeScript + Tailwind Operations Dashboard**
- **Phase 15: Automated Test Hardening (Unit, Integration, E2E)**
- **Phase 16: Multi-Stage Docker Containerization & Docker Compose**
- **Phase 17: Observability, Latency Tracing & Token Analytics**
- **Phase 18: GitHub Actions CI/CD Pipeline**
- **Phase 19: Deployment Configurations & Production Readiness**
- **Phase 20: Comprehensive System Architecture Documentation & ADRs**
- **Phase 21: Interactive Portfolio Demo & Interview Walkthrough**

---

## 4. Git & Version Control Protocol
- **Branch Strategy:**
  - `main`: Stable, release-ready branch.
  - Feature branches: `feature/<feature-name>` (e.g., `feature/auth-rbac`, `feature/ticket-lifecycle`, `feature/rag-pipeline`).
- **Commit Message Convention (Conventional Commits):**
  - `feat: add user registration and JWT authentication`
  - `feat: implement hybrid search retrieval in pgvector`
  - `fix: prevent unauthorized ticket access in customer role`
  - `test: add integration tests for LangGraph refund workflow`
  - `docs: add ADR-001 for PostgreSQL and pgvector selection`
  - *Strictly avoid:* vague commits like `update`, `fixes`, `changes`, `wip`.

---

## 5. Environment & Secrets Discipline
- Secrets must never be committed to Git.
- Maintain `.env.example` with documented configuration options and placeholder values.
- Runtime configurations are validated via Pydantic `BaseSettings` (`backend/app/core/config.py`).
- Key variables:
  - `DATABASE_URL`
  - `REDIS_URL`
  - `GROQ_API_KEY`
  - `JWT_SECRET_KEY`
  - `JWT_ALGORITHM`
  - `EMBEDDING_MODEL_NAME`

---

## 6. Testing Standard
Testing is not an afterthought; it runs continuously across features:
- `tests/unit/`: Pure function testing, schema validation, state graph routing logic, prompt templates.
- `tests/integration/`: Database repositories, pgvector queries, Alembic migrations, Redis caching.
- `tests/api/`: Endpoint authentication, RBAC authorization boundaries, ticket creation and triage.
- `tests/eval/`: AI evaluation datasets, retrieval hit rates, faithfulness, and context relevance benchmarks.
