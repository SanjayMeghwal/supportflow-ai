# ADR-009: Bounded AI Tool Execution Layer and Tool Registry

## Status
Accepted

## Context
In Phase 10 (ADR-008), SupportFlow AI implemented core LangGraph orchestration for grounded RAG synthesis using retrieved knowledge base passages. However, customer support inquiries often require access to dynamic, authoritative business records (such as order statuses, tracking numbers, and payment transaction details) that cannot be answered from static policy documentation alone.

Allowing an LLM unrestricted or direct access to APIs or databases introduces severe security and operational risks:
1. **Unbounded Code / Query Execution:** Allowing LLMs to write raw SQL, Python scripts, or shell commands leads to prompt injection, arbitrary remote code execution (RCE), and database compromise.
2. **Insecure Direct Object Reference (IDOR):** An LLM might be tricked into requesting or leaking data belonging to another customer if authorization is delegated to the model.
3. **Runaway Loops & Cost Explosion:** Without cycle caps, autonomous tool-calling agents can enter infinite loops, exhausting API rate limits and inflating latency.
4. **Data Leakage:** Raw ORM models or payment gateway responses contain sensitive internal fields (e.g., gateway secrets, customer IDs, hashed tokens, raw database UUIDs).
5. **Hallucinated Business Records:** If the model hallucinates operational data rather than querying authoritative backend services, customer trust is destroyed.

To solve this, SupportFlow AI requires a **sandboxed, bounded AI tool execution layer** tightly coupled with the LangGraph state machine and enforced by deterministic application-layer controls.

---

## Decision
We implement **Phase 11: Bounded AI Tool Execution Layer** adhering strictly to the architectural invariant: *"The LLM is an untrusted reasoning engine; the application enforces authorization, validation, and execution boundaries."*

### 1. Architectural Flow & Graph Integration
The tool layer extends the Phase 10 LangGraph state machine (`backend/app/services/rag_graph.py`) rather than replacing or duplicating it:

```text
                        START
                          │
                          ▼
                     [ retrieve ]
              (search_reranked: Vector +
               FTS + RRF + Cross-Encoder)
                          │
                          ▼
                [ context_assembly ]
             (Build structured context
              and extract source metadata)
                          │
                          ▼
                 context_available?
                /                  \
          [ YES ]                  [ NO ]
            │                        │
            ▼                        ▼
 [ generate_answer_or_    [ insufficient_context ]
     tool_call ]
    /          \
[ TOOL ]     [ PLAIN ]
   │             │
   ▼             │
[ execute_tool ] │
   │             │
   ▼             │
[ synthesize_    │
  with_tool ]    │
   │             │
   ▼             ▼
  [ validate_format ]
          │
          ▼
         END
```

### 2. Core Invariants & Security Guarantees

#### A. Tool Registry & Whitelist Enforcement (`backend/app/services/tool_registry.py`)
- Tools are statically declared in an immutable `TOOL_REGISTRY` mapping tool names to their Pydantic input schemas and async executor functions.
- Unknown tool requests (e.g., `delete_database`, `exec_code`) are immediately intercepted and rejected with an explicit error `ToolResult`.
- The LLM can never register, alter, or discover arbitrary tools dynamically. Only sanitized tool names and human-readable descriptions are exposed in the system prompt.

#### B. Strong Typing & Input Validation (`backend/app/schemas/tools.py`)
- Tool arguments are validated via dedicated Pydantic v2 schemas (`GetOrderStatusInput`, `GetPaymentStatusInput`) configured with `extra="forbid"`.
- Unexpected parameters, malformed types, or payload injections fail validation prior to invocation.
- Validation errors are trapped gracefully and returned as structured errors to the graph without unhandled exceptions.

#### C. Programmatic Authorization & IDOR Protection (`backend/app/services/tools.py`)
- Authorization is **never delegated to the LLM**.
- The `current_user` object is resolved from validated JWT credentials at the FastAPI dependency layer and injected into the graph state.
- Inside each tool executor:
  - `CUSTOMER` users are restricted strictly to records matching their verified `Customer.id`. Attempting to access another user's order or payment returns an authorization denial error.
  - `SUPPORT_AGENT` and `ADMIN` users possess authorized cross-customer read privileges to support customer inquiries.

#### D. Execution Sandboxing (No Code / No Raw SQL)
- Tools use pre-compiled SQLAlchemy ORM queries with bound parameters executed against the active `AsyncSession`.
- No `eval()`, `exec()`, shell execution, or dynamic SQL interpolation is used.

#### E. Tool Result Sanitization (`OrderStatusData`, `PaymentStatusData`)
- Output models explicitly define permitted return fields.
- Internal database IDs, raw JSON metadata, and payment gateway response payloads (`gateway_response_json`) are excluded from `ToolResult.data`.

#### F. Loop Prevention (`MAX_TOOL_CALLS = 3`)
- `AgentState.tool_calls_count` tracks tool invocations per pipeline execution.
- If the count reaches `MAX_TOOL_CALLS = 3`, execution is halted with an informative error result, preventing cyclic execution or runaway API costs.

---

## Consequences

### Positive
- **Strict Least-Privilege Execution:** The LLM cannot access records outside the authenticated user's permissions, preventing IDOR vulnerabilities.
- **Defense in Depth:** Validation via Pydantic, authorization via database-linked user context, and output sanitization via dedicated schemas form three independent security barriers.
- **Authoritative Data Grounding:** Real-time business data replaces LLM speculation for dynamic queries (order status, payment status).
- **Graceful Failure Mode:** Tool errors, authorization denials, and validation issues are structured as `ToolResult` facts allowing the LLM to explain the situation politely without crashing.

### Trade-offs & Limitations
- **Read-Only Bounded Scope:** Phase 11 tools are strictly read-only status lookups (`get_order_status`, `get_payment_status`). Write actions (e.g., initiating refunds, cancelling orders, updating customer details) are intentionally deferred to Phase 12 Human-In-The-Loop review.
- **Sequential Invocations:** The current tool node executes single tool invocations sequentially rather than concurrent multi-tool dispatches.
