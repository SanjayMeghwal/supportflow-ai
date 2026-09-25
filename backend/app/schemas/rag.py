"""Pydantic schemas for LangGraph RAG orchestration and query requests/responses."""

from typing import Any, Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field


class RAGSourceItem(BaseModel):
    """Source reference chunk propagated from multi-stage retrieval to the response."""

    model_config = ConfigDict(from_attributes=True)

    chunk_id: str = Field(description="Unique identifier of the document chunk")
    document_id: str = Field(description="Parent knowledge document identifier")
    document_title: str = Field(description="Title of the parent knowledge document")
    chunk_index: int = Field(description="Zero-based index of the chunk within the document")
    content: str = Field(description="Passage text used to ground the LLM response")
    score: float = Field(description="Relevance score produced by reranking/retrieval")
    metadata: Optional[dict[str, Any]] = Field(default=None, description="Arbitrary chunk metadata")


class RAGQueryRequest(BaseModel):
    """Inbound request payload for customer query answering via LangGraph RAG."""

    query: str = Field(
        ...,
        min_length=2,
        max_length=1000,
        description="Customer inquiry or support question",
        examples=["What is the refund timeline for a cancelled order?"],
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Number of context passages to retrieve and rerank for grounding",
    )


class RAGQueryResponse(BaseModel):
    """Outbound response payload containing the grounded answer and cited sources."""

    query: str = Field(description="Original customer inquiry")
    answer: str = Field(description="Synthesized grounded answer or insufficient-context notice")
    context_found: bool = Field(
        description="True if relevant knowledge chunks were found to answer the query"
    )
    sources: list[RAGSourceItem] = Field(
        default_factory=list,
        description="List of retrieved and reranked passages cited for this answer",
    )
