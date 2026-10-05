# Observability & Middleware Stack — Reference

> Companion document to [architecture.md](../architecture.md)  
> Source: `backend/app/core/middleware.py`, `backend/app/core/logging.py`,  
> `backend/app/core/metrics.py`, `backend/app/core/tracing.py`, `backend/app/core/rate_limit.py`

---

## Middleware Execution Order

FastAPI/Starlette processes middleware in **reverse registration order**:

```
Registration order in main.py:
  1. app.add_middleware(ObservabilityMiddleware)
  2. app.add_middleware(SecurityHeadersMiddleware)
  3. app.add_middleware(CORSMiddleware, ...)

Effective execution order (inbound request):
  CORSMiddleware → SecurityHeadersMiddleware → ObservabilityMiddleware → route handler

Effective execution order (outbound response):
  route handler → ObservabilityMiddleware → SecurityHeadersMiddleware → CORSMiddleware
```

`ObservabilityMiddleware` is outermost on the response path — this ensures it can measure total latency and stamp all response headers after all inner middleware have run.

---

## ObservabilityMiddleware

**File:** `core/middleware.py` — `class ObservabilityMiddleware(BaseHTTPMiddleware)`

### On Request:
1. Read `X-Request-ID` from request headers; generate UUID if absent or blank
2. Store in `ContextVar` via `set_request_id()` (thread-safe async-safe)
3. Record `start_time = time.perf_counter()`

### On Response:
4. Calculate `duration_ms = (perf_counter() - start_time) × 1000`
5. Inject headers:
   - `X-Request-ID: <uuid>`
   - `X-Response-Time-Ms: <float>`
   - Rate-limit headers from `request.state.rate_limit_headers` (if set by rate limiter)
6. Call `metrics_collector.record_request(method, route, status_code, duration_ms)`
7. Emit structured log (skipped for `/health`, `/healthz` to avoid flooding)

### On Unhandled Exception:
- Records metrics with `status_code=500`
- Logs `ERROR` with `exc_info=True`
- Re-raises (global exception handler in `main.py` catches it and returns sanitized 500)

---

## SecurityHeadersMiddleware

**File:** `core/middleware.py` — `class SecurityHeadersMiddleware(BaseHTTPMiddleware)`

### On Request:
1. Check `Content-Length` header against `MAX_REQUEST_BODY_SIZE` (10 MB)
2. If exceeded → return `HTTP 413` JSON response immediately (does not reach route handler)

### On Response (if `ENABLE_SECURITY_HEADERS=True`):
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: geolocation=(), camera=(), microphone=(), payment=()`
- `Content-Security-Policy: <configured value>` (uses `setdefault` — won't override if already set)
- `Strict-Transport-Security: max-age=31536000; includeSubDomains` (only if `HSTS_ENABLED=True`)

---

## Structured Logging

**File:** `core/logging.py`

All log output is structured JSON. Standard fields on every log record:

```json
{
  "timestamp": "ISO-8601",
  "level": "INFO",
  "logger": "supportflow.http",
  "event": "http_request",
  "request_id": "<uuid>",
  "method": "POST",
  "route": "/api/v1/tickets/ask",
  "status_code": 200,
  "duration_ms": 123.4
}
```

Security events additionally include `user_id` and a `details` object.

Log level: `DEBUG` when `DEBUG=True`; `INFO` in production.

---

## Request Context

**File:** `core/request_context.py`

```python
_request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)

def set_request_id(request_id: str) -> None: ...
def get_request_id() -> Optional[str]: ...
def generate_request_id() -> str: ...  # returns str(uuid4())
```

The `ContextVar` provides per-task (per-coroutine) isolation in async code — safe for concurrent requests without thread-local confusion.

---

## In-Process Metrics

**File:** `core/metrics.py` — `metrics_collector`

Tracks per-route request counts, error counts, and latency histograms in process memory.  
Exposed via `/api/v1/analytics` endpoints.

**Note:** This is an in-process, non-persistent metrics store. Metrics reset on process restart. No Prometheus/OpenTelemetry export is implemented in the current codebase.

---

## Pipeline Tracing

**File:** `core/tracing.py`

`PipelineTrace` records spans for each named step within a single RAG pipeline invocation:

```python
trace = PipelineTrace("rag_pipeline")
async with async_trace_span("retrieval") as span:
    span.metadata["retrieved_count"] = len(docs)
```

Traces are accumulated in `trace_buffer` (in-process ring buffer) and returned in the pipeline response dict (`result["trace"]`).

---

## Rate Limiting

**File:** `core/rate_limit.py`

- **Backend:** Redis 7 sliding window
- **Fallback:** If Redis is unavailable (`_redis_failed=True`), rate limiting degrades gracefully (requests are not blocked)
- **Client IP resolution:** Respects `X-Forwarded-For` and `X-Real-IP` headers when `TRUST_PROXY_HEADERS=True`
- **Per-route configuration:**

```python
# Applied as FastAPI dependencies on route handlers
RateLimitDependency(limit=settings.RATE_LIMIT_AUTH)    # /auth endpoints
RateLimitDependency(limit=settings.RATE_LIMIT_AI)      # /ask endpoints
RateLimitDependency(limit=settings.RATE_LIMIT_UPLOAD)  # /upload endpoints
RateLimitDependency(limit=settings.RATE_LIMIT_DEFAULT) # all others
```

- **Headers set on `request.state.rate_limit_headers`**, then propagated by `ObservabilityMiddleware`:
  - `X-RateLimit-Limit`
  - `X-RateLimit-Remaining`
  - `X-RateLimit-Reset`

Rate limit headers are propagated even when a `429 Too Many Requests` response is returned (so clients can implement retry-after logic).
