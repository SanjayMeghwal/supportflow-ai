"""LangGraph RAG orchestration workflow for grounded customer support answering."""

from typing import Any, Optional, TypedDict
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.services.knowledge import KnowledgeService
from backend.app.services.llm import BaseLLMService, get_llm_service

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


class AgentState(TypedDict, total=False):
    """Explicit state schema for the LangGraph RAG workflow."""

    # Inbound inputs
    query: str
    top_k: int

    # Multi-stage retrieval outputs
    retrieved_docs: list[dict[str, Any]]

    # Context assembly and source mapping
    context_text: str
    sources: list[dict[str, Any]]
    context_available: bool

    # Answer synthesis and validation
    answer: str
    is_valid: bool
    error: Optional[str]


def assemble_context(retrieved_docs: list[dict[str, Any]]) -> dict[str, Any]:
    """Assemble text context and extract citation metadata from retrieved chunks.

    Parameters
    ----------
    retrieved_docs : list[dict[str, Any]]
        List of ranked/reranked document chunks from KnowledgeService.

    Returns
    -------
    dict[str, Any]
        Dictionary updating context_text, sources, and context_available.
    """
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
    """Conditional router determining next node based on context availability.

    Returns
    -------
    str
        'generate_answer' if context is present, otherwise 'insufficient_context'.
    """
    if state.get("context_available", False):
        return "generate_answer"
    return "insufficient_context"


def validate_response(raw_answer: Optional[str]) -> dict[str, Any]:
    """Perform deterministic validation and cleanup on the generated response.

    Ensures the response is non-empty and stripped of extraneous whitespace.
    If the response is empty or whitespace-only, substitutes the safe fallback message.
    """
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


async def generate_grounded_answer(
    llm_service: BaseLLMService,
    query: str,
    context_text: str,
) -> str:
    """Invoke LLM with strict grounding prompt and context."""
    user_prompt = f"Reference Context:\n{context_text}\n\nCustomer Inquiry:\n{query}"
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    return await llm_service.generate(messages, temperature=0.0)


def build_rag_graph(
    knowledge_service: KnowledgeService,
    llm_service: BaseLLMService,
    db: AsyncSession,
) -> CompiledStateGraph:
    """Construct and compile the Phase 10 LangGraph RAG state graph.

    Graph Architecture
    ------------------
    START
      ↓
    retrieve (queries hybrid retrieval + cross-encoder reranker)
      ↓
    context_assembly (formats reference text and extracts source citations)
      ↓
    context_available?
      ├── NO  → insufficient_context → END
      └── YES → generate_answer → validate_format → END
    """
    workflow = StateGraph(AgentState)

    async def retrieve_step(state: AgentState) -> dict[str, Any]:
        docs = await knowledge_service.search_reranked(
            db=db,
            query=state["query"],
            top_k=state.get("top_k", 5),
        )
        return {"retrieved_docs": docs}

    def context_assembly_step(state: AgentState) -> dict[str, Any]:
        return assemble_context(state.get("retrieved_docs", []))

    def insufficient_context_step(state: AgentState) -> dict[str, Any]:
        return {
            "answer": INSUFFICIENT_CONTEXT_MESSAGE,
            "sources": [],
            "context_available": False,
            "is_valid": True,
        }

    async def generate_answer_step(state: AgentState) -> dict[str, Any]:
        raw_answer = await generate_grounded_answer(
            llm_service=llm_service,
            query=state["query"],
            context_text=state.get("context_text", ""),
        )
        return {"answer": raw_answer}

    def validate_format_step(state: AgentState) -> dict[str, Any]:
        return validate_response(state.get("answer", ""))

    # Register nodes
    workflow.add_node("retrieve", retrieve_step)
    workflow.add_node("context_assembly", context_assembly_step)
    workflow.add_node("insufficient_context", insufficient_context_step)
    workflow.add_node("generate_answer", generate_answer_step)
    workflow.add_node("validate_format", validate_format_step)

    # Register edges and conditional routing
    workflow.add_edge(START, "retrieve")
    workflow.add_edge("retrieve", "context_assembly")
    workflow.add_conditional_edges(
        "context_assembly",
        route_after_context_check,
        {
            "generate_answer": "generate_answer",
            "insufficient_context": "insufficient_context",
        },
    )
    workflow.add_edge("generate_answer", "validate_format")
    workflow.add_edge("validate_format", END)
    workflow.add_edge("insufficient_context", END)

    return workflow.compile()


async def run_rag_pipeline(
    query: str,
    db: AsyncSession,
    *,
    top_k: int = 5,
    knowledge_service: Optional[KnowledgeService] = None,
    llm_service: Optional[BaseLLMService] = None,
) -> dict[str, Any]:
    """Execute the compiled LangGraph RAG pipeline asynchronously.

    Parameters
    ----------
    query : str
        Customer inquiry.
    db : AsyncSession
        Active database session for multi-stage retrieval.
    top_k : int, optional
        Number of passages to retrieve and rerank, by default 5.
    knowledge_service : Optional[KnowledgeService], optional
        Knowledge service instance, by default None (instantiates default).
    llm_service : Optional[BaseLLMService], optional
        LLM service instance, by default None (resolves via get_llm_service).

    Returns
    -------
    dict[str, Any]
        Final state dictionary containing answer, sources, context_available, etc.
    """
    cleaned_query = (query or "").strip()
    if not cleaned_query:
        raise ValueError("Query string cannot be empty or whitespace-only.")

    ks = knowledge_service or KnowledgeService()
    ls = llm_service or get_llm_service()

    graph = build_rag_graph(knowledge_service=ks, llm_service=ls, db=db)

    initial_state: AgentState = {
        "query": cleaned_query,
        "top_k": top_k,
        "retrieved_docs": [],
        "context_text": "",
        "sources": [],
        "context_available": False,
        "answer": "",
        "is_valid": False,
        "error": None,
    }

    result = await graph.ainvoke(initial_state)
    return result
