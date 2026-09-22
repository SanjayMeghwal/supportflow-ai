# ADR-002: Asynchronous Data Access with SQLAlchemy 2.0 and Asyncpg

## Status
Accepted

## Context
SupportFlow AI uses FastAPI, an asynchronous ASGI framework designed for high-concurrency I/O operations (streaming LLM tokens, concurrent ticket polling, background triage tasks).
Using synchronous database drivers (e.g., `psycopg2`) blocks the event loop unless run in a separate thread pool, creating throughput bottlenecks.

## Decision
We adopt **SQLAlchemy 2.0 declarative models with `asyncpg`** (`postgresql+asyncpg://`) as the primary database interface, paired with async session lifecycle management (`AsyncSessionLocal`, `expire_on_commit=False`).

## Consequences & Trade-offs
### Positive
- **Non-blocking Event Loop:** Database queries execute concurrently with LLM requests and Redis operations without tying up worker threads.
- **Modern 2.0 Syntax:** Pure type-annotated mapped columns (`Mapped[...] = mapped_column(...)`) eliminate legacy SQLAlchemy 1.x type ambiguity.
- **Fast Driver:** `asyncpg` is significantly faster than standard DBAPI drivers due to binary protocol encoding.

### Negative / Mitigations
- **Lazy Loading Pitfall:** Accessing unloaded relationship attributes outside an explicit query raises `MissingGreenlet` errors.
- *Mitigation:* Explicit eager loading (`selectinload`, `joinedload`) in service/repository layers, and `expire_on_commit=False` on the session factory to prevent silent background reload triggers.
