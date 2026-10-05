# Authentication & Authorization — Detailed Architecture

> Companion document to [architecture.md](../architecture.md)  
> Source: `backend/app/core/security.py`, `backend/app/api/deps.py`

---

## Authentication Flow

```
POST /api/v1/auth/login
  │
  ├─ Lookup User by email → 401 if not found
  ├─ verify_password(plain, hashed) → bcrypt.checkpw → 401 if mismatch
  ├─ Check user.is_active → 401 if inactive
  ├─ create_access_token(user_id, ..., expires_minutes=60)
  └─ create_refresh_token(user_id, ..., expires_days=7)
       → { access_token, refresh_token, token_type: "bearer" }
```

---

## JWT Token Claims

Access tokens contain **only**:

```json
{
  "sub": "<user-uuid>",
  "type": "access",
  "iat": <unix-timestamp>,
  "exp": <unix-timestamp>
}
```

**Role, email, and all other user attributes are intentionally excluded** from token claims.  
Authorization always reads from the database — a compromised token cannot forge a role escalation.

---

## `get_current_user` Dependency

Used on every authenticated route via `Depends(get_current_user)`:

```
1. Extract Bearer token from Authorization header
        → HTTPBearer raises 401 automatically if missing/malformed

2. decode_access_token(token)
        → Verifies HS256 signature, expiry, and type == "access"
        → Returns user_id string or None

3. Parse UUID from user_id string
        → Guards against malformed sub claims

4. SELECT user FROM db WHERE id == user_id
        → Database is authoritative; returns None if user deleted since token issue

5. Check user.is_active == True
        → 401 if account deactivated
```

All failure modes return `HTTP 401` with `{"detail": "Could not validate credentials."}` — **no information leakage about which check failed**.

Security events are logged to structured audit log at each failure point.

---

## `require_roles` Dependency Factory

```python
def require_roles(*roles: UserRole) -> Callable:
    """Returns a FastAPI dependency that enforces role membership."""
```

Usage on routes:
```python
@router.get("/admin-endpoint")
async def admin_view(
    current_user: User = Depends(require_roles(UserRole.ADMIN))
): ...
```

Pre-built aliases:
```python
require_admin         = require_roles(UserRole.ADMIN)
require_support_agent = require_roles(UserRole.SUPPORT_AGENT, UserRole.ADMIN)
require_customer      = require_roles(UserRole.CUSTOMER)
```

---

## IDOR Prevention Pattern

`verify_resource_ownership()` is called in every endpoint that accesses customer-scoped resources:

```python
# ADMIN / SUPPORT_AGENT: always allowed
if current_user.role in (UserRole.ADMIN, UserRole.SUPPORT_AGENT):
    return True

# CUSTOMER: resolve DB customer_id from authenticated user
authenticated_customer_id = await db.execute(
    select(Customer.id).where(Customer.user_id == current_user.id)
)

# If customer_id in URL != authenticated customer's ID → 403
if authenticated_customer_id != resource_customer_id:
    log_security_event("cross_tenant_access_attempt", ...)
    raise HTTPException(403, "Access forbidden: you do not own this resource.")
```

**Key invariant:** A UUID in a URL path is an identifier — not an access token.  
Possession of another customer's UUID grants zero authorization.

---

## Password Security

| Property | Implementation |
|---|---|
| Algorithm | bcrypt |
| Salt | Per-hash salt (bcrypt.gensalt()) |
| Cost factor | bcrypt default (12 rounds) |
| Storage | Only bcrypt hash stored; plaintext never persisted |
| Comparison | `bcrypt.checkpw()` (constant-time) |

---

## Security Audit Logging

`log_security_event(event_type, request_id, user_id, details)` emits structured JSON logs for:

| Event | Trigger |
|---|---|
| `authentication_failure` | Invalid/expired token, user not in DB, inactive account |
| `authorization_denied` | Role check failed |
| `cross_tenant_access_attempt` | CUSTOMER accessing another customer's resource |
