import bcrypt
import pytest
from backend.app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


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


# ---------------------------------------------------------------------------
# JWT Unit Tests
# ---------------------------------------------------------------------------


def test_create_and_decode_access_token_roundtrip():
    """Verify JWT access token creation and decoding roundtrip."""
    secret = "unit-test-secret-key-at-least-32-chars-long"
    user_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

    token = create_access_token(
        user_id=user_id,
        secret_key=secret,
        algorithm="HS256",
        expires_minutes=15,
    )
    assert isinstance(token, str)
    assert len(token.split(".")) == 3

    decoded_sub = decode_access_token(
        token=token,
        secret_key=secret,
        algorithm="HS256",
    )
    assert decoded_sub == user_id


def test_decode_access_token_rejects_wrong_secret():
    """Verify JWT decoding fails when signed with a different secret."""
    user_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    token = create_access_token(
        user_id=user_id,
        secret_key="secret-key-one-which-is-valid-length!!",
        algorithm="HS256",
        expires_minutes=15,
    )
    decoded = decode_access_token(
        token=token,
        secret_key="secret-key-two-which-is-completely-diff!",
        algorithm="HS256",
    )
    assert decoded is None


def test_decode_access_token_rejects_expired_token():
    """Verify expired token produces None upon decode."""
    secret = "unit-test-secret-key-at-least-32-chars-long"
    user_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

    # Create token that expired 5 minutes ago
    expired_token = create_access_token(
        user_id=user_id,
        secret_key=secret,
        algorithm="HS256",
        expires_minutes=-5,
    )
    decoded = decode_access_token(
        token=expired_token,
        secret_key=secret,
        algorithm="HS256",
    )
    assert decoded is None


def test_decode_access_token_rejects_malformed_token():
    """Verify malformed strings return None instead of raising exceptions."""
    secret = "unit-test-secret-key-at-least-32-chars-long"
    assert decode_access_token("not.a.valid.jwt", secret, "HS256") is None
    assert decode_access_token("", secret, "HS256") is None
    assert decode_access_token("gibberish", secret, "HS256") is None