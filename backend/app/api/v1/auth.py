"""Authentication router: register, login, and current-user endpoints.

Endpoints:
  POST /api/v1/auth/register  — create a new CUSTOMER account
  POST /api/v1/auth/login     — authenticate and receive an access token and user profile
  GET  /api/v1/auth/me        — return the authenticated user's profile

Design decisions:
  - Registration is open for CUSTOMER accounts. SUPPORT_AGENT and ADMIN
    accounts are created by admins only (not implemented in this phase).
  - Login deliberately uses a generic error message to avoid leaking whether
    an email address exists in the system.
  - On success, login returns access_token, token_type ("bearer"), and the safe user profile.
  - Password is never returned, logged, or included in any response.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.deps import get_current_user
from backend.app.core.config import settings
from backend.app.core.database import get_db
from backend.app.core.security import create_access_token, hash_password, verify_password
from backend.app.models.user import Customer, User, UserRole
from backend.app.schemas.auth import (
    LoginRequest,
    MeResponse,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter()


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new customer account",
    responses={
        409: {"description": "Email address already registered"},
        422: {"description": "Validation error"},
    },
)
async def register(
    payload: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Register a new CUSTOMER user account.

    - Email is normalized (lowercased) before storage.
    - Password is hashed with bcrypt — plaintext is never persisted.
    - A Customer profile row is automatically created alongside the User.
    - Returns the created user (without any password information).
    """
    # Check for duplicate email — use a separate query to return a clean 409
    existing = await db.execute(
        select(User).where(User.email == payload.email)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email address already exists.",
        )

    # Hash the password before any persistence
    hashed = hash_password(payload.password)

    # Create the User row
    user = User(
        email=payload.email,
        hashed_password=hashed,
        role=UserRole.CUSTOMER,
        is_active=True,
    )
    db.add(user)
    await db.flush()  # Flush to get the generated user.id before creating Customer

    # Create the linked Customer profile
    customer = Customer(
        user_id=user.id,
        full_name=payload.full_name,
    )
    db.add(customer)
    await db.flush()
    await db.refresh(user)

    return UserResponse(
        id=user.id,
        email=user.email,
        role=user.role.value,
        is_active=user.is_active,
        created_at=user.created_at,
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Authenticate and receive an access token",
    responses={
        401: {"description": "Invalid credentials or inactive account"},
    },
)
async def login(
    payload: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Authenticate with email and password, returning a JWT access token.

    Security note: The error message is deliberately generic ('Invalid
    credentials') regardless of whether the email exists or the password is
    wrong. This avoids leaking account existence information.

    Inactive accounts receive the same generic error rather than a specific
    message that would confirm the email exists.
    """
    _invalid_credentials = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Fetch user by email
    result = await db.execute(
        select(User).where(User.email == payload.email)
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise _invalid_credentials

    # Verify password against stored hash
    if not verify_password(payload.password, user.hashed_password):
        raise _invalid_credentials

    # Reject inactive accounts after credential verification
    # (same error to avoid confirming account existence to a bad actor
    # who somehow obtained correct credentials)
    if not user.is_active:
        raise _invalid_credentials

    access_token = create_access_token(
        user_id=str(user.id),
        secret_key=settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
        expires_minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES,
    )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user=UserResponse(
            id=user.id,
            email=user.email,
            role=user.role.value,
            is_active=user.is_active,
            created_at=user.created_at,
        ),
    )


@router.get(
    "/me",
    response_model=MeResponse,
    summary="Get authenticated user profile",
    responses={
        401: {"description": "Missing or invalid authentication token"},
    },
)
async def me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MeResponse:
    """Return the profile of the currently authenticated user.

    For CUSTOMER accounts, the full_name from the linked Customer profile
    is included. For SUPPORT_AGENT / ADMIN there is no customer profile,
    so full_name will be None.
    """
    # Eagerly load customer profile if present
    result = await db.execute(
        select(User)
        .options(selectinload(User.customer_profile))
        .where(User.id == current_user.id)
    )
    user_with_profile = result.scalar_one()

    full_name: str | None = None
    if user_with_profile.customer_profile is not None:
        full_name = user_with_profile.customer_profile.full_name

    return MeResponse(
        id=user_with_profile.id,
        email=user_with_profile.email,
        role=user_with_profile.role.value,
        is_active=user_with_profile.is_active,
        created_at=user_with_profile.created_at,
        full_name=full_name,
    )


