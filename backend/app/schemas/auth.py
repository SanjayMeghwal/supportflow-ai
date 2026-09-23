"""Pydantic schemas for authentication and user representation.

Design principles:
- Request schemas validate and normalize input (email lowercased).
- Response schemas never include hashed_password or internal fields.
- SQLAlchemy models are never directly used as API response models.
"""

import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field, field_validator


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    """Payload for POST /auth/register.

    Email is automatically lowercased and stripped.
    Password must be at least 8 characters.
    full_name is required for CUSTOMER role and optional otherwise.
    """

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("full_name", mode="before")
    @classmethod
    def strip_full_name(cls, v: str) -> str:
        return v.strip()


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    """Payload for POST /auth/login."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()


# ---------------------------------------------------------------------------
# User representation (safe — no password fields)
# ---------------------------------------------------------------------------


class UserResponse(BaseModel):
    """Safe public representation of an authenticated user.

    hashed_password is explicitly excluded.
    role is included because the frontend needs it to render the correct UI.
    The role claim in this response is informational only; all authorization
    decisions are made from the database record, not from client-supplied data.
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    email: str
    role: str
    is_active: bool
    created_at: datetime


# ---------------------------------------------------------------------------
# Token
# ---------------------------------------------------------------------------


class TokenResponse(BaseModel):
    """Response body for a successful login."""

    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class MeResponse(BaseModel):
    """Response for GET /auth/me — includes user and optional customer profile."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    email: str
    role: str
    is_active: bool
    created_at: datetime
    full_name: Optional[str] = None
