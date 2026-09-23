"""Schemas package for SupportFlow AI."""

from backend.app.schemas.auth import (
    LoginRequest,
    MeResponse,
    RegisterRequest,
    TokenResponse,
    UserResponse,
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
]
