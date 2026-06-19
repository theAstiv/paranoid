"""Unit tests for backend.auth.passwords and backend.auth.tokens.

No database access — pure crypto unit tests.
"""

import hashlib
import time

import pytest


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------


def test_hash_password_returns_encoded_string() -> None:
    from backend.auth.passwords import hash_password

    hashed = hash_password("correct-horse-battery-staple")
    assert isinstance(hashed, str)
    assert hashed != "correct-horse-battery-staple"
    assert hashed.startswith("$argon2")


def test_verify_password_correct() -> None:
    from backend.auth.passwords import hash_password, verify_password

    plaintext = "hunter2"
    hashed = hash_password(plaintext)
    assert verify_password(plaintext, hashed) is True


def test_verify_password_wrong() -> None:
    from backend.auth.passwords import hash_password, verify_password

    hashed = hash_password("correct")
    assert verify_password("wrong", hashed) is False


def test_needs_rehash_fresh_hash_is_false() -> None:
    from backend.auth.passwords import hash_password, needs_rehash

    hashed = hash_password("test")
    assert needs_rehash(hashed) is False


# ---------------------------------------------------------------------------
# JWT access tokens
# ---------------------------------------------------------------------------


def test_create_and_decode_access_token() -> None:
    from backend.auth.tokens import create_access_token, decode_access_token

    token = create_access_token("user-abc", "alice", is_admin=False)
    assert isinstance(token, str)

    payload = decode_access_token(token)
    assert payload["sub"] == "user-abc"
    assert payload["username"] == "alice"
    assert payload["is_admin"] is False
    assert "exp" in payload
    assert "jti" in payload


def test_access_token_admin_flag() -> None:
    from backend.auth.tokens import create_access_token, decode_access_token

    token = create_access_token("admin-id", "admin", is_admin=True)
    payload = decode_access_token(token)
    assert payload["is_admin"] is True


def test_decode_expired_access_token_raises() -> None:
    import jwt as pyjwt

    from backend.auth.tokens import _get_jwt_key, decode_access_token

    now = int(time.time())
    payload = {
        "sub": "user-123",
        "username": "alice",
        "is_admin": False,
        "iat": now - 120,
        "exp": now - 60,  # expired 60 s ago
        "jti": "test-jti",
    }
    expired_token = pyjwt.encode(payload, _get_jwt_key(), algorithm="HS256")

    with pytest.raises(pyjwt.ExpiredSignatureError):
        decode_access_token(expired_token)


def test_decode_token_wrong_key_raises() -> None:
    import jwt as pyjwt

    from backend.auth.tokens import decode_access_token

    now = int(time.time())
    payload = {"sub": "x", "iat": now, "exp": now + 900, "jti": "j"}
    bad_token = pyjwt.encode(payload, "wrong-secret", algorithm="HS256")

    with pytest.raises(pyjwt.InvalidSignatureError):
        decode_access_token(bad_token)


# ---------------------------------------------------------------------------
# Refresh tokens
# ---------------------------------------------------------------------------


def test_create_refresh_token_format() -> None:
    from backend.auth.tokens import create_refresh_token, parse_refresh_token_jti

    jti, raw = create_refresh_token()
    assert isinstance(jti, str)
    assert isinstance(raw, str)
    assert ":" in raw

    extracted = parse_refresh_token_jti(raw)
    assert extracted == jti


def test_parse_refresh_token_jti_bad_format() -> None:
    from backend.auth.tokens import parse_refresh_token_jti

    assert parse_refresh_token_jti("no-colon-here") is None
    assert parse_refresh_token_jti("") is None


# ---------------------------------------------------------------------------
# Personal Access Tokens
# ---------------------------------------------------------------------------


def test_create_pat_format() -> None:
    from backend.auth.tokens import create_pat, is_pat

    token_id, raw_token, token_hash = create_pat()

    assert raw_token.startswith("pat_")
    assert is_pat(raw_token)
    assert isinstance(token_id, str)
    assert isinstance(token_hash, str)
    assert len(token_hash) == 64  # sha256 hex digest


def test_create_pat_hash_matches() -> None:
    from backend.auth.tokens import create_pat, hash_pat

    _token_id, raw_token, token_hash = create_pat()
    assert hash_pat(raw_token) == token_hash


def test_create_pat_token_id_extractable() -> None:
    from backend.auth.tokens import create_pat, parse_pat_token_id

    token_id, raw_token, _ = create_pat()
    extracted = parse_pat_token_id(raw_token)
    assert extracted == token_id


def test_hash_pat_is_sha256() -> None:
    from backend.auth.tokens import hash_pat

    raw = "pat_abc123_deadbeef"
    expected = hashlib.sha256(raw.encode()).hexdigest()
    assert hash_pat(raw) == expected


def test_is_pat_true_for_pat_prefix() -> None:
    from backend.auth.tokens import is_pat

    assert is_pat("pat_abc123_random") is True


def test_is_pat_false_for_jwt() -> None:
    from backend.auth.tokens import is_pat

    assert is_pat("eyJhbGciOiJIUzI1NiJ9.payload.sig") is False
    assert is_pat("") is False


def test_parse_pat_token_id_bad_format() -> None:
    from backend.auth.tokens import parse_pat_token_id

    assert parse_pat_token_id("not-a-pat") is None
    assert parse_pat_token_id("pat_nounderscore") is None


# ---------------------------------------------------------------------------
# CLI import cleanliness
# ---------------------------------------------------------------------------


def test_cli_import_does_not_pull_in_argon2_or_jwt() -> None:
    """Importing cli.main must not cause argon2 or jwt to be loaded.

    This guards the lazy-import pattern: if someone accidentally adds a
    top-level 'import argon2' or 'import jwt' to a module reachable from
    cli.main, this test fails in CI before the binary is built.
    """
    import sys

    # Drop modules that might have been imported by earlier tests in this run.
    for key in list(sys.modules.keys()):
        if key == "argon2" or key.startswith("argon2.") or key == "jwt":
            del sys.modules[key]

    # Importing cli.main should not pull in argon2 or jwt.
    import importlib

    importlib.import_module("cli.main")

    assert "argon2" not in sys.modules, "argon2 imported transitively from cli.main"
    assert "jwt" not in sys.modules, "PyJWT imported transitively from cli.main"
