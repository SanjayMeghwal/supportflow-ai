# SupportFlow AI — Project Context

## 1. Executive Summary & Vision
**SupportFlow AI** is an enterprise-grade, production-oriented AI customer-support and operations platform. It demonstrates how modern software and AI engineering converge to build an end-to-end operational product rather than a prototype chatbot or toy tutorial.

The system addresses the core operational problems of high-volume customer support:
- High response latency and repetitive human workloads.
- Inconsistent and hallucinated answers.
- Disconnected silos between customer records, policy documentation, and resolution workflows.
- Poor traceability, missing audit trails, and unmeasured AI accuracy.

SupportFlow AI is engineered around the principle: **Never blindly trust the LLM.** Business logic, authorization, and ticket states reside strictly within the deterministic backend. When knowledge retrieval or AI confidence is insufficient, the system proactively routes to Human-In-The-Loop (HITL) review rather than fabricating an answer.

---

## 2. Core Business Problem & Domain Example
Support organizations manage incoming inquiries across chat, email, and portals. Agents frequently scramble across disparate CRM tools, databases, and policy documentation to answer standard queries (e.g., cancellations, refunds, billing discrepancies).

### Concrete Scenario:
> **Customer Inquiry:** *"I was charged ₹2,000 but my order was cancelled. When will I get my refund?"*
>
> **SupportFlow AI Lifecycle:**
> 1. Ingest customer ticket & assign unique tracking ID.
> 2. Classify intent: `Billing / Refund`.
> 3. Extract entities: Order identifiers, transaction references, amounts.
> 4. Evaluate knowledge retrieval requirements (Policy lookup needed: Refund timelines).
> 5. Query hybrid vector + keyword knowledge index (retrieves authoritative cancellation/refund policy).
> 6. Invoke bounded backend tools to verify order cancellation status and payment gateway records.
> 7. Synthesize grounded answer strictly citing policy (e.g., "5–7 business days via original payment method").
> 8. Compute response confidence & grounding evidence score.
> 9. Decision gate:
>    - **Confidence $\ge$ Threshold & Sufficient Evidence:** Response proposed for automated delivery or agent one-click dispatch based on tenant configuration.
>    - **Confidence < Threshold or Missing Data:** Ticket proactively escalated to `SUPPORT_AGENT` review queue with retrieved context, tool outputs, and reasoning draft pre-populated.
> 10. Persist complete audit trace (prompt tokens, response tokens, tool inputs/outputs, model version, latencies).

---

## 3. Technology Stack & Principles

### Backend & Storage
- **Runtime & Framework:** Python 3.12, FastAPI (async/await, OpenAPI spec, dependency injection).
- **Validation & Serialization:** Pydantic v2.
- **ORM & Migrations:** SQLAlchemy 2.0 (declarative async models) + Alembic.
- **Relational & Vector Database:** PostgreSQL 16+ with `pgvector` extension for unified ACID relational data and dense vector embeddings.
- **Caching & Ephemeral State:** Redis (rate limiting, session caching, task coordination).

### AI & Retrieval (Free / Open-Source First)
- **Primary LLM:** Groq API (high-throughput, low-latency inference).
- **LLM Abstraction:** Decoupled client interface isolating Groq from application services to allow pluggable local LLMs (e.g., Ollama / vLLM) or alternative providers.
- **Embeddings:** Local open-source Sentence-Transformers (e.g., `BAAI/bge-small-en-v1.5` or `all-MiniLM-L6-v2`) running without paid API costs.
- **Reranker:** Local Cross-Encoder (e.g., `cross-encoder/ms-marco-MiniLM-L-6-v2`) for multi-stage precision retrieval.
- **Agent Orchestration:** LangGraph (explicit state graph: state schemas, node functions, conditional edges, cycle limits, and checkpointing).
- **Tool Calling:** Hardened internal tools with schema enforcement, RBAC checks, and sandboxed DB access.

### Frontend
- **Framework & Language:** React + TypeScript + Vite.
- **Styling:** Tailwind CSS + clean design system.
- **Dashboards:** Customer ticket view, Support Agent triage queue (with side-by-side HITL diffing/approval), and Admin analytics/RAG document management.

### Testing, DevOps & Quality
- **Testing:** Pytest, pytest-asyncio, HTTPX (Unit, Integration, API tests).
- **RAG & Agent Evaluation:** Golden test datasets evaluating Context Relevance, Faithfulness, and Answer Relevance (Ragas / custom deterministic assertions).
- **Containerization:** Docker multi-stage builds + Docker Compose.
- **CI/CD:** GitHub Actions (linting, type checking, test suites, automated image builds).

---

## 4. Key Architectural Invariants
1. **The LLM is Not the Application:** The LLM is an untrusted reasoning engine. It does not possess direct database access, cannot bypass authorization rules, and cannot modify ticket state outside bounded backend service methods.
2. **Deterministic Security & RBAC:** Role-Based Access Control (`ADMIN`, `SUPPORT_AGENT`, `CUSTOMER`) is enforced at the API gateway and service boundaries, never by prompt instructions.
3. **Auditability & Traceability:** Every AI inference, tool invocation, confidence score, and human modification is captured with structured logging and audit records.
4. **Vertical Slice Evolution:** New functionality is introduced in testable, end-to-end vertical increments rather than monolithic horizontal layers.
