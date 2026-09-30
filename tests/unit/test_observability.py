"""Unit tests for Phase 17 Observability, Logging, Metrics, Tracing, and Token Analytics."""

import json
import logging
import pytest
import time

from backend.app.core.logging import (
    StructuredJSONFormatter,
    sanitize_log_data,
)
from backend.app.core.metrics import RequestMetricsCollector
from backend.app.core.request_context import (
    generate_request_id,
    get_request_id,
    set_request_id,
)
from backend.app.core.tracing import (
    PipelineTrace,
    Span,
    TraceBuffer,
    async_trace_span,
    trace_span,
)
from backend.app.services.llm_analytics import (
    LLMAnalyticsService,
    estimate_tokens,
)


@pytest.mark.unit
class TestRequestContext:
    """Test correlation ID generation and async context management."""

    def test_generate_request_id_format(self):
        req_id = generate_request_id()
        assert isinstance(req_id, str)
        assert len(req_id) >= 32

    def test_set_and_get_request_id(self):
        test_id = "test-corr-id-12345"
        set_request_id(test_id)
        assert get_request_id() == test_id


@pytest.mark.unit
class TestStructuredLogging:
    """Test structured JSON logging and sensitive data redaction."""

    def test_sanitize_log_data_redacts_sensitive_keys(self):
        payload = {
            "username": "alice",
            "password": "SuperSecretPassword123!",
            "access_token": "eyJhbGciOi...",
            "api_key": "gsk_12345",
            "nested": {
                "jwt_secret_key": "my-secret",
                "normal_field": 42,
            },
            "list_field": [
                {"token": "secret-token", "item": "safe"},
            ],
        }
        sanitized = sanitize_log_data(payload)
        assert sanitized["username"] == "alice"
        assert sanitized["password"] == "[REDACTED]"
        assert sanitized["access_token"] == "[REDACTED]"
        assert sanitized["api_key"] == "[REDACTED]"
        assert sanitized["nested"]["jwt_secret_key"] == "[REDACTED]"
        assert sanitized["nested"]["normal_field"] == 42
        assert sanitized["list_field"][0]["token"] == "[REDACTED]"
        assert sanitized["list_field"][0]["item"] == "safe"

    def test_json_formatter_structure(self):
        formatter = StructuredJSONFormatter()
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg="User login successful",
            args=(),
            exc_info=None,
        )
        record.event = "auth_event"
        record.request_id = "req-abc-999"
        record.metadata = {"user_id": "u1", "password": "hidden"}

        formatted_str = formatter.format(record)
        data = json.loads(formatted_str)

        assert data["level"] == "INFO"
        assert data["logger"] == "test_logger"
        assert data["message"] == "User login successful"
        assert data["request_id"] == "req-abc-999"
        assert data["event"] == "auth_event"
        assert data["metadata"]["password"] == "[REDACTED]"
        assert data["metadata"]["user_id"] == "u1"


@pytest.mark.unit
class TestMetricsCollector:
    """Test in-memory request metrics and percentile computation."""

    def test_metrics_recording_and_percentiles(self):
        collector = RequestMetricsCollector(max_samples=100)
        collector.reset()

        # Record varied latencies
        latencies = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
        for lat in latencies:
            collector.record_request(
                method="GET",
                route="/api/v1/tickets",
                status_code=200,
                duration_ms=lat,
            )

        # Record an error
        collector.record_request(
            method="POST",
            route="/api/v1/tickets",
            status_code=500,
            duration_ms=150.0,
        )

        snapshot = collector.get_snapshot()
        assert snapshot["total_requests"] == 11
        assert snapshot["error_count"] == 1
        assert snapshot["error_rate"] == round(1 / 11, 4)
        assert snapshot["p50_latency_ms"] >= 40.0
        assert snapshot["p95_latency_ms"] >= 90.0
        assert snapshot["status_codes"][200] == 10
        assert snapshot["status_codes"][500] == 1
        assert "GET /api/v1/tickets" in snapshot["endpoints"]

    def test_metrics_empty_snapshot(self):
        collector = RequestMetricsCollector()
        collector.reset()
        snapshot = collector.get_snapshot()
        assert snapshot["total_requests"] == 0
        assert snapshot["error_rate"] == 0.0
        assert snapshot["p50_latency_ms"] == 0.0


@pytest.mark.unit
class TestTracingAndSpans:
    """Test synchronous and asynchronous tracing spans."""

    def test_sync_trace_span(self):
        trace = PipelineTrace("unit_test_trace", request_id="trace-123")
        with trace_span("step_1", trace=trace, custom_meta="abc") as span:
            time.sleep(0.01)

        assert span.status == "SUCCESS"
        assert span.duration_ms >= 8.0
        assert span.metadata["custom_meta"] == "abc"
        assert len(trace.spans) == 1

        trace.finish()
        trace_dict = trace.to_dict()
        assert trace_dict["trace_name"] == "unit_test_trace"
        assert len(trace_dict["spans"]) == 1

    @pytest.mark.asyncio
    async def test_async_trace_span(self):
        trace = PipelineTrace("async_trace")
        async with async_trace_span("async_step", trace=trace) as span:
            span.metadata["count"] = 5

        assert span.status == "SUCCESS"
        assert len(trace.spans) == 1

    def test_trace_span_error_capture(self):
        trace = PipelineTrace("failing_trace")
        with pytest.raises(ValueError):
            with trace_span("failing_step", trace=trace):
                raise ValueError("Intentional step error")

        assert len(trace.spans) == 1
        assert trace.spans[0].status == "ERROR"
        assert trace.spans[0].error_type == "ValueError"

    def test_trace_buffer_capacity(self):
        buf = TraceBuffer(capacity=5)
        for i in range(10):
            t = PipelineTrace(f"trace_{i}")
            t.finish()
            buf.record_trace(t)

        recent = buf.get_traces(limit=10)
        assert len(recent) == 5
        assert recent[0]["trace_name"] == "trace_9"


@pytest.mark.unit
class TestLLMAnalyticsService:
    """Test LLM call recording, token telemetry, and estimation."""

    def test_estimate_tokens(self):
        assert estimate_tokens("") == 0
        assert estimate_tokens("short text") >= 1
        assert estimate_tokens("a" * 400) == 100

    def test_record_call_with_actual_tokens(self):
        service = LLMAnalyticsService(in_memory_capacity=10)
        service.clear()

        record = service.record_call(
            model="llama-3.3-70b-versatile",
            provider="groq",
            operation="rag_synthesis",
            prompt_tokens=150,
            completion_tokens=50,
            total_tokens=200,
            is_estimated=False,
            latency_ms=320,
            success=True,
            request_id="req-99",
        )

        assert record["model"] == "llama-3.3-70b-versatile"
        assert record["prompt_tokens"] == 150
        assert record["completion_tokens"] == 50
        assert record["total_tokens"] == 200
        assert record["is_estimated"] is False
        assert record["success"] is True

        summary = service.get_in_memory_summary()
        assert summary["total_calls"] == 1
        assert summary["total_tokens"] == 200
        assert summary["success_count"] == 1
        assert summary["failure_count"] == 0
        assert "llama-3.3-70b-versatile" in summary["models"]

    def test_record_call_with_estimated_tokens(self):
        service = LLMAnalyticsService(in_memory_capacity=10)
        service.clear()

        record = service.record_call(
            model="mock-model",
            provider="mock",
            operation="mock_synthesis",
            prompt_tokens=40,
            completion_tokens=20,
            is_estimated=True,
            latency_ms=15,
            success=True,
        )

        assert record["is_estimated"] is True
        assert record["total_tokens"] == 60
