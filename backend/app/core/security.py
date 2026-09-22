"""Security utilities for password hashing and authentication primitives."""

import bcrypt


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
