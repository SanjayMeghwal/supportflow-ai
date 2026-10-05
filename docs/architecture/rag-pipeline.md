# RAG Pipeline — Detailed Architecture

> Companion document to [architecture.md](../architecture.md)  
> Source: `backend/app/services/rag_graph.py`

---

## Overview

The SupportFlow AI RAG pipeline is implemented as a compiled LangGraph `StateGraph` (`CompiledStateGraph`). Each request to the AI endpoints (`/api/v1/tickets/{id}/ask` or `/api/v1/knowledge/ask`) invokes `run_rag_pipeline()`, which builds and executes the graph for that request.

---

## Pipeline Entry Point

```python
async def run_rag_pipeline(
    query: str,
    db: AsyncSession,
    *,
    top_k: int = 5,
    knowledge_service: Optional[KnowledgeService] = None,
    llm_service: Optional[BaseLLMService] = None,
    current_user: Optional[User] = None,
) -> dict[str, Any]
```

**Pre-flight guards applied before the graph runs:**

1. Empty/whitespace query → `ValueError`
2. Query truncated to `MAX_AI_INPUT_CHARS` (4000 chars) to prevent prompt injection / cost explosion

---

## Node Reference

### `retrieve`

- Calls `KnowledgeService.search_reranked(db, query, top_k)`
- Returns `retrieved_docs: list[dict]` — already reranked by cross-encoder score
- Traced with `async_trace_span("retrieval")`

### `context_assembly`

- Formats each retrieved doc into labeled context blocks wrapped in `<untrusted_reference_document>` XML tags (prompt injection mitigation)
- Extracts citation metadata: `chunk_id`, `document_id`, `document_title`, `chunk_index`, `score`
- Sets `context_available` flag

### `insufficient_context`

- Sets `answer` to a safe, pre-written refusal message
- Does not call the LLM
- Sets `context_available=False`

### `generate_answer_or_tool_call`

**Two modes depending on `current_user`:**

| Mode | Condition | System Prompt |
|---|---|---|
| Tool-aware | `current_user is not None` | `TOOL_AWARE_SYSTEM_PROMPT` (with tool descriptions) |
| Grounded answer only | `current_user is None` | `SYSTEM_PROMPT` |

Temperature: `0.0` (deterministic).

If the LLM output matches the tool-call JSON schema:
```json
{"tool_call": {"tool_name": "<name>", "arguments": {...}}}
```
it is parsed strictly by `_extract_tool_call_request()` → `ToolCallRequest` (Pydantic).  
Any malformed output is treated as a plain answer (no tool call executed).

### `execute_tool`

- Checks `tool_calls_count < MAX_TOOL_CALLS`; returns safe error ToolResult if exceeded
- Calls `dispatch_tool(request, current_user=current_user, db=db)` via `ToolRegistry`
- Only registered tool names are accepted; arguments are Pydantic-validated before execution
- Traced with `async_trace_span("tool_execution", tool_name=...)`

### `synthesize_with_tool`

- Passes authoritative tool result (JSON) + original reference context to LLM
- LLM instructed to treat tool result as ground truth, not contradict it
- Temperature: `0.0`

### `validate_format`

- Deterministic: strips whitespace, detects empty answer
- If empty → replaces with `INSUFFICIENT_CONTEXT_MESSAGE`

### `check_escalation`

- Calls `check_escalation_triggers(query, context_available, confidence_score, tool_result)`
- Confidence score proxy: rerank score of top retrieved document
- Escalation triggers (deterministic, no LLM involvement):
  1. Explicit human-request / guardrail keywords in query
  2. Tool execution failure or denial
  3. Missing knowledge base context (`context_available=False`)
  4. Confidence score below threshold (configurable, default `0.75`)
- Writes `escalation_triggered`, `escalation_reason`, `escalation_status` to state
- The API layer reads these flags and persists a `HumanReview` DB record if triggered

---

## Graph Routing

```python
# Conditional: context_assembly → (generate_answer_or_tool_call | insufficient_context)
route_after_context_check(state) → str

# Conditional: generate_answer_or_tool_call → (execute_tool | validate_format)
route_after_answer_or_tool(state) → str
```

Unconditional edges:
```
execute_tool → synthesize_with_tool → validate_format → check_escalation → END
insufficient_context → check_escalation → END
```

---

## Pipeline Output

```python
{
    "answer": str,
    "sources": list[dict],          # citation metadata for each used chunk
    "context_available": bool,
    "is_valid": bool,
    "tool_result": Optional[ToolResult],
    "escalation_triggered": bool,
    "escalation_reason": Optional[str],
    "escalation_status": Optional[str],
    "total_latency_ms": float,
    "trace": dict,                  # PipelineTrace with per-node spans
}
```

---

## Bounded Tool Registry

```python
# tool_registry.py
MAX_TOOL_CALLS = 3  # hard cap per pipeline run

TOOL_REGISTRY = {
    "get_order_status": get_order_status_tool,
    "get_payment_status": get_payment_status_tool,
}
```

Tools enforce their own authorization internally using the `current_user` passed from the API layer.
