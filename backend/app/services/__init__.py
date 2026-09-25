"""Services package for SupportFlow AI."""

from backend.app.services.chunking import RecursiveTextChunker
from backend.app.services.embedding import EmbeddingService, get_embedding_service
from backend.app.services.extractors import extract_text
from backend.app.services.knowledge import DuplicateDocumentError, KnowledgeService
from backend.app.services.llm import (
    BaseLLMService,
    GroqLLMService,
    MockLLMService,
    get_llm_service,
    set_llm_service,
)
from backend.app.services.rag_graph import (
    AgentState,
    build_rag_graph,
    run_rag_pipeline,
)

__all__ = [
    "RecursiveTextChunker",
    "EmbeddingService",
    "get_embedding_service",
    "extract_text",
    "DuplicateDocumentError",
    "KnowledgeService",
    "BaseLLMService",
    "GroqLLMService",
    "MockLLMService",
    "get_llm_service",
    "set_llm_service",
    "AgentState",
    "build_rag_graph",
    "run_rag_pipeline",
]

