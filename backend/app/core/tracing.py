"""Lightweight execution tracing and span instrumentation for AI/RAG workflows."""

from collections import deque
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
import threading
import time
from typing import Any, AsyncGenerator, Deque, Dict, Generator, List, Optional

from backend.app.core.request_context import get_request_id


class Span:
    """Represents a single timed step in an AI or API pipeline."""

    def __init__(self, name: str, request_id: Optional[str] = None, **metadata: Any) -> None:
        self.name = name
        self.request_id = request_id or get_request_id()
        self.start_time: float = time.perf_counter()
        self.start_iso: str = datetime.now(timezone.utc).isoformat()
        self.end_time: Optional[float] = None
        self.duration_ms: float = 0.0
        self.status: str = "RUNNING"
        self.error_type: Optional[str] = None
        self.metadata: Dict[str, Any] = dict(metadata)

    def finish(self, status: str = "SUCCESS", error_type: Optional[str] = None) -> None:
        self.end_time = time.perf_counter()
        self.duration_ms = round((self.end_time - self.start_time) * 1000.0, 2)
        self.status = status
        self.error_type = error_type

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "request_id": self.request_id,
            "start_time": self.start_iso,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "error_type": self.error_type,
            "metadata": self.metadata,
        }


class PipelineTrace:
    """Represents an end-to-end trace composed of multiple child spans."""

    def __init__(self, trace_name: str, request_id: Optional[str] = None) -> None:
        self.trace_name = trace_name
        self.request_id = request_id or get_request_id()
        self.start_time: float = time.perf_counter()
        self.start_iso: str = datetime.now(timezone.utc).isoformat()
        self.duration_ms: float = 0.0
        self.status: str = "SUCCESS"
        self.spans: List[Span] = []

    def add_span(self, span: Span) -> None:
        self.spans.append(span)

    def finish(self, status: str = "SUCCESS") -> None:
        self.duration_ms = round((time.perf_counter() - self.start_time) * 1000.0, 2)
        self.status = status

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_name": self.trace_name,
            "request_id": self.request_id,
            "start_time": self.start_iso,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "spans": [s.to_dict() for s in self.spans],
        }


class TraceBuffer:
    """Thread-safe ring buffer storing recent pipeline traces for diagnostic APIs."""

    def __init__(self, capacity: int = 100) -> None:
        self.capacity = capacity
        self._lock = threading.Lock()
        self._traces: Deque[Dict[str, Any]] = deque(maxlen=capacity)

    def record_trace(self, trace: PipelineTrace) -> None:
        with self._lock:
            self._traces.append(trace.to_dict())

    def get_traces(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self._traces)
            return list(reversed(items[-limit:]))

    def clear(self) -> None:
        with self._lock:
            self._traces.clear()


# Global trace storage buffer
trace_buffer = TraceBuffer(capacity=100)


@contextmanager
def trace_span(name: str, trace: Optional[PipelineTrace] = None, **metadata: Any) -> Generator[Span, None, None]:
    """Synchronous context manager to measure and record a pipeline step."""
    span = Span(name, **metadata)
    if trace:
        trace.add_span(span)
    try:
        yield span
        span.finish(status="SUCCESS")
    except Exception as exc:
        span.finish(status="ERROR", error_type=exc.__class__.__name__)
        raise


@asynccontextmanager
async def async_trace_span(
    name: str, trace: Optional[PipelineTrace] = None, **metadata: Any
) -> AsyncGenerator[Span, None]:
    """Asynchronous context manager to measure and record an async pipeline step."""
    span = Span(name, **metadata)
    if trace:
        trace.add_span(span)
    try:
        yield span
        span.finish(status="SUCCESS")
    except Exception as exc:
        span.finish(status="ERROR", error_type=exc.__class__.__name__)
        raise
