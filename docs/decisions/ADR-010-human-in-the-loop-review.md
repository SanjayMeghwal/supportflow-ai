# ADR-010: Human-In-The-Loop Review and Escalation Workflow

**Status:** Accepted  
**Phase:** 12  
**Date:** 2026-09-28  
**Branch:** `feature/human-in-the-loop`  
**Author:** SupportFlow AI Engineering Team

---

## Context

Prior to Phase 12, the SupportFlow AI pipeline (Phases 10–11) could:

1. Retrieve grounded knowledge via hybrid RAG search.
2. Invoke bounded business tools (`get_order_status`, `get_payment_status`) under strict authorization.
3. Synthesize a final answer and deliver it to the customer.

This pipeline had **unlimited downstream authority** — the AI's synthesized response was dispatched to the customer without any human checkpoint. In regulated support environments, this creates risk:

- The AI may produce a factually correct but contextually inappropriate response.
- Low-confidence answers may be delivered without flagging.
- Customers explicitly requesting human assistance may receive an AI reply.
- Legal/chargeback keywords in a query may not receive appropriate escalation.
- Tool failures (denied orders, missing records) silently result in AI-generated guesses.

The core principle required by stakeholders:

> **"AI may recommend. Human may approve. Application enforces."**

---

## Decision

Introduce a **deterministic, application-layer escalation system** that intercepts AI pipeline results before customer delivery and routes qualifying runs to a human review queue.

### Architecture

```
LangGraph Pipeline
  retrieve → context_assembly → generate_answer_or_tool_call
           → [execute_tool → synthesize_with_tool]
           → validate_format
           → check_escalation          ← NEW Phase 12 node
                 ↓
         escalation_triggered = True?
         ├── NO  → answer is safe to deliver
         └── YES → API layer creates HumanReview DB record
                        ↓
                   Ticket → PENDING_AGENT_REVIEW
                        ↓
                   Human agent reviews draft
                        ↓
                   APPROVE / EDIT / REJECT / ESCALATE
```

### Components

| Component | File | Role |
|---|---|---|
| `check_escalation_triggers` | `services/review_service.py` | Deterministic rule engine |
| `check_escalation_step` | `services/rag_graph.py` | LangGraph node |
| `create_human_review` | `services/review_service.py` | DB record creation + ticket state |
| `submit_review_action` | `services/review_service.py` | Human action with row lock |
| `HumanReview` model | `models/ai.py` | Persistence |
| `ReviewStatus` / `ReviewAction` | `models/ai.py` | Lifecycle enums |
| Review router | `api/v1/reviews.py` | REST API for agents |
| ADR-010 | `docs/decisions/ADR-010-hitl.md` | This document |

---

## Escalation Trigger Rules

Evaluated **deterministically** (no ML inference) in strict priority order:

| Priority | Trigger | Resulting AIRunStatus |
|---|---|---|
| 1 | Explicit human-request or guardrail phrase in query | `ESCALATED_GUARDRAIL` |
| 2 | Tool execution failed or access denied | `ESCALATED_GUARDRAIL` |
| 3 | Knowledge base context missing | `ESCALATED_LOW_CONFIDENCE` |
| 4 | Reranker confidence score < 0.70 | `ESCALATED_LOW_CONFIDENCE` |
| — | None of the above | `SUCCESS` (no review needed) |

**Guardrail phrases include (non-exhaustive):**  
`talk to an agent`, `speak to a human`, `human please`, `manager`, `lawyer`, `legal action`, `chargeback`, `dispute payment`.

The phrase list is defined in `review_service.ESCALATION_PHRASES` and is application-controlled — the LLM cannot modify or bypass it.

---

## Human Review Actions

| Action | `ReviewAction` | Ticket outcome |
|---|---|---|
| **Approve** | `APPROVED` | Draft delivered as-is; ticket → `PENDING_CUSTOMER` (or `RESOLVED`) |
| **Edit** | `EDITED` | Modified text delivered; ticket → `PENDING_CUSTOMER` (or `RESOLVED`) |
| **Reject** | `REJECTED` | Draft discarded; ticket → `IN_PROGRESS`, agent assumes ownership |
| **Escalate** | `ESCALATED` | Routed to higher-tier agent; ticket → `IN_PROGRESS`, optional reassignment |

---

## Security Invariants

1. **The LLM cannot approve its own output.** The `check_escalation_step` node is deterministic Python — it does not call the LLM.
2. **reviewer_id is never accepted from the client.** It is derived server-side from the authenticated JWT in `require_support_agent`.
3. **CUSTOMER role cannot access review endpoints.** `require_support_agent` enforces `SUPPORT_AGENT | ADMIN`.
4. **Concurrency protection.** `submit_review_action` acquires `SELECT ... FOR UPDATE` on both the `HumanReview` and `Ticket` rows. A second concurrent reviewer sees `status != PENDING` and receives `HTTP 409 Conflict`.
5. **Audit trail.** Every review creation and action is persisted to `AuditLog` with `actor_id`, `actor_role`, `action`, and `change_details_json`.
6. **Escalation is deterministic.** Trigger evaluation uses only rule-based logic on application state — not LLM output analysis.

---

## Status Transition Updates

`VALID_STATUS_TRANSITIONS` (in `schemas/ticket.py`) was updated to permit:

```
PENDING_AGENT_REVIEW → PENDING_CUSTOMER   (approve/edit)
PENDING_AGENT_REVIEW → IN_PROGRESS        (reject/escalate)
```

The terminal state `CLOSED` remains non-transitionable.

---

## Database Migration

Migration `8efbad059e12` was applied to the `human_reviews` table:

- Added `status` column (`review_status_enum`, non-null, default `PENDING`)
- Added `escalation_reason` column (`VARCHAR(255)`, default `'AI escalation'`)
- Added `resolved_at` column (`TIMESTAMP WITH TIME ZONE`, nullable)
- Made `reviewer_id` nullable (no reviewer assigned at creation time)
- Made `action_taken` nullable (no action taken at creation time)

---

## REST API

```
GET  /api/v1/reviews/pending                 — Paginated FIFO queue for triage
GET  /api/v1/reviews/{review_id}             — Full review detail with AI run metadata
POST /api/v1/reviews/{review_id}/approve     — Approve AI draft as-is
POST /api/v1/reviews/{review_id}/edit        — Submit modified response
POST /api/v1/reviews/{review_id}/reject      — Reject and assign to agent
POST /api/v1/reviews/{review_id}/escalate    — Escalate to higher-tier agent
```

All endpoints require `Authorization: Bearer <token>` with `SUPPORT_AGENT` or `ADMIN` role.

---

## Consequences

**Positive:**
- Human oversight is now enforced at the application layer, not dependent on LLM self-restraint.
- Every escalation and human action is auditable with a complete trail.
- Concurrency protection prevents duplicate actions on the same review.
- The AI pipeline remains stateless — escalation metadata lives in `AgentState`; the API layer creates DB records.
- The `check_escalation` node is fully unit-testable without a database.

**Negative / Trade-offs:**
- High escalation rates from conservative thresholds will increase agent workload. The `CONFIDENCE_THRESHOLD` (0.70) should be tuned based on production metrics.
- `PENDING_AGENT_REVIEW` tickets block the automated flow; SLA tracking for the human queue is recommended for Phase 13.

---

## Alternatives Considered

| Alternative | Rejected reason |
|---|---|
| LLM self-assessment of confidence | LLM cannot be trusted to assess its own reliability |
| Probabilistic ML-based escalation | Adds model dependency; deterministic rules are auditable and explainable |
| Async notification only (no blocking) | Violates the principle that the AI must not have unlimited delivery authority |
| Per-ticket configuration of triggers | Adds complexity without clear benefit at this phase |
