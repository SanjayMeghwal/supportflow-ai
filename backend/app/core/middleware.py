"""FastAPI middleware for request correlation, latency measurement, and metrics collection."""

import time
from typing import Callable
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from backend.app.core.logging import get_logger
from backend.app.core.metrics import metrics_collector
from backend.app.core.request_context import generate_request_id, set_request_id

logger = get_logger("supportflow.http")


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Middleware capturing request IDs, calculating latency, and updating metrics."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 1. Resolve or generate request correlation ID
        request_id = request.headers.get("X-Request-ID")
        if not request_id or not request_id.strip():
            request_id = generate_request_id()

        set_request_id(request_id)
        start_time = time.perf_counter()

        # 2. Process request
        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            route = request.url.path
            metrics_collector.record_request(
                method=request.method,
                route=route,
                status_code=500,
                duration_ms=duration_ms,
            )
            logger.error(
                f"HTTP {request.method} {route} failed with unhandled exception: {exc}",
                extra={
                    "event": "http_request_error",
                    "request_id": request_id,
                    "method": request.method,
                    "route": route,
                    "status_code": 500,
                    "duration_ms": duration_ms,
                    "error_type": exc.__class__.__name__,
                },
                exc_info=True,
            )
            raise

        # 3. Calculate latency and record metrics
        duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        route = request.url.path

        # Inject correlation and timing headers into response
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-Ms"] = str(duration_ms)

        # Update metrics collector
        metrics_collector.record_request(
            method=request.method,
            route=route,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )

        # Avoid logging noisy health checks at INFO level to prevent log flooding
        if route not in ("/health", "/healthz"):
            logger.info(
                f"HTTP {request.method} {route} {response.status_code} ({duration_ms}ms)",
                extra={
                    "event": "http_request",
                    "request_id": request_id,
                    "method": request.method,
                    "route": route,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                },
            )

        return response
