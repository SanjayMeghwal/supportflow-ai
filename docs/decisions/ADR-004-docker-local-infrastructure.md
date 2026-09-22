# ADR-004: Containerized Local Infrastructure via Docker Compose

## Status
Accepted

## Context
SupportFlow AI relies on stateful dependencies: PostgreSQL 16 with the compiled C extension `pgvector`, and Redis 7. Installing and managing specific versions of these services natively on Windows/macOS/Linux machines creates environment disparities ("it works on my machine") and port collision risks with other pre-existing projects.

## Decision
We orchestrate local stateful infrastructure through **Docker Compose** (`docker-compose.yml`), mapping:
- PostgreSQL + pgvector to isolated host port `5434` (container internal `5432`).
- Redis to host port `6379`.
Persistent volumes (`supportflow_pgdata`, `supportflow_redisdata`) ensure local data persists across container restarts.

## Consequences & Trade-offs
### Positive
- **Deterministic Environment:** Ensures identical `pgvector` binaries and PostgreSQL 16 configuration across all developer and CI/CD environments.
- **Port Isolation:** Eliminates collisions with existing default PostgreSQL instances running on host port `5432`.
- **Zero Host Pollution:** Avoids manual local service installations and daemon lifecycle management.

### Negative / Mitigations
- Requires Docker Desktop or Docker engine running on the developer's machine.
- *Mitigation:* Documented in quick-start instructions and automated via standard Docker Compose commands.
