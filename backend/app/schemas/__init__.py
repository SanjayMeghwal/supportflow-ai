"""Schemas package for SupportFlow AI."""

from backend.app.schemas.auth import (
    LoginRequest,
    MeResponse,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from backend.app.schemas.knowledge import (
    DocumentChunkResponse,
    FAQDocumentCreateRequest,
    FAQItem,
    KnowledgeDocumentDetailResponse,
    KnowledgeDocumentListResponse,
    KnowledgeDocumentResponse,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    KnowledgeSearchResultItem,
    TextDocumentCreateRequest,
)
from backend.app.schemas.ticket import (
    TicketAssignRequest,
    TicketCreateRequest,
    TicketListResponse,
    TicketMessageCreateRequest,
    TicketMessageResponse,
    TicketResponse,
    TicketUpdateRequest,
)

__all__ = [
    "RegisterRequest",
    "LoginRequest",
    "TokenResponse",
    "UserResponse",
    "MeResponse",
    "TicketCreateRequest",
    "TicketUpdateRequest",
    "TicketAssignRequest",
    "TicketMessageCreateRequest",
    "TicketResponse",
    "TicketListResponse",
    "TicketMessageResponse",
    "TextDocumentCreateRequest",
    "FAQItem",
    "FAQDocumentCreateRequest",
    "DocumentChunkResponse",
    "KnowledgeDocumentResponse",
    "KnowledgeDocumentDetailResponse",
    "KnowledgeDocumentListResponse",
    "KnowledgeSearchRequest",
    "KnowledgeSearchResultItem",
    "KnowledgeSearchResponse",
]

