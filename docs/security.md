# SupportFlow AI — Security Architecture & Production Hardening Guide (Phase 18)

This document specifies the security controls, invariants, threat model defenses, and architectural protections implemented in SupportFlow AI to safeguard operations, identities, knowledge documents, and AI agent execution.

---

## 1. Authentication

* **Mechanism**: Bearer JWT authentication enforced via FastAPI dependency injection (`get_current_user`).
* **Validation Pipeline**:
  1. Header format validation (`Authorization: Bearer <token>`).
  2. Cryptographic signature verification using HMAC-SHA256 with environment-configured secret (`JWT_SECRET_KEY`).
  3. Token type assertion (`type == 'access'`).
  4. Expiration check (`exp` claim must be in the future).
  5. Authoritative database lookup for user presence and active status (`is_active == True`).
* **Security Controls**:
  - Inactive or deleted accounts are immediately rejected with 401 Unauthorized, invalidating existing sessions.
  - Authentication failure responses return uniform generic messages (`Invalid credentials.`) to prevent account/email enumeration.

---

## 2. Authorization & RBAC

* **Role-Based Access Control**:
  - `CUSTOMER`: Limited strictly to viewing and creating their own tickets, viewing their customer profile, and conversing in their support threads. Cannot access internal notes, agent assignment, knowledge ingestion, or system observability.
  - `SUPPORT_AGENT`: Operational role authorized to view tickets, update ticket statuses, add agent messages, inspect the knowledge base, ingest documents, and view LLM telemetry.
  - `ADMIN`: Superuser role authorized for all agent capabilities plus user administration, system configuration, and full operational observability.
* **Enforcement Layer**:
  - Enforced deterministically in backend route dependencies (`require_customer`, `require_support_agent`, `require_admin`).
  - Roles are read authoritatively from the database record during request execution—never trusted from client-controlled JWT claims.

---

## 3. Tenant & Customer Isolation (IDOR Protection)

* **Resource Scoping**:
  - Every customer-facing resource (ticket, message, order, review) is bound to an authoritative `customer_id`.
  - In `verify_resource_ownership(resource_customer_id, current_user, db)`:
    - Customer users can only access records where `resource_customer_id == user.customer_profile.id`.
    - Passing a foreign UUID in request URLs or payloads results in an immediate 403 Forbidden with security audit logging (`cross_tenant_access_attempt`).
  - Ticket query filters in `GET /api/v1/tickets` automatically scope result sets to the authenticated customer ID when accessed by customer tokens.

---

## 4. JWT Hardening

* **Algorithm Pinning**: Explicitly pinned to `HS256`. Requests signed with `none` or mismatched asymmetric algorithms are rejected.
* **Claim Minimization**: Token payloads contain only `sub` (user UUID), `type` ("access"), `iat`, and `exp`. Roles, permissions, and email addresses are intentionally excluded from the payload to prevent stale authorization claims.
* **Token Lifetime**: Short-lived access tokens (default 60 minutes) configurable via `ACCESS_TOKEN_EXPIRE_MINUTES`.

---

## 5. Password Security & Hashing

* **Algorithm**: Direct `bcrypt` with unique per-password salt generation (`bcrypt.gensalt()`).
* **Storage Invariant**: Plaintext passwords are never persisted to disk, printed to console, or written to logs.
* **Response Masking**: Passwords and hashed passwords are excluded from all Pydantic response schemas (`UserResponse`, `MeResponse`).

---

## 6. API Rate Limiting

* **Architecture**: Distributed sliding-window rate limiter powered by Redis (`aioredis`) with thread-safe in-memory sliding-window fallback if Redis is temporarily unreachable.
* **Rate Limit Tiers (Per Minute)**:
  - **Auth (`/auth/login`, `/auth/register`)**: 10 req/min (protects against credential stuffing and brute force).
  - **AI / RAG (`/knowledge/search`, `/rag/ask`)**: 20 req/min (protects LLM inference budgets and compute resources).
  - **Upload (`/knowledge/upload`, `/knowledge/raw`, `/knowledge/faq`)**: 10 req/min (protects disk storage and document chunking pipeline).
  - **General Default**: 100 req/min.
* **Headers Injected**:
  - `X-RateLimit-Limit`: Maximum allowable requests in the 60s window.
  - `X-RateLimit-Remaining`: Remaining request capacity.
  - `Retry-After`: Seconds until quota replenishment (returned on 429 Too Many Requests).
* **Failure Mode**: Graceful degradation—if Redis connectivity fails, the in-memory limiter continues protection without dropping requests.

---

## 7. File Upload Security & Path Traversal Prevention

* **Filename Sanitization**:
  - Strips leading/trailing directory paths (`../`, `..\`, `/`), null bytes (`\x00`), and control characters using `sanitize_filename`.
  - Enforces server-side controlled document naming and unique UUID primary keys.
* **Extension & Executable Blocking**:
  - Strict extension allowlist: `.pdf`, `.md`, `.markdown`, `.txt`, `.text`, `.json`.
  - Dangerous extensions (`.exe`, `.sh`, `.bat`, `.cmd`, `.py`, `.js`, `.html`, `.php`, etc.) and compound disguises (`.pdf.exe`) are rejected with 400 Bad Request.
* **MIME Type Validation**: Rejects dangerous MIME types (`application/x-msdownload`, `text/html`, `application/javascript`).
* **Magic Byte Content Inspection**:
  - PDF uploads must start with the `%PDF-` signature byte header.
  - Text and Markdown files are scanned for binary null bytes (`\x00`) to detect disguised binaries.
  - JSON FAQ files must validate through UTF-8 parser and match expected structural schema.
* **Size Bounding**: Max 10MB per file (`MAX_FILE_UPLOAD_SIZE`), enforced prior to extraction.

---

## 8. Request Size Limits & Security Headers

* **Payload Bounding**: `SecurityHeadersMiddleware` validates `Content-Length` headers, rejecting payloads exceeding `MAX_REQUEST_BODY_SIZE` (10MB) with 413 Payload Too Large.
* **HTTP Security Headers Injected**:
  - `X-Content-Type-Options: nosniff` (prevents MIME type sniffing).
  - `X-Frame-Options: DENY` (clickjacking defense).
  - `Referrer-Policy: strict-origin-when-cross-origin`.
  - `Permissions-Policy: geolocation=(), camera=(), microphone=(), payment=()`.
  - `Content-Security-Policy`: Configured to permit local application assets and API routes while preventing unauthorized script execution.
  - `Strict-Transport-Security`: HSTS configurable via `HSTS_ENABLED` for HTTPS production environments.

---

## 9. Secret & Configuration Safety

* **Environment-Driven Configuration**: All credentials (`JWT_SECRET_KEY`, `POSTGRES_PASSWORD`, `GROQ_API_KEY`) are managed via `pydantic-settings` from `.env`.
* **Zero Hard-Coded Secrets**: Source code, Dockerfiles, and git commits contain only safe development placeholders.
* **Frontend Isolation**: Vite frontend only exposes `VITE_API_BASE_URL`. Database credentials and LLM keys are never bundled into client assets.

---

## 10. Security Audit Logging & Masking

* **Structured JSON Logging**: Every log entry emits ISO-8601 timestamps, log level, request correlation ID (`request_id`), and event metadata.
* **Automatic Secret Masking**: Keys matching `password`, `secret`, `token`, `authorization`, `api_key`, `groq_api_key`, and `jwt` are masked (`***MASKED***`) across all log levels.
* **Auditable Security Events (`log_security_event`)**:
  - `auth_login_success`, `auth_login_failure`, `auth_register`
  - `authentication_failure`, `authorization_denied`
  - `cross_tenant_access_attempt`
  - `rate_limit_exceeded`
  - `invalid_upload`, `oversized_upload`
  - `unhandled_exception`

---

## 11. LLM & AI Security (Prompt Injection & Bounded Execution)

* **Retrieval Sandboxing**:
  - Retrieved knowledge chunks are encapsulated in strict tags: `<untrusted_reference_document>...content...</untrusted_reference_document>`.
  - System prompts instruct the LLM that retrieved passages are strictly factual reference documents and must never be interpreted as system instructions or executable commands.
* **Input Length Bounding**: User prompt inputs are bounded to `MAX_AI_INPUT_CHARS` (4000 characters) to prevent token exhaustion and context window overflow attacks.
* **Agent Recursion Limits**: State graph invocation specifies `config={"recursion_limit": 15}` to guarantee bounded loop termination.
* **Tool Authorization Boundary**:
  - The LLM cannot execute tools directly. Tools are parsed strictly from JSON schemas and dispatched through `ToolRegistry`.
  - Business tools (`get_order_status`, etc.) enforce database-level customer ownership checks before returning data.

---

## 12. Docker & Container Security

* **Non-Root Execution**: Backend container runs as unprivileged user `appuser` (UID 10001, GID 10001).
* **Multi-Stage Builds**: Build-time compilers (`gcc`, `build-essential`) are discarded in builder stage; production runtime image contains only minimal runtime libraries.
* **Health Checks**: Automated internal healthcheck verifies application status without exposing privileged endpoints.

---

## 13. Known Limitations

* **Antivirus Scanning**: In-memory virus scanning (e.g. ClamAV) is not embedded in the backend container; production deployments handling public uploads should route uploads through an external object storage scanning pipeline (e.g. AWS S3 bucket malware scanning).
* **HTTPS Termination**: TLS/SSL termination is expected to take place at the edge reverse proxy or load balancer (Nginx / Cloudflare / AWS ALB).

---

## 14. Verification Summary

| Component | Test Suite | Pass Count | Status |
|---|---|---|---|
| Authentication Hardening | `tests/security/test_auth_hardening.py` | 9 | Verified |
| RBAC & IDOR Scoping | `tests/security/test_rbac_idor.py` | 6 | Verified |
| Rate Limiting Engine | `tests/security/test_rate_limiting.py` | 4 | Verified |
| Upload & Traversal Security | `tests/security/test_upload_security.py` | 5 | Verified |
| Security Headers & Request Limits | `tests/security/test_security_headers.py` | 2 | Verified |
| Error Leakage Sanitization | `tests/security/test_error_handling.py` | 1 | Verified |
| AI Bounded Execution | `tests/security/test_ai_security.py` | 2 | Verified |
| Frontend Test Suite | `npm test` | 43 | Verified |
| Frontend Production Bundle | `npm run build` | Built | Verified |
