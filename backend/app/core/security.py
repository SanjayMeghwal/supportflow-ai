"""Security utilities for password hashing and JWT primitives."""

from datetime import datetime, timedelta, timezone
from typing import Optional
import bcrypt
from jose import JWTError, jwt


def hash_password(password: str) -> str:
    """Hash a plaintext password using direct bcrypt.
    
    Args:
        password: Raw plaintext password string.

    Returns:
        Hashed password string formatted with salt and cost factor.
    """
    password_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a stored bcrypt hash.
    
    Args:
        plain_password: Raw plaintext password entered by the user.
        hashed_password: Stored bcrypt hash string.

    Returns:
        True if the password matches the hash, False otherwise.
    """
    try:
        plain_bytes = plain_password.encode("utf-8")
        hashed_bytes = hashed_password.encode("utf-8")
        return bcrypt.checkpw(plain_bytes, hashed_bytes)
    except (ValueError, TypeError):
        return False


def create_access_token(
    user_id: str,
    secret_key: str,
    algorithm: str,
    expires_minutes: int,
) -> str:
    """Create a signed JWT access token.

    The token payload contains only the minimum necessary claims:
      - sub: the user's UUID as a string
      - type: literal "access" to distinguish token type
      - exp: expiration timestamp
      - iat: issued-at timestamp

    IMPORTANT: Role, email, and other user attributes are intentionally
    excluded. Authorization always reads from the database, not from claims.

    Args:
        user_id: The user's UUID (as string).
        secret_key: HMAC signing secret from settings.
        algorithm: JWT algorithm (e.g. HS256).
        expires_minutes: Token lifetime in minutes.

    Returns:
        Signed JWT string.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
    }
    return jwt.encode(payload, secret_key, algorithm=algorithm)


def decode_access_token(
    token: str,
    secret_key: str,
    algorithm: str,
) -> Optional[str]:
    """Decode and validate a JWT access token.

    Returns the user_id (sub claim) if the token is valid and is of
    type 'access'. Returns None for any invalid/expired/malformed token.

    Args:
        token: Raw JWT string from the Authorization header.
        secret_key: HMAC signing secret from settings.
        algorithm: JWT algorithm (e.g. HS256).

    Returns:
        user_id string, or None if the token is invalid.
    """
    try:
        payload = jwt.decode(token, secret_key, algorithms=[algorithm])
        user_id: Optional[str] = payload.get("sub")
        token_type: Optional[str] = payload.get("type")

        # Reject if missing required claims or wrong token type
        if user_id is None or token_type != "access":
            return None

        return user_id
    except JWTError:
        return None
