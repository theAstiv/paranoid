"""Tests for /api/auth/* routes.

Uses httpx.AsyncClient with ASGITransport. Functions imported at module level in
backend.routes.auth are patched there (usage site), not at the source module.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app


# ---------------------------------------------------------------------------
# Shared fixtures & helpers
# ---------------------------------------------------------------------------

_ANON_ADMIN_ID = "00000000-0000-0000-0000-000000000001"  # matches dependencies._ANON_ADMIN

_PLAIN_USER = {
    "id": "user-plain-uuid",
    "username": "alice",
    "email": "alice@test.local",
    "display_name": "Alice",
    "password_hash": "$argon2id$v=19$m=65536,t=3,p=4$placeholder$placeholder",
    "is_active": 1,
    "is_admin": 0,
    "created_at": "2026-01-01T00:00:00",
    "updated_at": "2026-01-01T00:00:00",
    "last_login_at": None,
}


@pytest.fixture
async def client(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def _future_session(jti: str, user_id: str) -> dict:
    return {
        "id": jti,
        "user_id": user_id,
        "created_at": "2026-01-01T00:00:00",
        "expires_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
        "revoked_at": None,
    }


# ---------------------------------------------------------------------------
# POST /api/auth/register
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_returns_201(client):
    with (
        patch("backend.routes.auth.get_user_by_username", new=AsyncMock(return_value=None)),
        patch("backend.routes.auth.get_user_by_email", new=AsyncMock(return_value=None)),
        patch("backend.routes.auth.create_user", new=AsyncMock(return_value=_PLAIN_USER)),
    ):
        resp = await client.post(
            "/api/auth/register",
            json={"username": "alice", "email": "alice@test.local", "password": "password123"},
        )
    assert resp.status_code == 201
    data = resp.json()
    assert data["username"] == "alice"
    assert "password_hash" not in data


@pytest.mark.asyncio
async def test_register_duplicate_username_returns_409(client):
    with (
        patch("backend.routes.auth.get_user_by_username", new=AsyncMock(return_value=_PLAIN_USER)),
    ):
        resp = await client.post(
            "/api/auth/register",
            json={"username": "alice", "email": "new@test.local", "password": "password123"},
        )
    assert resp.status_code == 409
    assert "Username" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_register_duplicate_email_returns_409(client):
    with (
        patch("backend.routes.auth.get_user_by_username", new=AsyncMock(return_value=None)),
        patch("backend.routes.auth.get_user_by_email", new=AsyncMock(return_value=_PLAIN_USER)),
    ):
        resp = await client.post(
            "/api/auth/register",
            json={"username": "newuser", "email": "alice@test.local", "password": "password123"},
        )
    assert resp.status_code == 409
    assert "Email" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_register_invalid_username_pattern_returns_422(client):
    resp = await client.post(
        "/api/auth/register",
        json={"username": "bad user!", "email": "x@x.com", "password": "password123"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_register_password_too_short_returns_422(client):
    resp = await client.post(
        "/api/auth/register",
        json={"username": "alice", "email": "alice@test.local", "password": "short"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_register_missing_at_in_email_returns_422(client):
    resp = await client.post(
        "/api/auth/register",
        json={"username": "alice", "email": "notanemail", "password": "password123"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/auth/login
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_valid_credentials_returns_tokens(client):
    from backend.auth.passwords import hash_password

    hashed = hash_password("correct-password")
    user = {**_PLAIN_USER, "password_hash": hashed}

    with (
        patch("backend.routes.auth.get_user_by_username", new=AsyncMock(return_value=user)),
        patch("backend.routes.auth.create_session", new=AsyncMock(return_value={})),
        patch("backend.routes.auth.update_last_login", new=AsyncMock()),
    ):
        resp = await client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "correct-password"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"  # noqa: S105 — not a credential, it's the OAuth2 token_type field
    assert "user" in data
    assert "password_hash" not in data["user"]


@pytest.mark.asyncio
async def test_login_wrong_password_returns_401(client):
    from backend.auth.passwords import hash_password

    user = {**_PLAIN_USER, "password_hash": hash_password("correct-password")}
    with patch("backend.routes.auth.get_user_by_username", new=AsyncMock(return_value=user)):
        resp = await client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "wrong-password"},
        )
    assert resp.status_code == 401
    assert "Invalid credentials" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_login_unknown_user_returns_401(client):
    with patch("backend.routes.auth.get_user_by_username", new=AsyncMock(return_value=None)):
        resp = await client.post(
            "/api/auth/login",
            json={"username": "nobody", "password": "any-password"},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_inactive_user_returns_401(client):
    from backend.auth.passwords import hash_password

    inactive = {**_PLAIN_USER, "password_hash": hash_password("pw"), "is_active": 0}
    with patch("backend.routes.auth.get_user_by_username", new=AsyncMock(return_value=inactive)):
        resp = await client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "pw"},
        )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/auth/refresh
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_valid_token_rotates_session(client):
    from backend.auth.tokens import create_refresh_token

    jti, raw = create_refresh_token()
    session = _future_session(jti, _PLAIN_USER["id"])

    with (
        patch("backend.routes.auth.get_session", new=AsyncMock(return_value=session)),
        patch("backend.routes.auth.get_user_by_id", new=AsyncMock(return_value=_PLAIN_USER)),
        patch("backend.routes.auth.revoke_session", new=AsyncMock()),
        patch("backend.routes.auth.create_session", new=AsyncMock(return_value={})),
    ):
        resp = await client.post("/api/auth/refresh", json={"refresh_token": raw})

    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data


@pytest.mark.asyncio
async def test_refresh_revoked_token_kills_all_sessions(client):
    from backend.auth.tokens import create_refresh_token

    jti, raw = create_refresh_token()
    revoked = {
        **_future_session(jti, _PLAIN_USER["id"]),
        "revoked_at": "2026-01-02T00:00:00",
    }
    kill_mock = AsyncMock()
    with (
        patch("backend.routes.auth.get_session", new=AsyncMock(return_value=revoked)),
        patch("backend.routes.auth.revoke_all_user_sessions", new=kill_mock),
    ):
        resp = await client.post("/api/auth/refresh", json={"refresh_token": raw})

    assert resp.status_code == 401
    assert "reuse" in resp.json()["detail"].lower()
    kill_mock.assert_awaited_once_with(_PLAIN_USER["id"])


@pytest.mark.asyncio
async def test_refresh_expired_token_returns_401(client):
    from backend.auth.tokens import create_refresh_token

    jti, raw = create_refresh_token()
    expired = {
        **_future_session(jti, _PLAIN_USER["id"]),
        "expires_at": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
    }
    with (
        patch("backend.routes.auth.get_session", new=AsyncMock(return_value=expired)),
        patch("backend.routes.auth.revoke_session", new=AsyncMock()),
    ):
        resp = await client.post("/api/auth/refresh", json={"refresh_token": raw})

    assert resp.status_code == 401
    assert "expired" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_refresh_unknown_jti_returns_401(client):
    from backend.auth.tokens import create_refresh_token

    _, raw = create_refresh_token()
    with patch("backend.routes.auth.get_session", new=AsyncMock(return_value=None)):
        resp = await client.post("/api/auth/refresh", json={"refresh_token": raw})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_refresh_no_token_returns_401(client):
    resp = await client.post("/api/auth/refresh")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/auth/me (auth disabled → anon admin)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_me_when_auth_disabled_returns_anon_admin(client):
    """PARANOID_REQUIRE_AUTH=false → anon admin returned without DB hit."""
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "admin"
    assert data["is_admin"] is True
    assert "password_hash" not in data


# ---------------------------------------------------------------------------
# POST /api/auth/tokens (PAT create)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_pat_returns_raw_token(client):
    pat_row = {
        "id": "pat-id-uuid",
        "user_id": _ANON_ADMIN_ID,
        "name": "CI Token",
        "project_id": None,
        "last_used_at": None,
        "expires_at": None,
        "created_at": "2026-01-01T00:00:00",
    }
    with patch("backend.routes.auth.db_create_pat", new=AsyncMock(return_value=pat_row)):
        resp = await client.post("/api/auth/tokens", json={"name": "CI Token"})

    assert resp.status_code == 201
    data = resp.json()
    assert "token" in data
    assert data["token"].startswith("pat_")
    assert data["name"] == "CI Token"


@pytest.mark.asyncio
async def test_create_pat_with_expiry(client):
    pat_row = {
        "id": "pat-id-uuid",
        "user_id": _ANON_ADMIN_ID,
        "name": "Expiring Token",
        "project_id": None,
        "last_used_at": None,
        "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
        "created_at": "2026-01-01T00:00:00",
    }
    with patch("backend.routes.auth.db_create_pat", new=AsyncMock(return_value=pat_row)):
        resp = await client.post(
            "/api/auth/tokens",
            json={"name": "Expiring Token", "expires_in_days": 30},
        )
    assert resp.status_code == 201
    assert resp.json()["expires_at"] is not None


@pytest.mark.asyncio
async def test_list_pats_excludes_token_hash(client):
    rows = [
        {
            "id": "pat-id-uuid",
            "user_id": _ANON_ADMIN_ID,
            "name": "CI Token",
            "project_id": None,
            "last_used_at": None,
            "expires_at": None,
            "created_at": "2026-01-01T00:00:00",
        }
    ]
    with patch("backend.routes.auth.list_pats", new=AsyncMock(return_value=rows)):
        resp = await client.get("/api/auth/tokens")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert "token_hash" not in data[0]


@pytest.mark.asyncio
async def test_delete_pat_owned_by_current_user_returns_204(client):
    pat_row = {
        "id": "pat-id-uuid",
        "user_id": _ANON_ADMIN_ID,
        "name": "CI Token",
        "project_id": None,
        "last_used_at": None,
        "expires_at": None,
        "created_at": "2026-01-01T00:00:00",
    }
    with (
        patch("backend.routes.auth.get_pat_by_id", new=AsyncMock(return_value=pat_row)),
        patch("backend.routes.auth.delete_pat", new=AsyncMock()),
    ):
        resp = await client.delete("/api/auth/tokens/pat-id-uuid")
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_delete_pat_not_owned_returns_404(client):
    """PAT owned by a different user should 404 (avoids ownership enumeration)."""
    pat_row = {
        "id": "pat-id-uuid",
        "user_id": "some-other-user",
        "name": "Other Token",
        "project_id": None,
        "last_used_at": None,
        "expires_at": None,
        "created_at": "2026-01-01T00:00:00",
    }
    with patch("backend.routes.auth.get_pat_by_id", new=AsyncMock(return_value=pat_row)):
        resp = await client.delete("/api/auth/tokens/pat-id-uuid")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_pat_not_found_returns_404(client):
    with patch("backend.routes.auth.get_pat_by_id", new=AsyncMock(return_value=None)):
        resp = await client.delete("/api/auth/tokens/nonexistent")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/auth/users (admin-only list)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_users_as_anon_admin_returns_200(client):
    rows = [
        {
            "id": _ANON_ADMIN_ID,
            "username": "admin",
            "email": "admin@paranoid.local",
            "display_name": "Administrator",
            "is_active": 1,
            "is_admin": 1,
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
            "last_login_at": None,
        }
    ]
    with patch("backend.routes.auth.list_users", new=AsyncMock(return_value=rows)):
        resp = await client.get("/api/auth/users")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    assert len(resp.json()) == 1
