import bcrypt
import pytest
from backend.app.core.security import hash_password, verify_password


def test_bcrypt_version_installed():
    """Verify that modern bcrypt library is installed and operational."""
    version = getattr(bcrypt, "__version__", None)
    assert version is not None
    assert int(version.split(".")[0]) >= 4


def test_hash_password_produces_valid_bcrypt_hash():
    """Verify password hashing returns a salted bcrypt hash string."""
    raw_password = "SuperSecretPassword123!"
    hashed = hash_password(raw_password)

    assert hashed != raw_password
    assert hashed.startswith("$2b$") or hashed.startswith("$2a$")
    assert len(hashed) >= 50


def test_verify_password_matches_correct_password():
    """Verify password verification succeeds with correct credentials."""
    raw_password = "SupportFlow#Password2026"
    hashed = hash_password(raw_password)

    assert verify_password(raw_password, hashed) is True


def test_verify_password_rejects_incorrect_password():
    """Verify password verification fails with incorrect credentials."""
    raw_password = "SupportFlow#Password2026"
    hashed = hash_password(raw_password)

    assert verify_password("WrongPassword!", hashed) is False
    assert verify_password("", hashed) is False
    assert verify_password("supportflow#password2026", hashed) is False  # case sensitive


def test_verify_password_handles_corrupt_hash_safely():
    """Verify verify_password gracefully handles corrupt or non-bcrypt strings."""
    assert verify_password("password", "invalid_not_a_hash") is False
    assert verify_password("password", "") is False
