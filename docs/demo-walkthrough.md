# SupportFlow AI — Demo Walkthrough

> **Audience:** Engineers, hiring managers, or anyone evaluating the project.
> **Goal:** Walk through the system end-to-end in under 15 minutes, demonstrating real backend engineering — not a ChatGPT wrapper.

---

## Prerequisites

| Requirement | Version |
|---|---|
| Docker + Docker Compose | 24+ |
| Python | 3.11+ |
| Node.js | 18+ |
| Git | any |

---

## Step 1 — Clone & Configure

```bash
git clone https://github.com/SanjayMeghwal/supportflow-ai.git
cd supportflow-ai
cp .env.example .env
```

Open `.env` and set at minimum:

```env
OPENAI_API_KEY=sk-...          # required for embeddings and LLM responses
SECRET_KEY=<random-32-chars>   # JWT signing key
```

All other defaults work for a local demo.

---

## Step 2 — Start the Stack

```bash
docker compose up -d
```

This starts:

| Service | Port | Purpose |
|---|---|---|
| `backend` | 8000 | FastAPI (async, Pydantic v2, SQLAlchemy 2.x) |
| `frontend` | 5173 | React SPA (Vite) |
| `postgres` | 5432 | PostgreSQL 15 + pgvector extension |
| `redis` | 6379 | Rate-limiting and caching |

Wait ~20 seconds for services to initialise, then verify health:

```bash
curl http://localhost:8000/health/live
# {"status":"ok"}

curl http://localhost:8000/health/ready
# {"status":"ok","database":"ok","redis":"ok"}
```

---

## Step 3 — Seed Demo Data

```bash
python scripts/demo_seed.py
```

This script creates deterministic, reproducible demo state:

| Resource | Count | Details |
|---|---|---|
| Users | 3 | demo@supportflow.ai (customer), agent@supportflow.ai, admin@supportflow.ai |
| Support Tickets | 4 | Spanning all lifecycle states: open → in_progress → resolved → closed |
| Knowledge-base docs | 5 | Product FAQ, billing policy, refund SOP, escalation rules, contact info |
| Orders | 2 | Linked to the demo customer for tool-call demonstrations |

> **Security note:** Seed credentials are demo-only and are loaded via the standard registration API — no backdoors, no auth bypass.

---

## Step 4 — Log In

Open **http://localhost:5173** in your browser.

Use the **one-click demo login buttons** on the login page, or enter credentials manually:

| Role | Email | Password |
|---|---|---|
| Customer | demo@supportflow.ai | DemoPass123! |
| Support Agent | agent@supportflow.ai | AgentPass123! |
| Admin | admin@supportflow.ai | AdminPass123! |

Each role lands on a different dashboard. Authentication is full JWT — the one-click buttons hit the same `/api/v1/auth/login` endpoint as a real user would.

---

## Step 5 — Demo: Customer Perspective

Log in as **demo@supportflow.ai**.

### 5a — Submit a Ticket

1. Click **New Ticket** → fill in a subject and description.
2. Submit. Note the `ticket_id` returned.
3. Observe the ticket appears in the **My Tickets** list with status `open`.

### 5b — AI Assistant (RAG Pipeline)

1. Navigate to **AI Assistant** in the sidebar.
2. Ask: *"What is your refund policy?"*

   **What happens under the hood:**
   - The query is embedded via the configured embedding model.
   - A **hybrid search** runs: pgvector ANN (semantic) + PostgreSQL full-text search (BM25-style) in parallel.
   - Results are merged, then **cross-encoder reranked** for precision.
   - The LangGraph agent selects the best passage and generates a grounded response.
   - The response panel shows **pipeline observability metadata**: retrieval latency, reranker score, tool name used.

3. Ask: *"Check the status of my latest order."*

   **What happens:**
   - The LangGraph agent invokes the **`check_order_status` tool** from the ToolRegistry.
   - The tool resolves the authenticated user's identity from the JWT — no user ID in the request body.
   - The tool returns real order data from PostgreSQL.
   - The response includes `tool_name: check_order_status` and latency in the metadata panel.

---

## Step 6 — Demo: Agent Perspective

Log out and log in as **agent@supportflow.ai**.

1. Navigate to **Tickets** → see all open/in-progress tickets across all customers.
2. Open a ticket → assign it to yourself → update status to `in_progress`.
3. Add an internal note (not visible to the customer).
4. Navigate to **AI Assistant** → ask the same refund policy question → same RAG pipeline, same grounded answer.

**RBAC in action:** The agent cannot access the Admin panel. Try navigating to `/admin/users` — you will receive a `403 Forbidden` response.

---

## Step 7 — Demo: Admin Perspective

Log out and log in as **admin@supportflow.ai**.

1. Navigate to **Admin → Users** → see the full user roster with roles.
2. Observe that the admin can modify roles, but even the admin cannot impersonate another user's resource ownership (IDOR protection is enforced at the database query level, not just middleware).
3. Navigate to **Architecture** in the sidebar for an in-browser engineering overview.

---

## Step 8 — Demo: Observability Endpoints

With any session active, open a new terminal:

```bash
# Structured JSON request logs
curl http://localhost:8000/api/v1/analytics/requests \
  -H "Authorization: Bearer <admin_jwt>"

# LLM pipeline analytics
curl http://localhost:8000/api/v1/analytics/llm \
  -H "Authorization: Bearer <admin_jwt>"

# Per-endpoint latency percentiles
curl http://localhost:8000/api/v1/analytics/performance \
  -H "Authorization: Bearer <admin_jwt>"
```

All analytics endpoints are admin-only (RBAC enforced). Data is collected in-process by `ObservabilityMiddleware` without a third-party APM dependency.

---

## Step 9 — Reset Demo State

To restore a clean slate:

```bash
python scripts/demo_seed.py --reset
```

This truncates demo-owned records and re-seeds fresh data. Safe to run repeatedly.

---

## Architecture Overview (in-browser)

The **Architecture** page (sidebar) renders a visual breakdown of:

- System components and data flows
- RAG pipeline node graph (LangGraph)
- Security controls and RBAC enforcement points
- Observability middleware stack

---

## What This Demo Is NOT

| Not demonstrated | Why |
|---|---|
| Paid cloud deployment | No live costs incurred; see `docs/deployment.md` for VPS instructions |
| Real customer data | All data is synthetic and deterministically seeded |
| External AI service mocking | Real OpenAI API is used; bring your own key |

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `health/ready` returns `{"database":"error"}` | Wait 30s for Postgres to finish init; retry |
| Embedding calls fail | Check `OPENAI_API_KEY` in `.env` |
| Demo seed fails with duplicate key | Run `python scripts/demo_seed.py --reset` first |
| Frontend blank page | Ensure `VITE_API_URL=http://localhost:8000` in `.env` |

---

*For the engineering deep-dive, see [`docs/interview-walkthrough.md`](interview-walkthrough.md).*
*For architecture decisions, see [`docs/architecture.md`](architecture.md) and [`docs/decisions/`](decisions/).*
