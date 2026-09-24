"""Services package for SupportFlow AI."""

from backend.app.services.chunking import RecursiveTextChunker
from backend.app.services.embedding import EmbeddingService, get_embedding_service
from backend.app.services.extractors import extract_text
from backend.app.services.knowledge import DuplicateDocumentError, KnowledgeService

__all__ = [
    "RecursiveTextChunker",
    "EmbeddingService",
    "get_embedding_service",
    "extract_text",
    "DuplicateDocumentError",
    "KnowledgeService",
]
