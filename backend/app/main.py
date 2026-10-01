from contextlib import asynccontextmanager
import logging
from typing import AsyncGenerator
from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from backend.app.api.v1.api import api_router
from backend.app.core.config import settings
from backend.app.core.database import engine
from backend.app.core.logging import get_logger, setup_structured_logging
from backend.app.core.middleware import ObservabilityMiddleware, SecurityHeadersMiddleware
from backend.app.core.rate_limit import limiter
from backend.app.core.request_context import get_request_id
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = get_logger("supportflow.server")

# Initialize structured JSON logging
setup_structured_logging(log_level=logging.DEBUG if settings.DEBUG else logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager for startup and shutdown hooks."""
    # Startup verification
    print(f"Starting {settings.APP_NAME} in [{settings.APP_ENV}] mode...")
    yield
    # Graceful shutdown: dispose database connection pool and close Redis connection
    print(f"Shutting down {settings.APP_NAME}...")
    await engine.dispose()
    await limiter.close()


app = FastAPI(
    title=settings.APP_NAME,
    description="Production-oriented AI customer-support and operations platform.",
    version="0.1.0",
    docs_url="/docs" if settings.ENABLE_DOCS else None,
    redoc_url="/redoc" if settings.ENABLE_DOCS else None,
    openapi_url=f"{settings.API_V1_STR}/openapi.json" if settings.ENABLE_DOCS else None,
    lifespan=lifespan,
)

# 1. Observability Middleware (Request IDs, Latency Telemetry, Metrics)
app.add_middleware(ObservabilityMiddleware)

# 2. Security Headers & Request Payload Size Middleware
app.add_middleware(SecurityHeadersMiddleware)

# 3. Hardened CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Safe unhandled exception handler preventing stack trace or internal leakage."""
    req_id = get_request_id() or "unknown"
    logger.error(
        f"Unhandled server error on {request.method} {request.url.path}: {exc}",
        extra={
            "event": "unhandled_exception",
            "request_id": req_id,
            "route": request.url.path,
            "method": request.method,
            "error_type": exc.__class__.__name__,
        },
        exc_info=True,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Internal server error. Please contact support with the request ID.",
            "request_id": req_id,
        },
    )


# Centralized API v1 Router
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/", tags=["General"])
async def root():
    """Root metadata endpoint."""
    return {
        "app": settings.APP_NAME,
        "version": "0.1.0",
        "status": "online",
        "docs": "/docs",
    }


@app.get("/health/live", tags=["Monitoring"], status_code=status.HTTP_200_OK)
async def health_liveness():
    """Liveness probe validating application process is responsive."""
    return {"status": "live"}


@app.get("/health/ready", tags=["Monitoring"])
async def health_readiness(response: Response):
    """Readiness probe validating operational dependencies (PostgreSQL + Redis)."""
    db_healthy = False
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            db_healthy = True
    except Exception as exc:
        logger.warning(f"Readiness probe: database connection check failed: {exc}")

    redis_healthy = True
    if settings.REDIS_URL:
        try:
            r = limiter._get_redis()
            if r is not None:
                await r.ping()
            elif limiter._redis_failed:
                redis_healthy = False
        except Exception as exc:
            logger.warning(f"Readiness probe: Redis connection check failed: {exc}")
            redis_healthy = False

    is_ready = db_healthy and redis_healthy
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ready" if is_ready else "not_ready",
        "database": "healthy" if db_healthy else "unhealthy",
        "redis": "healthy" if redis_healthy else "unhealthy",
    }


@app.get("/health", tags=["Monitoring"], status_code=status.HTTP_200_OK)
async def health_check():
    """General health check validating application runtime and database connectivity."""
    db_status = "unhealthy"
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            db_status = "healthy"
    except Exception as exc:
        logger.warning(f"Health check: database unreachable: {exc}")
        db_status = "unhealthy"

    return {
        "status": "healthy" if db_status == "healthy" else "degraded",
        "database": db_status,
        "environment": settings.APP_ENV,
    }
