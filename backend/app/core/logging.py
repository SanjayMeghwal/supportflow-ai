"""Structured JSON logging with request correlation and sensitive data sanitization."""

from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, Optional, Set

from backend.app.core.request_context import get_request_id

# Keys that must NEVER be logged directly
SENSITIVE_KEYS: Set[str] = {
    "password",
    "pass",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "auth",
    "api_key",
    "groq_api_key",
    "jwt_secret_key",
    "jwt",
    "credit_card",
    "card_number",
    "cvv",
}


def sanitize_log_data(data: Any, max_depth: int = 5) -> Any:
    """Recursively sanitize sensitive key-value pairs from logging payloads."""
    if max_depth <= 0:
        return "<max_depth_exceeded>"

    if isinstance(data, dict):
        sanitized: Dict[str, Any] = {}
        for key, value in data.items():
            key_lower = str(key).lower()
            if any(sens in key_lower for sens in SENSITIVE_KEYS):
                sanitized[key] = "[REDACTED]"
            else:
                sanitized[key] = sanitize_log_data(value, max_depth - 1)
        return sanitized
    elif isinstance(data, list):
        return [sanitize_log_data(item, max_depth - 1) for item in data]
    elif isinstance(data, tuple):
        return tuple(sanitize_log_data(item, max_depth - 1) for item in data)
    return data


class StructuredJSONFormatter(logging.Formatter):
    """Log formatter outputting single-line JSON records with correlation IDs."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None) or get_request_id(),
        }

        # Include custom structured extra fields if provided
        if hasattr(record, "event"):
            log_entry["event"] = record.event
        if hasattr(record, "operation"):
            log_entry["operation"] = record.operation
        if hasattr(record, "duration_ms"):
            log_entry["duration_ms"] = record.duration_ms
        if hasattr(record, "status_code"):
            log_entry["status_code"] = record.status_code
        if hasattr(record, "route"):
            log_entry["route"] = record.route
        if hasattr(record, "method"):
            log_entry["method"] = record.method
        if hasattr(record, "model"):
            log_entry["model"] = record.model
        if hasattr(record, "provider"):
            log_entry["provider"] = record.provider
        if hasattr(record, "tokens"):
            log_entry["tokens"] = record.tokens
        if hasattr(record, "metadata"):
            log_entry["metadata"] = sanitize_log_data(record.metadata)
        if hasattr(record, "security_event_type"):
            log_entry["security_event_type"] = record.security_event_type
        if hasattr(record, "user_id"):
            log_entry["user_id"] = record.user_id
        if hasattr(record, "details"):
            log_entry["details"] = sanitize_log_data(record.details)

        # Include exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str)


def setup_structured_logging(log_level: int = logging.INFO) -> None:
    """Configure the root logger with the StructuredJSONFormatter."""
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Avoid duplicate handlers
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(StructuredJSONFormatter())
    root_logger.addHandler(console_handler)


def get_logger(name: str) -> logging.Logger:
    """Retrieve a named logger configured for structured output."""
    return logging.getLogger(name)


def log_security_event(
    event_type: str,
    *,
    request_id: Optional[str] = None,
    user_id: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
    level: int = logging.WARNING,
) -> None:
    """Log an auditable security event via the structured JSON logger.

    Ensures sensitive fields in details are sanitized and standard security
    event attributes are attached.
    """
    logger = get_logger("supportflow.security")
    sanitized_details = sanitize_log_data(details) if details else {}
    req_id = request_id or get_request_id() or "unknown"

    extra = {
        "event": "security_audit",
        "security_event_type": event_type,
        "request_id": req_id,
        "user_id": str(user_id) if user_id else None,
        "details": sanitized_details,
    }
    logger.log(
        level,
        f"Security Event [{event_type}]: {sanitized_details.get('message', event_type)}",
        extra=extra,
    )

