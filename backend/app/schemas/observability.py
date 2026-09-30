"""Pydantic schemas for Observability, HTTP Metrics, Traces, and LLM Token Analytics."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class EndpointMetricItem(BaseModel):
    """Metrics for a single endpoint route."""

    count: int = 0
    errors: int = 0
    total_duration_ms: float = 0.0
    avg_duration_ms: float = 0.0


class RequestMetricsResponse(BaseModel):
    """HTTP request throughput, error rates, and percentile latencies."""

    model_config = ConfigDict(from_attributes=True)

    total_requests: int
    error_count: int
    error_rate: float
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    status_codes: Dict[str, int] = Field(default_factory=dict)
    endpoint_count: int = 0
    endpoints: Dict[str, EndpointMetricItem] = Field(default_factory=dict)


class LLMCallRecordResponse(BaseModel):
    """Detailed record of a single LLM invocation."""

    model_config = ConfigDict(from_attributes=True)

    id: Optional[str] = None
    request_id: str
    provider: str
    model: str
    operation: str
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    is_estimated: bool = False
    latency_ms: Optional[int] = None
    success: bool = True
    error_type: Optional[str] = None
    created_at: Optional[str] = None


class ModelUsageStat(BaseModel):
    """Token and latency breakdown for a specific model."""

    calls: int
    tokens: int
    avg_latency_ms: float


class OperationUsageStat(BaseModel):
    """Token and call count breakdown for an AI operation type."""

    calls: int
    tokens: int


class TokenBreakdown(BaseModel):
    """Prompt vs completion token counts."""

    prompt: int = 0
    completion: int = 0
    total: int = 0


class PeriodInfo(BaseModel):
    """Time filter window metadata."""

    start: str
    end: str
    label: str


class LLMAnalyticsSummaryResponse(BaseModel):
    """Aggregated LLM analytics across a specified time period."""

    model_config = ConfigDict(from_attributes=True)

    period: PeriodInfo
    total_calls: int
    success_count: int
    failure_count: int
    error_rate: float
    tokens: TokenBreakdown
    avg_latency_ms: float
    models: Dict[str, ModelUsageStat] = Field(default_factory=dict)
    operations: Dict[str, OperationUsageStat] = Field(default_factory=dict)
    recent_records: List[LLMCallRecordResponse] = Field(default_factory=list)


class TraceSpanResponse(BaseModel):
    """Single span inside an execution trace."""

    name: str
    request_id: str
    start_time: str
    duration_ms: float
    status: str
    error_type: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PipelineTraceResponse(BaseModel):
    """End-to-end execution trace for an AI/RAG request."""

    trace_name: str
    request_id: str
    start_time: str
    duration_ms: float
    status: str
    spans: List[TraceSpanResponse] = Field(default_factory=list)


class ObservabilityOverviewResponse(BaseModel):
    """Unified system observability overview."""

    model_config = ConfigDict(from_attributes=True)

    system_status: str
    requests: RequestMetricsResponse
    llm: Dict[str, Any]
    recent_traces_count: int
