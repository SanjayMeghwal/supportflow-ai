"""Production-safe rate limiting engine for SupportFlow AI.

Supports:
- Redis-backed distributed sliding window counter when Redis is reachable.
- Graceful in-memory sliding window fallback if Redis is unavailable or unconfigured.
- Distinct rate limit categories: auth, ai, upload, and general default.
- Informative and safe HTTP headers: X-RateLimit-Limit, X-RateLimit-Remaining, Retry-After.
- Emits security audit events on rate limit violations without leaking secrets.
"""

from collections import defaultdict
import threading
import time
from typing import Optional, Tuple
from fastapi import HTTPException, Request, Response, status
import redis.asyncio as aioredis

from backend.app.core.config import settings
from backend.app.core.logging import get_logger, log_security_event
from backend.app.core.request_context import get_request_id

logger = get_logger("supportflow.rate_limit")


class InMemorySlidingWindow:
    """Thread-safe in-memory sliding window rate limiter fallback."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str, limit: int, window_seconds: int = 60) -> Tuple[bool, int, int]:
        """Check if request is allowed within the sliding window.

        Returns:
            Tuple[bool, int, int]: (is_allowed, remaining, retry_after)
        """
        now = time.time()
        cutoff = now - window_seconds

        with self._lock:
            # Purge timestamps outside the current window
            valid_hits = [ts for ts in self._hits[key] if ts > cutoff]
            self._hits[key] = valid_hits

            current_count = len(valid_hits)
            if current_count >= limit:
                # Oldest hit timestamp determines retry_after
                oldest = valid_hits[0]
                retry_after = max(1, int(oldest + window_seconds - now))
                return False, 0, retry_after

            # Record this hit
            self._hits[key].append(now)
            remaining = max(0, limit - (current_count + 1))
            return True, remaining, 0

    def reset(self) -> None:
        """Clear all in-memory rate limit records (useful in tests)."""
        with self._lock:
            self._hits.clear()


class RateLimiter:
    """Production rate limiter with Redis backend and in-memory fallback."""

    def __init__(self) -> None:
        self._memory_limiter = InMemorySlidingWindow()
        self._redis_client: Optional[aioredis.Redis] = None
        self._redis_failed = False

    def _get_redis(self) -> Optional[aioredis.Redis]:
        if not settings.REDIS_URL or self._redis_failed:
            return None
        if self._redis_client is None:
            try:
                self._redis_client = aioredis.from_url(
                    settings.REDIS_URL,
                    decode_responses=True,
                    socket_connect_timeout=1.0,
                    socket_timeout=1.0,
                )
            except Exception as exc:
                logger.warning(
                    f"Unable to connect to Redis at {settings.REDIS_URL}: {exc}. "
                    "Using in-memory rate limiting fallback."
                )
                self._redis_failed = True
                return None
        return self._redis_client

    async def check(
        self,
        key: str,
        limit: int,
        window_seconds: int = 60,
    ) -> Tuple[bool, int, int]:
        """Check rate limit for the given key.

        Returns:
            (is_allowed, remaining, retry_after)
        """
        if not settings.RATE_LIMIT_ENABLED:
            return True, limit, 0

        redis_client = self._get_redis()
        if redis_client is not None:
            try:
                now = time.time()
                pipeline = redis_client.pipeline()
                redis_key = f"rate_limit:{key}"
                # Remove timestamps older than window
                pipeline.zremrangebyscore(redis_key, 0, now - window_seconds)
                # Count remaining items in window
                pipeline.zcard(redis_key)
                # Add current request
                pipeline.zadd(redis_key, {str(now): now})
                # Set TTL on set
                pipeline.expire(redis_key, window_seconds + 5)
                results = await pipeline.execute()

                current_count = results[1]
                if current_count >= limit:
                    # Fetch oldest timestamp to compute retry_after
                    oldest = await redis_client.zrange(redis_key, 0, 0, withscores=True)
                    if oldest:
                        retry_after = max(1, int(oldest[0][1] + window_seconds - now))
                    else:
                        retry_after = window_seconds
                    return False, 0, retry_after

                remaining = max(0, limit - (current_count + 1))
                return True, remaining, 0
            except Exception as exc:
                logger.warning(
                    f"Redis rate limiting failed ({exc}). Falling back to in-memory limiter."
                )
                # Graceful degradation: do not fail request, use in-memory limiter
                return self._memory_limiter.check(key, limit, window_seconds)

        return self._memory_limiter.check(key, limit, window_seconds)

    def reset_memory(self) -> None:
        """Reset in-memory rate limit records."""
        self._memory_limiter.reset()


# Global rate limiter instance
limiter = RateLimiter()


def get_client_ip(request: Request) -> str:
    """Extract client IP address respecting reverse proxies safely."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # Take the leftmost IP (original client)
        client_ip = forwarded.split(",")[0].strip()
        if client_ip:
            return client_ip
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"


def get_rate_limit_for_category(category: str) -> int:
    """Retrieve the configured rate limit ceiling for a category."""
    if category == "auth":
        return settings.RATE_LIMIT_AUTH
    elif category == "ai":
        return settings.RATE_LIMIT_AI
    elif category == "upload":
        return settings.RATE_LIMIT_UPLOAD
    return settings.RATE_LIMIT_DEFAULT


class RateLimitDependency:
    """FastAPI route dependency that enforces rate limits per category."""

    def __init__(self, category: str = "default", limit: Optional[int] = None) -> None:
        self.category = category
        self.explicit_limit = limit

    async def __call__(self, request: Request, response: Response) -> None:
        if not settings.RATE_LIMIT_ENABLED:
            return

        limit = self.explicit_limit or get_rate_limit_for_category(self.category)
        client_ip = get_client_ip(request)

        # Prefer user ID if authenticated or in state, otherwise client IP
        user_id = getattr(request.state, "user_id", None)
        key = f"{self.category}:{user_id if user_id else client_ip}"

        allowed, remaining, retry_after = await limiter.check(key, limit, window_seconds=60)

        # Inject rate limit headers into response
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)

        if not allowed:
            response.headers["Retry-After"] = str(retry_after)
            log_security_event(
                "rate_limit_exceeded",
                request_id=get_request_id(),
                user_id=str(user_id) if user_id else None,
                details={
                    "category": self.category,
                    "key": key,
                    "client_ip": client_ip,
                    "limit": limit,
                    "retry_after": retry_after,
                    "path": request.url.path,
                    "method": request.method,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Try again in {retry_after} seconds.",
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                },
            )


# Pre-built dependencies for easy route decoration
rate_limit_default = RateLimitDependency(category="default")
rate_limit_auth = RateLimitDependency(category="auth")
rate_limit_ai = RateLimitDependency(category="ai")
rate_limit_upload = RateLimitDependency(category="upload")
