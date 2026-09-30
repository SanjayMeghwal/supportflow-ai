"""LLM analytics service for tracking model usage, token consumption, and latency."""

from collections import deque
from datetime import datetime, timedelta, timezone
import math
import threading
from typing import Any, Deque, Dict, List, Optional
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.logging import get_logger, sanitize_log_data
from backend.app.core.request_context import get_request_id
from backend.app.models.analytics import LLMAnalyticsRecord

logger = get_logger("supportflow.ai.llm")


def estimate_tokens(text: str) -> int:
    """Heuristic token estimation (~4 characters per token). Always marked as is_estimated=True."""
    if not text:
        return 0
    return max(1, len(text.strip()) // 4)


class LLMAnalyticsService:
    """Centralized service for recording and aggregating LLM calls, token usage, and latencies."""

    def __init__(self, in_memory_capacity: int = 500) -> None:
        self._lock = threading.Lock()
        self._recent_calls: Deque[Dict[str, Any]] = deque(maxlen=in_memory_capacity)

    def record_call(
        self,
        *,
        model: str,
        provider: str = "groq",
        operation: str = "rag_synthesis",
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
        is_estimated: bool = False,
        latency_ms: Optional[int] = None,
        success: bool = True,
        error_type: Optional[str] = None,
        request_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Record an LLM call in-memory and emit a structured log event."""
        req_id = request_id or get_request_id()
        safe_meta = sanitize_log_data(metadata or {})

        # Compute total_tokens if prompt and completion are present
        if total_tokens is None and prompt_tokens is not None and completion_tokens is not None:
            total_tokens = prompt_tokens + completion_tokens

        record_data = {
            "request_id": req_id,
            "provider": provider,
            "model": model,
            "operation": operation,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "is_estimated": is_estimated,
            "latency_ms": latency_ms,
            "success": success,
            "error_type": error_type,
            "metadata": safe_meta,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        with self._lock:
            self._recent_calls.append(record_data)

        logger.info(
            f"LLM Call: {provider}/{model} [{operation}] - {total_tokens or 0} tokens ({latency_ms or 0}ms)",
            extra={
                "event": "llm_call",
                "request_id": req_id,
                "provider": provider,
                "model": model,
                "operation": operation,
                "tokens": {
                    "prompt": prompt_tokens,
                    "completion": completion_tokens,
                    "total": total_tokens,
                    "is_estimated": is_estimated,
                },
                "latency_ms": latency_ms,
                "success": success,
                "error_type": error_type,
                "metadata": safe_meta,
            },
        )

        return record_data

    async def persist_call(
        self,
        db: AsyncSession,
        *,
        model: str,
        provider: str = "groq",
        operation: str = "rag_synthesis",
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
        is_estimated: bool = False,
        latency_ms: Optional[int] = None,
        success: bool = True,
        error_type: Optional[str] = None,
        request_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> LLMAnalyticsRecord:
        """Record an LLM call in memory and persist it to PostgreSQL."""
        record_data = self.record_call(
            model=model,
            provider=provider,
            operation=operation,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            is_estimated=is_estimated,
            latency_ms=latency_ms,
            success=success,
            error_type=error_type,
            request_id=request_id,
            metadata=metadata,
        )

        db_record = LLMAnalyticsRecord(
            request_id=record_data["request_id"],
            provider=record_data["provider"],
            model=record_data["model"],
            operation=record_data["operation"],
            prompt_tokens=record_data["prompt_tokens"],
            completion_tokens=record_data["completion_tokens"],
            total_tokens=record_data["total_tokens"],
            is_estimated=record_data["is_estimated"],
            latency_ms=record_data["latency_ms"],
            success=record_data["success"],
            error_type=record_data["error_type"],
            metadata_json=record_data["metadata"],
        )
        db.add(db_record)
        return db_record

    def get_in_memory_recent_calls(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve recent in-memory recorded LLM calls."""
        with self._lock:
            calls = list(self._recent_calls)
            return list(reversed(calls[-limit:]))

    def get_in_memory_summary(self) -> Dict[str, Any]:
        """Aggregate in-memory metrics for fast health and dashboard overviews."""
        with self._lock:
            calls = list(self._recent_calls)

        total_calls = len(calls)
        if total_calls == 0:
            return {
                "total_calls": 0,
                "total_tokens": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "avg_latency_ms": 0.0,
                "p50_latency_ms": 0.0,
                "p95_latency_ms": 0.0,
                "success_count": 0,
                "failure_count": 0,
                "error_rate": 0.0,
                "models": {},
            }

        total_tokens = sum(c.get("total_tokens") or 0 for c in calls)
        prompt_tokens = sum(c.get("prompt_tokens") or 0 for c in calls)
        completion_tokens = sum(c.get("completion_tokens") or 0 for c in calls)
        latencies = sorted([c["latency_ms"] for c in calls if c.get("latency_ms") is not None])
        avg_latency = round(sum(latencies) / len(latencies), 2) if latencies else 0.0

        p50 = latencies[int(len(latencies) * 0.5)] if latencies else 0.0
        p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0.0

        successes = sum(1 for c in calls if c.get("success", True))
        failures = total_calls - successes
        error_rate = round(failures / total_calls, 4)

        # Model breakdown
        models: Dict[str, Dict[str, Any]] = {}
        for c in calls:
            m_name = c["model"]
            if m_name not in models:
                models[m_name] = {"calls": 0, "tokens": 0, "total_ms": 0}
            models[m_name]["calls"] += 1
            models[m_name]["tokens"] += c.get("total_tokens") or 0
            models[m_name]["total_ms"] += c.get("latency_ms") or 0

        for m_name, data in models.items():
            data["avg_latency_ms"] = round(data["total_ms"] / data["calls"], 2) if data["calls"] > 0 else 0

        return {
            "total_calls": total_calls,
            "total_tokens": total_tokens,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "avg_latency_ms": avg_latency,
            "p50_latency_ms": p50,
            "p95_latency_ms": p95,
            "success_count": successes,
            "failure_count": failures,
            "error_rate": error_rate,
            "models": models,
        }

    async def get_db_summary(
        self,
        db: AsyncSession,
        period: Optional[str] = "24h",
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Aggregate durable analytics directly from PostgreSQL with time filtering."""
        now = datetime.now(timezone.utc)
        if not end_time:
            end_time = now

        if not start_time:
            if period == "7d":
                start_time = now - timedelta(days=7)
            elif period == "30d":
                start_time = now - timedelta(days=30)
            elif period == "1h":
                start_time = now - timedelta(hours=1)
            else:  # default 24h
                start_time = now - timedelta(hours=24)

        # Query total calls, tokens, latency
        base_filter = [
            LLMAnalyticsRecord.created_at >= start_time,
            LLMAnalyticsRecord.created_at <= end_time,
        ]

        totals_q = await db.execute(
            select(
                func.count(LLMAnalyticsRecord.id),
                func.coalesce(func.sum(LLMAnalyticsRecord.prompt_tokens), 0),
                func.coalesce(func.sum(LLMAnalyticsRecord.completion_tokens), 0),
                func.coalesce(func.sum(LLMAnalyticsRecord.total_tokens), 0),
                func.coalesce(func.avg(LLMAnalyticsRecord.latency_ms), 0.0),
            ).where(*base_filter)
        )
        t_row = totals_q.one()
        total_calls = t_row[0] or 0
        prompt_tokens = int(t_row[1] or 0)
        completion_tokens = int(t_row[2] or 0)
        total_tokens = int(t_row[3] or 0)
        avg_latency = round(float(t_row[4] or 0.0), 2)

        # Success vs Failure counts
        failures_q = await db.execute(
            select(func.count(LLMAnalyticsRecord.id)).where(
                *base_filter, LLMAnalyticsRecord.success == False  # noqa: E712
            )
        )
        failure_count = failures_q.scalar_one() or 0
        success_count = total_calls - failure_count
        error_rate = round(failure_count / total_calls, 4) if total_calls > 0 else 0.0

        # Model breakdown
        model_q = await db.execute(
            select(
                LLMAnalyticsRecord.model,
                func.count(LLMAnalyticsRecord.id),
                func.coalesce(func.sum(LLMAnalyticsRecord.total_tokens), 0),
                func.coalesce(func.avg(LLMAnalyticsRecord.latency_ms), 0.0),
            )
            .where(*base_filter)
            .group_by(LLMAnalyticsRecord.model)
        )
        models_dict: Dict[str, Dict[str, Any]] = {
            row[0]: {
                "calls": row[1],
                "tokens": int(row[2]),
                "avg_latency_ms": round(float(row[3]), 2),
            }
            for row in model_q.all()
        }

        # Operation breakdown
        op_q = await db.execute(
            select(
                LLMAnalyticsRecord.operation,
                func.count(LLMAnalyticsRecord.id),
                func.coalesce(func.sum(LLMAnalyticsRecord.total_tokens), 0),
            )
            .where(*base_filter)
            .group_by(LLMAnalyticsRecord.operation)
        )
        operations_dict: Dict[str, Dict[str, Any]] = {
            row[0]: {
                "calls": row[1],
                "tokens": int(row[2]),
            }
            for row in op_q.all()
        }

        # Fetch recent records
        recent_q = await db.execute(
            select(LLMAnalyticsRecord)
            .where(*base_filter)
            .order_by(LLMAnalyticsRecord.created_at.desc())
            .limit(20)
        )
        recent_records = [
            {
                "id": str(r.id),
                "request_id": r.request_id,
                "provider": r.provider,
                "model": r.model,
                "operation": r.operation,
                "prompt_tokens": r.prompt_tokens,
                "completion_tokens": r.completion_tokens,
                "total_tokens": r.total_tokens,
                "is_estimated": r.is_estimated,
                "latency_ms": r.latency_ms,
                "success": r.success,
                "error_type": r.error_type,
                "created_at": r.created_at.isoformat(),
            }
            for r in recent_q.scalars().all()
        ]

        return {
            "period": {
                "start": start_time.isoformat(),
                "end": end_time.isoformat(),
                "label": period or "custom",
            },
            "total_calls": total_calls,
            "success_count": success_count,
            "failure_count": failure_count,
            "error_rate": error_rate,
            "tokens": {
                "prompt": prompt_tokens,
                "completion": completion_tokens,
                "total": total_tokens,
            },
            "avg_latency_ms": avg_latency,
            "models": models_dict,
            "operations": operations_dict,
            "recent_records": recent_records,
        }

    def clear(self) -> None:
        """Clear in-memory buffer."""
        with self._lock:
            self._recent_calls.clear()


# Global singleton LLM analytics service
llm_analytics_service = LLMAnalyticsService()
