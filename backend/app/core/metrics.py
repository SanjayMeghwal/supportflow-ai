"""In-memory HTTP request metrics collector for low-overhead latency and throughput tracking."""

from collections import deque
import math
import threading
from typing import Any, Deque, Dict, List, Optional


class RequestMetricsCollector:
    """Thread-safe collector for HTTP request metrics, error rates, and latency distributions."""

    def __init__(self, max_samples: int = 1000) -> None:
        self.max_samples = max_samples
        self._lock = threading.Lock()
        self.total_requests: int = 0
        self.error_count: int = 0  # 4xx and 5xx
        self.status_codes: Dict[int, int] = {}
        self.latency_samples: Deque[float] = deque(maxlen=max_samples)
        self.endpoint_stats: Dict[str, Dict[str, Any]] = {}

    def record_request(
        self,
        method: str,
        route: str,
        status_code: int,
        duration_ms: float,
    ) -> None:
        """Record an incoming request completion."""
        with self._lock:
            self.total_requests += 1
            self.status_codes[status_code] = self.status_codes.get(status_code, 0) + 1

            if status_code >= 400:
                self.error_count += 1

            self.latency_samples.append(duration_ms)

            # Endpoint-specific tracking
            endpoint_key = f"{method} {route}"
            if endpoint_key not in self.endpoint_stats:
                self.endpoint_stats[endpoint_key] = {
                    "count": 0,
                    "errors": 0,
                    "total_duration_ms": 0.0,
                    "avg_duration_ms": 0.0,
                }

            stats = self.endpoint_stats[endpoint_key]
            stats["count"] += 1
            if status_code >= 400:
                stats["errors"] += 1
            stats["total_duration_ms"] += duration_ms
            stats["avg_duration_ms"] = round(
                stats["total_duration_ms"] / stats["count"], 2
            )

    def _calculate_percentile(self, sorted_samples: List[float], percentile: float) -> float:
        """Compute the given percentile (0-100) from a sorted list of samples."""
        if not sorted_samples:
            return 0.0
        k = (len(sorted_samples) - 1) * (percentile / 100.0)
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return round(sorted_samples[int(k)], 2)
        d0 = sorted_samples[int(f)] * (c - k)
        d1 = sorted_samples[int(c)] * (k - f)
        return round(d0 + d1, 2)

    def get_snapshot(self) -> Dict[str, Any]:
        """Return a structured snapshot of current operational metrics."""
        with self._lock:
            samples = sorted(list(self.latency_samples))
            count = self.total_requests
            errs = self.error_count
            error_rate = round(errs / count, 4) if count > 0 else 0.0
            avg_latency = round(sum(samples) / len(samples), 2) if samples else 0.0

            return {
                "total_requests": count,
                "error_count": errs,
                "error_rate": error_rate,
                "avg_latency_ms": avg_latency,
                "p50_latency_ms": self._calculate_percentile(samples, 50.0),
                "p95_latency_ms": self._calculate_percentile(samples, 95.0),
                "p99_latency_ms": self._calculate_percentile(samples, 99.0),
                "status_codes": dict(self.status_codes),
                "endpoint_count": len(self.endpoint_stats),
                "endpoints": {k: dict(v) for k, v in self.endpoint_stats.items()},
            }

    def reset(self) -> None:
        """Reset metrics (primarily used in test fixtures)."""
        with self._lock:
            self.total_requests = 0
            self.error_count = 0
            self.status_codes.clear()
            self.latency_samples.clear()
            self.endpoint_stats.clear()


# Global metrics collector instance
metrics_collector = RequestMetricsCollector()
request_metrics = metrics_collector
