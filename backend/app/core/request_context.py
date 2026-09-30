"""Request context management for correlation IDs across async execution chains."""

from contextvars import ContextVar
import uuid

# ContextVar holding the correlation ID for the current async task / HTTP request
_request_id_ctx_var: ContextVar[str] = ContextVar("request_id", default="")


def get_request_id() -> str:
    """Retrieve the current request correlation ID, or generate a fallback if unset."""
    req_id = _request_id_ctx_var.get()
    return req_id if req_id else "system"


def set_request_id(req_id: str) -> None:
    """Set the current request correlation ID."""
    _request_id_ctx_var.set(req_id)


def generate_request_id() -> str:
    """Generate a clean UUID4 string suitable for X-Request-ID headers."""
    return str(uuid.uuid4())
