"""LangGraph RAG + bounded AI-tool orchestration workflow.

Phase 10 — RAG Orchestration
  Retrieval → context assembly → grounded answer via Groq.

Phase 11 — Bounded AI Tool Execution Layer
  After initial answer synthesis, if the LLM signals it needs a business tool
  (get_order_status, get_payment_status) to answer the query, the application:
    1. Parses and validates the tool call request strictly.
    2. Dispatches it through the ToolRegistry (never the LLM directly).
    3. Enforces authorization inside each tool.
    4. Re-synthesizes the answer with the authoritative tool result as additional context.

Phase 12 — Human-In-The-Loop Escalation Detection
  After answer validation, the pipeline deterministically evaluates whether the
  result requires human review before delivery to the customer.  Triggers are:
    1. Explicit human-request or guardrail keywords in the query.
    2. Tool execution failure or denial.
    3. Missing knowledge base context.
    4. Grounding confidence score below the configured threshold (0.70).
  When a trigger fires, escalation metadata is written into AgentState.
  The API layer reads these flags and persists the HumanReview record.
  The LLM CANNOT approve, edit, or reject its own output.

Security invariants:
  - The LLM cannot bypass the ToolRegistry.
  - Tool calls are capped at MAX_TOOL_CALLS per run.
  - current_user is always passed from the API layer, never derived from LLM output.
  - Tool results replace speculation — the LLM must use them as ground truth.
  - Escalation decisions are deterministic and application-enforced, not LLM-driven.
"""

import json
import re
from typing import Any, Optional, TypedDict
import time
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.tracing import (
    PipelineTrace,
    async_trace_span,
    trace_buffer,
    trace_span,
)
from backend.app.models.user import User
from backend.app.schemas.tools import ToolCallRequest, ToolResult
from backend.app.services.knowledge import KnowledgeService
from backend.app.services.llm import BaseLLMService, get_llm_service
from backend.app.services.review_service import check_escalation_triggers
from backend.app.services.tool_registry import (
    MAX_TOOL_CALLS,
    dispatch_tool,
    get_tool_descriptions,
)

INSUFFICIENT_CONTEXT_MESSAGE: str = (
    "I do not have sufficient information in the knowledge base to answer your question. "
    "Please contact our support team or check our official documentation for more details."
)

SYSTEM_PROMPT: str = (
    "You are a reliable, professional customer support AI assistant for SupportFlow AI.\n"
    "Your objective is to answer the customer's inquiry accurately and concisely, strictly based on the provided reference context.\n\n"
    "Guidelines:\n"
    "1. Base your answer ONLY on the explicit facts provided in the reference context.\n"
    "2. Do not invent, speculate, or assume details not supported by the context.\n"
    "3. If the context only partially answers the inquiry, explain clearly what is known and what cannot be confirmed.\n"
    "4. Maintain a courteous, professional, and clear tone suited for customer support."
)

# Injected into the system prompt when tools are available
TOOL_AWARE_SYSTEM_PROMPT: str = (
    "You are a reliable, professional customer support AI assistant for SupportFlow AI.\n"
    "Your objective is to answer the customer's inquiry accurately using the provided reference context "
    "and, when necessary, real-time business data retrieved via approved tools.\n\n"
    "You have access to the following tools:\n"
    "{tool_descriptions}\n\n"
    "Guidelines:\n"
    "1. First, attempt to answer using the provided reference context.\n"
    "2. If the query requires real-time business data (e.g., order status, payment status), "
    "you MUST request a tool call instead of guessing.\n"
    "3. To request a tool call, respond ONLY with a JSON object in this exact format:\n"
    '   {{"tool_call": {{"tool_name": "<name>", "arguments": {{...}}}}}}\n'
    "4. Do NOT include any other text when requesting a tool call.\n"
    "5. If you do not need a tool, respond with a plain answer.\n"
    "6. Do NOT invent order numbers, payment references, or any business data.\n"
    "7. Maintain a courteous, professional, and clear tone."
)

SYNTHESIS_WITH_TOOL_PROMPT: str = (
    "You are a reliable, professional customer support AI assistant for SupportFlow AI.\n"
    "The following tool result contains authoritative, real-time business data. "
    "Use it as the definitive answer for the relevant part of the query.\n\n"
    "Tool Result:\n"
    "{tool_result_json}\n\n"
    "Reference Context:\n"
    "{context_text}\n\n"
    "Guidelines:\n"
    "1. Incorporate the tool result as authoritative fact — do not contradict it.\n"
    "2. Supplement with reference context where relevant.\n"
    "3. Do not mention internal field names (IDs, raw JSON keys) — use human-readable descriptions.\n"
    "4. Maintain a courteous, professional, and clear tone."
)


# ---------------------------------------------------------------------------
# AgentState — Phase 12 extension
# ---------------------------------------------------------------------------


class AgentState(TypedDict, total=False):
    """Explicit state schema for the LangGraph RAG + tool + HITL escalation workflow."""

    # Inbound inputs
    query: str
    top_k: int

    # Authenticated user (passed from API layer, never from LLM output)
    current_user: Optional[User]

    # Multi-stage retrieval outputs
    retrieved_docs: list[dict[str, Any]]

    # Context assembly and source mapping
    context_text: str
    sources: list[dict[str, Any]]
    context_available: bool

    # Phase 11: tool call state
    tool_call_request: Optional[ToolCallRequest]   # parsed from LLM output
    tool_result: Optional[ToolResult]              # result from ToolRegistry
    tool_calls_count: int                          # guard against loops

    # Answer synthesis and validation
    answer: str
    is_valid: bool
    error: Optional[str]

    # Phase 12: Human-In-The-Loop escalation detection
    # These fields are written by the check_escalation node.
    # The API layer reads them to persist a HumanReview DB record.
    escalation_triggered: bool                  # True iff the run must pause for human review
    escalation_reason: Optional[str]            # Human-readable trigger description
    escalation_status: Optional[str]            # AIRunStatus value (ESCALATED_GUARDRAIL|ESCALATED_LOW_CONFIDENCE)


# ---------------------------------------------------------------------------
# Utility functions (Phase 10 — unchanged)
# ---------------------------------------------------------------------------


def assemble_context(retrieved_docs: list[dict[str, Any]]) -> dict[str, Any]:
    """Assemble text context and extract citation metadata from retrieved chunks."""
    if not retrieved_docs:
        return {
            "context_available": False,
            "context_text": "",
            "sources": [],
        }

    context_blocks: list[str] = []
    sources: list[dict[str, Any]] = []

    for idx, doc in enumerate(retrieved_docs, start=1):
        content = (doc.get("content") or "").strip()
        if not content:
            continue

        doc_title = doc.get("document_title") or "Document"
        chunk_idx = doc.get("chunk_index", 0)
        score = float(doc.get("rerank_score", doc.get("score", 0.0)))

        context_blocks.append(
            f"[Source {idx}]: {doc_title} (Passage {chunk_idx + 1})\n{content}"
        )

        sources.append(
            {
                "chunk_id": str(doc.get("chunk_id", "")),
                "document_id": str(doc.get("document_id", "")),
                "document_title": doc_title,
                "chunk_index": chunk_idx,
                "content": content,
                "score": round(score, 4),
                "metadata": doc.get("metadata") or {},
            }
        )

    if not context_blocks:
        return {
            "context_available": False,
            "context_text": "",
            "sources": [],
        }

    return {
        "context_available": True,
        "context_text": "\n\n---\n\n".join(context_blocks),
        "sources": sources,
    }


def route_after_context_check(state: AgentState) -> str:
    """Route based on context availability."""
    if state.get("context_available", False):
        return "generate_answer_or_tool_call"
    return "insufficient_context"


def validate_response(raw_answer: Optional[str]) -> dict[str, Any]:
    """Deterministic validation and cleanup on the generated response."""
    cleaned = (raw_answer or "").strip()
    if not cleaned:
        return {
            "answer": INSUFFICIENT_CONTEXT_MESSAGE,
            "is_valid": False,
            "error": "Generated answer was empty.",
        }
    return {
        "answer": cleaned,
        "is_valid": True,
        "error": None,
    }


# ---------------------------------------------------------------------------
# Phase 11: Tool-call parsing from LLM output
# ---------------------------------------------------------------------------


def _extract_tool_call_request(raw_output: str) -> Optional[ToolCallRequest]:
    """Attempt to parse a ToolCallRequest from raw LLM output.

    The LLM is instructed to produce ONLY a JSON object when requesting a tool:
      {"tool_call": {"tool_name": "...", "arguments": {...}}}

    This function is intentionally strict — any malformed output is treated as
    a regular answer (no tool call).  The LLM cannot trigger arbitrary tool
    execution via prompt injection because:
      1. Only registered tool names pass the ToolRegistry check.
      2. Pydantic validates all arguments before any execution.

    Returns
    -------
    ToolCallRequest or None
        Parsed request if valid, None otherwise.
    """
    text = (raw_output or "").strip()

    # Attempt direct JSON parse first (LLM output is the whole JSON object)
    try:
        payload = json.loads(text)
        if isinstance(payload, dict) and "tool_call" in payload:
            tc = payload["tool_call"]
            return ToolCallRequest(
                tool_name=tc.get("tool_name", ""),
                arguments=tc.get("arguments", {}),
            )
    except (json.JSONDecodeError, Exception):
        pass

    # Fallback: look for a JSON code block the LLM may have wrapped
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            payload = json.loads(match.group(1))
            if isinstance(payload, dict) and "tool_call" in payload:
                tc = payload["tool_call"]
                return ToolCallRequest(
                    tool_name=tc.get("tool_name", ""),
                    arguments=tc.get("arguments", {}),
                )
        except (json.JSONDecodeError, Exception):
            pass

    return None


def route_after_answer_or_tool(state: AgentState) -> str:
    """Route based on whether the LLM requested a tool call."""
    if state.get("tool_call_request") is not None:
        return "execute_tool"
    return "validate_format"


# ---------------------------------------------------------------------------
# Graph builder — Phase 10 + Phase 11 integrated
# ---------------------------------------------------------------------------


def build_rag_graph(
    knowledge_service: KnowledgeService,
    llm_service: BaseLLMService,
    db: AsyncSession,
    current_user: Optional[User] = None,
) -> CompiledStateGraph:
    """Construct and compile the Phase 10 + 11 + 12 LangGraph RAG state graph.

    Graph Architecture (Phase 12)
    ------------------------------
    START
      ↓
    retrieve (hybrid retrieval + cross-encoder reranker)
      ↓
    context_assembly (formats reference text + citations)
      ↓
    context_available?
      ├── NO  → insufficient_context → check_escalation → END
      └── YES → generate_answer_or_tool_call
                  ├── tool requested? YES → execute_tool → synthesize_with_tool → validate_format → check_escalation → END
                  └── NO → validate_format → check_escalation → END

    Security:
      - current_user is resolved from the API layer and injected at build time.
      - Tool execution is capped by MAX_TOOL_CALLS.
      - ToolRegistry enforces authorization inside each tool.
      - Escalation is deterministic and application-enforced — the LLM cannot
        approve, edit, or reject its own output.
    """
    # Prepare tool-aware system prompt if user context is available
    tool_descriptions_text = "\n".join(
        f"  - {t['tool_name']}: {t['description']}"
        for t in get_tool_descriptions()
    )
    system_prompt_with_tools = TOOL_AWARE_SYSTEM_PROMPT.format(
        tool_descriptions=tool_descriptions_text
    )

    workflow = StateGraph(AgentState)

    # -----------------------------------------------------------------------
    # Node: retrieve
    # -----------------------------------------------------------------------

    async def retrieve_step(state: AgentState) -> dict[str, Any]:
        async with async_trace_span("retrieval") as span:
            docs = await knowledge_service.search_reranked(
                db=db,
                query=state["query"],
                top_k=state.get("top_k", 5),
            )
            span.metadata["retrieved_count"] = len(docs)
            return {"retrieved_docs": docs}

    # -----------------------------------------------------------------------
    # Node: context_assembly
    # -----------------------------------------------------------------------

    def context_assembly_step(state: AgentState) -> dict[str, Any]:
        return assemble_context(state.get("retrieved_docs", []))

    # -----------------------------------------------------------------------
    # Node: insufficient_context
    # -----------------------------------------------------------------------

    def insufficient_context_step(state: AgentState) -> dict[str, Any]:
        return {
            "answer": INSUFFICIENT_CONTEXT_MESSAGE,
            "sources": [],
            "context_available": False,
            "is_valid": True,
        }

    # -----------------------------------------------------------------------
    # Node: generate_answer_or_tool_call  (Phase 11 replacement of Phase 10's generate_answer)
    # -----------------------------------------------------------------------

    async def generate_answer_or_tool_call_step(state: AgentState) -> dict[str, Any]:
        """Generate an answer or a structured tool call request.

        If a user context is available, use the tool-aware prompt so the LLM
        knows it can request business tools.  Otherwise fall back to the
        grounded-answer-only prompt (Phase 10 behaviour for anonymous use).
        """
        use_tool_prompt = current_user is not None

        if use_tool_prompt:
            user_prompt = (
                f"Reference Context:\n{state.get('context_text', '')}\n\n"
                f"Customer Inquiry:\n{state['query']}"
            )
            messages = [
                {"role": "system", "content": system_prompt_with_tools},
                {"role": "user", "content": user_prompt},
            ]
        else:
            user_prompt = (
                f"Reference Context:\n{state.get('context_text', '')}\n\n"
                f"Customer Inquiry:\n{state['query']}"
            )
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]

        async with async_trace_span("llm_generation") as span:
            raw_output = await llm_service.generate(
                messages,
                temperature=0.0,
                operation="rag_synthesis",
            )
            span.metadata["output_length"] = len(raw_output)

        # Check if LLM requested a tool call
        tool_call_request = None
        if use_tool_prompt:
            tool_call_request = _extract_tool_call_request(raw_output)

        if tool_call_request is not None:
            return {
                "answer": raw_output,   # store raw for debug; will be replaced after tool
                "tool_call_request": tool_call_request,
                "tool_calls_count": state.get("tool_calls_count", 0),
            }

        return {
            "answer": raw_output,
            "tool_call_request": None,
        }

    # -----------------------------------------------------------------------
    # Node: execute_tool  (Phase 11)
    # -----------------------------------------------------------------------

    async def execute_tool_step(state: AgentState) -> dict[str, Any]:
        """Execute the validated tool call and store the result in state.

        Guards:
          - MAX_TOOL_CALLS cap: if exceeded, returns a safe error ToolResult.
          - current_user must exist (guaranteed by the graph builder injection).
        """
        calls_so_far = state.get("tool_calls_count", 0)
        if calls_so_far >= MAX_TOOL_CALLS:
            return {
                "tool_result": ToolResult(
                    tool_name=state["tool_call_request"].tool_name,
                    success=False,
                    data=None,
                    error=f"Tool call limit ({MAX_TOOL_CALLS}) exceeded. Cannot execute further tool calls.",
                ),
                "tool_calls_count": calls_so_far + 1,
                "tool_call_request": None,
            }

        request = state["tool_call_request"]
        tool_name = request.tool_name if request else "unknown"

        async with async_trace_span("tool_execution", tool_name=tool_name) as span:
            result = await dispatch_tool(
                request,
                current_user=current_user,
                db=db,
            )
            span.metadata["success"] = result.success

        return {
            "tool_result": result,
            "tool_calls_count": calls_so_far + 1,
            "tool_call_request": None,  # clear so we don't loop
        }

    # -----------------------------------------------------------------------
    # Node: synthesize_with_tool  (Phase 11)
    # -----------------------------------------------------------------------

    async def synthesize_with_tool_step(state: AgentState) -> dict[str, Any]:
        """Re-synthesize the answer using the authoritative tool result as fact.

        The LLM receives:
          - The tool result as structured JSON (ground truth).
          - The original reference context (background knowledge).
          - The customer's original inquiry.

        It MUST use the tool result as authoritative and not contradict it.
        """
        tool_result: ToolResult = state.get("tool_result")
        tool_result_json = json.dumps(
            tool_result.model_dump() if tool_result else {}, indent=2
        )

        synthesis_system = SYNTHESIS_WITH_TOOL_PROMPT.format(
            tool_result_json=tool_result_json,
            context_text=state.get("context_text", ""),
        )

        user_prompt = f"Customer Inquiry:\n{state['query']}"
        messages = [
            {"role": "system", "content": synthesis_system},
            {"role": "user", "content": user_prompt},
        ]

        async with async_trace_span("tool_synthesis") as span:
            raw_answer = await llm_service.generate(
                messages,
                temperature=0.0,
                operation="tool_synthesis",
            )
            span.metadata["output_length"] = len(raw_answer)

        return {"answer": raw_answer}

    # -----------------------------------------------------------------------
    # Node: validate_format
    # -----------------------------------------------------------------------

    def validate_format_step(state: AgentState) -> dict[str, Any]:
        return validate_response(state.get("answer", ""))

    # -----------------------------------------------------------------------
    # Node: check_escalation  (Phase 12)
    # -----------------------------------------------------------------------

    def check_escalation_step(state: AgentState) -> dict[str, Any]:
        """Deterministically evaluate whether this run requires human review.

        Reads finalized state (answer, context_available, tool_result) and calls
        the application-level `check_escalation_triggers` function.  The result
        is stored as escalation metadata in state — the API layer reads these
        fields and creates the HumanReview DB record if needed.

        The LLM has no access to this node and cannot influence its output.
        """
        # Derive a confidence score proxy from the best reranked doc score
        confidence_score: Optional[float] = None
        docs = state.get("retrieved_docs") or []
        if docs:
            top_score = docs[0].get("rerank_score", docs[0].get("score"))
            if top_score is not None:
                confidence_score = float(top_score)

        with trace_span("check_escalation") as span:
            should_escalate, reason, run_status = check_escalation_triggers(
                state.get("query", ""),
                context_available=state.get("context_available", False),
                confidence_score=confidence_score,
                tool_result=state.get("tool_result"),
            )
            span.metadata["escalation_triggered"] = should_escalate

        return {
            "escalation_triggered": should_escalate,
            "escalation_reason": reason,
            "escalation_status": run_status.value,
        }

    # -----------------------------------------------------------------------
    # Register nodes
    # -----------------------------------------------------------------------
    workflow.add_node("retrieve", retrieve_step)
    workflow.add_node("context_assembly", context_assembly_step)
    workflow.add_node("insufficient_context", insufficient_context_step)
    workflow.add_node("generate_answer_or_tool_call", generate_answer_or_tool_call_step)
    workflow.add_node("execute_tool", execute_tool_step)
    workflow.add_node("synthesize_with_tool", synthesize_with_tool_step)
    workflow.add_node("validate_format", validate_format_step)
    workflow.add_node("check_escalation", check_escalation_step)

    # -----------------------------------------------------------------------
    # Register edges and conditional routing
    # -----------------------------------------------------------------------
    workflow.add_edge(START, "retrieve")
    workflow.add_edge("retrieve", "context_assembly")
    workflow.add_conditional_edges(
        "context_assembly",
        route_after_context_check,
        {
            "generate_answer_or_tool_call": "generate_answer_or_tool_call",
            "insufficient_context": "insufficient_context",
        },
    )
    workflow.add_conditional_edges(
        "generate_answer_or_tool_call",
        route_after_answer_or_tool,
        {
            "execute_tool": "execute_tool",
            "validate_format": "validate_format",
        },
    )
    workflow.add_edge("execute_tool", "synthesize_with_tool")
    workflow.add_edge("synthesize_with_tool", "validate_format")
    workflow.add_edge("validate_format", "check_escalation")
    workflow.add_edge("insufficient_context", "check_escalation")
    workflow.add_edge("check_escalation", END)

    return workflow.compile()


# ---------------------------------------------------------------------------
# Public pipeline entry point
# ---------------------------------------------------------------------------


async def run_rag_pipeline(
    query: str,
    db: AsyncSession,
    *,
    top_k: int = 5,
    knowledge_service: Optional[KnowledgeService] = None,
    llm_service: Optional[BaseLLMService] = None,
    current_user: Optional[User] = None,
) -> dict[str, Any]:
    """Execute the compiled LangGraph RAG + tool pipeline asynchronously.

    Parameters
    ----------
    query : str
        Customer inquiry.
    db : AsyncSession
        Active database session for retrieval and tool execution.
    top_k : int, optional
        Number of passages to retrieve and rerank, by default 5.
    knowledge_service : Optional[KnowledgeService], optional
        Knowledge service instance, by default None (instantiates default).
    llm_service : Optional[BaseLLMService], optional
        LLM service instance, by default None (resolves via get_llm_service).
    current_user : Optional[User], optional
        Authenticated user from the API layer, required for tool-enabled execution.
        If None, tools are disabled and the graph runs in Phase 10 RAG-only mode.

    Returns
    -------
    dict[str, Any]
        Final state dictionary containing answer, sources, context_available,
        tool_result (if any), and is_valid.
    """
    cleaned_query = (query or "").strip()
    if not cleaned_query:
        raise ValueError("Query string cannot be empty or whitespace-only.")

    ks = knowledge_service or KnowledgeService()
    ls = llm_service or get_llm_service()

    graph = build_rag_graph(
        knowledge_service=ks,
        llm_service=ls,
        db=db,
        current_user=current_user,
    )

    initial_state: AgentState = {
        "query": cleaned_query,
        "top_k": top_k,
        "current_user": current_user,
        "retrieved_docs": [],
        "context_text": "",
        "sources": [],
        "context_available": False,
        "tool_call_request": None,
        "tool_result": None,
        "tool_calls_count": 0,
        "answer": "",
        "is_valid": False,
        "error": None,
        # Phase 12 escalation defaults (overwritten by check_escalation node)
        "escalation_triggered": False,
        "escalation_reason": None,
        "escalation_status": None,
    }

    trace = PipelineTrace("rag_pipeline")
    start_time = time.perf_counter()
    result = await graph.ainvoke(initial_state)
    duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
    trace.finish(status="SUCCESS" if result.get("is_valid", True) else "FAILED")
    trace_buffer.record_trace(trace)
    result["total_latency_ms"] = duration_ms
    result["trace"] = trace.to_dict()

    return result
