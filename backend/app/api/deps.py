"""FastAPI dependency injection for authentication and authorization.

Design principles:
- get_current_user() is the single entry point for authenticated routes.
- Role is always read from the database, never from JWT claims.
- require_roles() is a factory that returns a dependency — keeps routes clean.
- Resource ownership enforcement is documented here as a pattern even though
  the full ticket API is not yet implemented.

Security invariants enforced here:
  1. JWT must be a valid, non-expired 'access' type token.
  2. The user_id from the token must exist in the database.
  3. The user must be active (is_active == True).
  4. Role checks use the DB record, not any claim the client could forge.
"""

import uuid
from typing import List
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.core.database import get_db
from backend.app.core.logging import log_security_event
from backend.app.core.request_context import get_request_id
from backend.app.core.security import decode_access_token
from backend.app.models.user import Customer, User, UserRole

# FastAPI's HTTP Bearer extractor — returns 401 automatically if
# the Authorization header is missing or malformed.
_bearer_scheme = HTTPBearer(auto_error=True)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Extract and validate a Bearer JWT, returning the authenticated User.

    Steps:
      1. Extract the raw token from the Authorization header.
      2. Decode & validate the JWT (signature, expiry, type claim).
      3. Parse the user_id from the 'sub' claim.
      4. Fetch the user from the database (database is authoritative).
      5. Verify the account is active.

    Raises:
        HTTPException 401: For any invalid/expired/missing token.
        HTTPException 401: If the user no longer exists in the database.
        HTTPException 401: If the user account is inactive.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token = credentials.credentials
    user_id_str = decode_access_token(
        token=token,
        secret_key=settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )

    if user_id_str is None:
        log_security_event(
            "authentication_failure",
            request_id=get_request_id(),
            details={"reason": "invalid_or_expired_token"},
        )
        raise credentials_exception

    # Parse the UUID — guards against malformed sub claims
    try:
        user_id = uuid.UUID(user_id_str)
    except (ValueError, AttributeError):
        log_security_event(
            "authentication_failure",
            request_id=get_request_id(),
            details={"reason": "malformed_sub_uuid", "sub": user_id_str},
        )
        raise credentials_exception

    # Fetch user from DB — this is the authoritative source for role/is_active
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        log_security_event(
            "authentication_failure",
            request_id=get_request_id(),
            details={"reason": "user_id_not_in_db", "user_id": str(user_id)},
        )
        raise credentials_exception

    if not user.is_active:
        log_security_event(
            "authentication_failure",
            request_id=get_request_id(),
            user_id=str(user.id),
            details={"reason": "inactive_account"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is inactive.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def require_roles(*roles: UserRole):
    """Factory returning a FastAPI dependency that enforces role-based access.

    Usage in a route:
        @router.get("/admin-only")
        async def admin_endpoint(
            current_user: User = Depends(require_roles(UserRole.ADMIN)),
        ): ...

    The role is read from the database record (via get_current_user),
    not from JWT claims.

    Raises:
        HTTPException 403: If the authenticated user's role is not in `roles`.
    """
    allowed = set(roles)

    async def _check(
        current_user: User = Depends(get_current_user),
    ) -> User:
        if current_user.role not in allowed:
            log_security_event(
                "authorization_denied",
                request_id=get_request_id(),
                user_id=str(current_user.id),
                details={
                    "user_role": current_user.role.value,
                    "required_roles": [r.value for r in allowed],
                },
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions.",
            )
        return current_user

    return _check


# ---------------------------------------------------------------------------
# Pre-built role dependencies for convenience
# ---------------------------------------------------------------------------

require_admin = require_roles(UserRole.ADMIN)
require_support_agent = require_roles(UserRole.SUPPORT_AGENT, UserRole.ADMIN)
require_customer = require_roles(UserRole.CUSTOMER)


# ---------------------------------------------------------------------------
# Resource Ownership Scoping Patterns
# ---------------------------------------------------------------------------


async def get_current_customer(
    current_user: User = Depends(require_customer),
    db: AsyncSession = Depends(get_db),
) -> Customer:
    """Retrieve the Customer domain entity linked to the authenticated user.

    Enforces that the authenticated user possesses the CUSTOMER role and
    has an active Customer profile record.
    """
    result = await db.execute(
        select(Customer).where(Customer.user_id == current_user.id)
    )
    customer = result.scalar_one_or_none()
    if customer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer profile not found.",
        )
    return customer


async def verify_resource_ownership(
    resource_customer_id: uuid.UUID,
    current_user: User,
    db: AsyncSession,
) -> bool:
    """Verify that current_user has legitimate access to a customer-owned resource.

    Authorization Invariants:
      1. ADMIN and SUPPORT_AGENT roles possess cross-customer support oversight.
      2. CUSTOMER role can ONLY access resources where the resource's customer_id
         strictly equals the authenticated user's linked customer record.
      3. A foreign customer UUID in a URL never grants access (UUID is an identifier,
         never an authorization token).

    Raises:
        HTTPException 403: If a CUSTOMER attempts to access another customer's resource.
        HTTPException 404: If the customer profile does not exist.
    """
    if current_user.role in (UserRole.ADMIN, UserRole.SUPPORT_AGENT):
        return True

    # For customers, resolve their authoritative customer ID from database
    result = await db.execute(
        select(Customer.id).where(Customer.user_id == current_user.id)
    )
    authenticated_customer_id = result.scalar_one_or_none()

    if authenticated_customer_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer profile not found.",
        )

    if authenticated_customer_id != resource_customer_id:
        log_security_event(
            "cross_tenant_access_attempt",
            request_id=get_request_id(),
            user_id=str(current_user.id),
            details={
                "authenticated_customer_id": str(authenticated_customer_id),
                "attempted_resource_customer_id": str(resource_customer_id),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: you do not own this resource.",
        )

    return True

