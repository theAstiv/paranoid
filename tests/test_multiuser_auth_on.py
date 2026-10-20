"""Multi-user verification pass with PARANOID_REQUIRE_AUTH=true (bug-bash-plan.md §7.7).

End-to-end against a temp DB, no mocks of the auth CRUD layer: real argon2 logins,
real sessions, real PAT rows. The route-by-role denials live in test_rbac_matrix.py
and the PAT project scope in test_pat_scope.py; this file covers the flows those
don't: refresh rotation and reuse, the login rate limit, CSRF on the auth routes,
JWT key derivation, PAT lifecycle, the last-owner guard, the status workflow, SSE
authorization and project soft delete.

Tests marked xfail(strict=True) are bug-bash findings: the app is wrong and the
test states the expected behaviour. A fix makes them XPASS, which fails the run
until the marker is removed.
"""

import asyncio
import hashlib
import re
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.auth import tokens as auth_tokens
from backend.auth.passwords import hash_password
from backend.auth.tokens import create_access_token
from backend.config import settings
from backend.db import crud, crud_activity, crud_auth, crud_projects
from backend.db.connection import db
from backend.main import app
from backend.models.enums import ModelStatus
from backend.security.csrf import parse_allowed_origins
from tests._rbac_world import World, build_world


_PASSWORD = "correct horse battery"  # noqa: S105 - test-only credential


@pytest.fixture(autouse=True)
def auth_on(monkeypatch):
    monkeypatch.setattr(settings, "paranoid_require_auth", True)


def _client() -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    )


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _make_user(username: str, *, is_admin: bool = False) -> dict:
    return await crud_auth.create_user(
        username=username,
        email=f"{username}@test.local",
        password_hash=hash_password(_PASSWORD),
        is_admin=is_admin,
    )


async def _login(client: AsyncClient, username: str) -> dict:
    r = await client.post("/api/auth/login", json={"username": username, "password": _PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()


async def _refresh(client: AsyncClient, raw: str):
    # Body path (CLI). Clear cookies so the jar's latest cookie can't stand in.
    client.cookies.clear()
    return await client.post("/api/auth/refresh", json={"refresh_token": raw})


# ---------------------------------------------------------------------------
# Login smoke + refresh rotation / reuse detection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_on_admin_login_smoke(test_db):
    await _make_user("admin", is_admin=True)
    async with _client() as client:
        assert (await client.get("/api/auth/me")).status_code == 401
        r = await client.post("/api/auth/login", json={"username": "admin", "password": _PASSWORD})
        assert r.status_code == 200
        body = r.json()
        assert "password_hash" not in body["user"]

        cookie = r.headers["set-cookie"].lower()
        for attr in ("httponly", "samesite=strict", "secure", "path=/api/auth/"):
            assert attr in cookie

        me = await client.get("/api/auth/me", headers=_bearer(body["access_token"]))
        assert me.status_code == 200
        assert me.json()["username"] == "admin"
        assert me.json()["is_admin"]

        # With auth on, a project route with no token is 401, not the anonymous admin.
        assert (await client.get("/api/projects")).status_code == 401


@pytest.mark.asyncio
async def test_refresh_rotates_and_reuse_kills_every_session(test_db):
    user = await _make_user("alice")
    async with _client() as client:
        first = (await _login(client, "alice"))["refresh_token"]
        other_device = (await _login(client, "alice"))["refresh_token"]

        r = await _refresh(client, first)
        assert r.status_code == 200
        rotated = r.json()["refresh_token"]
        assert rotated != first
        assert auth_tokens.parse_refresh_token_jti(rotated) != auth_tokens.parse_refresh_token_jti(
            first
        )
        old_session = await crud_auth.get_session(auth_tokens.parse_refresh_token_jti(first))
        assert old_session["revoked_at"] is not None

        # Replaying the rotated-out token is reuse: the whole family dies.
        r = await _refresh(client, first)
        assert r.status_code == 401
        assert "reuse" in r.json()["detail"].lower()

        assert (await _refresh(client, rotated)).status_code == 401
        assert (await _refresh(client, other_device)).status_code == 401

    conn = await db.get()
    async with conn.execute(
        "SELECT COUNT(*) FROM sessions WHERE user_id = ? AND revoked_at IS NULL", (user["id"],)
    ) as cur:
        assert (await cur.fetchone())[0] == 0


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    reason="Finding: /api/auth/refresh looks the session up by jti only and never checks "
    "the random half of the refresh token, so '<jti>:anything' is accepted",
)
async def test_refresh_rejects_a_token_with_the_right_jti_and_a_wrong_secret(test_db):
    await _make_user("alice")
    async with _client() as client:
        raw = (await _login(client, "alice"))["refresh_token"]
        jti = auth_tokens.parse_refresh_token_jti(raw)
        r = await _refresh(client, f"{jti}:forged")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Brute-force tier
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_brute_force_gets_429_after_ten_attempts(test_db):
    await _make_user("alice")
    async with _client() as client:
        for _ in range(10):
            r = await client.post("/api/auth/login", json={"username": "alice", "password": "x"})
            assert r.status_code == 401
        r = await client.post("/api/auth/login", json={"username": "alice", "password": _PASSWORD})
    # Even the right password is refused once the bucket is full.
    assert r.status_code == 429
    assert "Retry-After" in r.headers


@pytest.mark.asyncio
async def test_refresh_brute_force_gets_429_after_ten_attempts(test_db):
    async with _client() as client:
        for _ in range(10):
            assert (await _refresh(client, "no-such:token")).status_code == 401
        r = await _refresh(client, "no-such:token")
    assert r.status_code == 429


@pytest.mark.asyncio
async def test_login_limit_is_not_bypassed_by_a_spoofed_forwarded_for(test_db):
    await _make_user("alice")
    async with _client() as client:
        statuses = [
            (
                await client.post(
                    "/api/auth/login",
                    json={"username": "alice", "password": "x"},
                    headers={"X-Forwarded-For": f"203.0.113.{i}"},
                )
            ).status_code
            for i in range(11)
        ]
    assert statuses[-1] == 429


# ---------------------------------------------------------------------------
# CSRF on the auth routes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "header",
    [{"Origin": "https://evil.example"}, {"Referer": "https://evil.example/page"}],
)
async def test_refresh_from_a_disallowed_origin_is_rejected_and_rotates_nothing(test_db, header):
    await _make_user("alice")
    async with _client() as client:
        raw = (await _login(client, "alice"))["refresh_token"]
        client.cookies.clear()
        r = await client.post("/api/auth/refresh", json={"refresh_token": raw}, headers=header)
        assert r.status_code == 403
        assert "ALLOWED_ORIGINS" in r.json()["detail"]
        # The token wasn't touched: it still refreshes from an allowed caller.
        assert (await _refresh(client, raw)).status_code == 200


@pytest.mark.asyncio
async def test_refresh_from_an_allowed_origin_passes(test_db):
    allowed = parse_allowed_origins(settings.allowed_origins)
    if not allowed:
        pytest.skip("ALLOWED_ORIGINS is empty in this environment")
    await _make_user("alice")
    async with _client() as client:
        raw = (await _login(client, "alice"))["refresh_token"]
        client.cookies.clear()
        r = await client.post(
            "/api/auth/refresh", json={"refresh_token": raw}, headers={"Origin": allowed[0]}
        )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_login_from_a_disallowed_origin_is_rejected(test_db):
    await _make_user("alice")
    async with _client() as client:
        r = await client.post(
            "/api/auth/login",
            json={"username": "alice", "password": _PASSWORD},
            headers={"Origin": "https://evil.example"},
        )
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# JWT secret separation
# ---------------------------------------------------------------------------


def test_jwt_key_is_derived_from_config_secret_with_its_own_salt(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", "")
    monkeypatch.setattr(settings, "config_secret", "s3cret-one")
    key = auth_tokens._get_jwt_key()

    expected = hashlib.pbkdf2_hmac("sha256", b"s3cret-one", b"paranoid:jwt:v1", 100_000).hex()
    assert key == expected
    assert key != "s3cret-one"
    # Not the key that encrypts stored credentials (backend/security/source_key.py).
    fernet_raw = hashlib.pbkdf2_hmac(
        "sha256", b"s3cret-one", b"paranoid:source_key:v1", 100_000, dklen=32
    )
    assert key != fernet_raw.hex()


@pytest.mark.asyncio
async def test_rotating_config_secret_invalidates_jwts(test_db, monkeypatch):
    import jwt as pyjwt

    user = await _make_user("alice")
    monkeypatch.setattr(settings, "jwt_secret", "")
    monkeypatch.setattr(settings, "config_secret", "s3cret-one")
    token = create_access_token(user["id"], "alice", False)

    # A token signed with the raw CONFIG_SECRET (no derivation) is not accepted.
    now = int(datetime.now(UTC).timestamp())
    raw_signed = pyjwt.encode(
        {"sub": user["id"], "iat": now, "exp": now + 600, "jti": "x"},
        "s3cret-one",
        algorithm="HS256",
    )
    async with _client() as client:
        assert (await client.get("/api/auth/me", headers=_bearer(token))).status_code == 200
        assert (await client.get("/api/auth/me", headers=_bearer(raw_signed))).status_code == 401

        monkeypatch.setattr(settings, "config_secret", "s3cret-two")
        assert (await client.get("/api/auth/me", headers=_bearer(token))).status_code == 401


@pytest.mark.asyncio
async def test_explicit_jwt_secret_survives_a_config_secret_rotation(test_db, monkeypatch):
    user = await _make_user("alice")
    monkeypatch.setattr(settings, "jwt_secret", "dedicated-jwt-key")
    monkeypatch.setattr(settings, "config_secret", "s3cret-one")
    token = create_access_token(user["id"], "alice", False)
    monkeypatch.setattr(settings, "config_secret", "s3cret-two")
    async with _client() as client:
        assert (await client.get("/api/auth/me", headers=_bearer(token))).status_code == 200


@pytest.mark.asyncio
async def test_ephemeral_key_changes_on_restart(test_db, monkeypatch):
    user = await _make_user("alice")
    monkeypatch.setattr(settings, "jwt_secret", "")
    monkeypatch.setattr(settings, "config_secret", "")
    monkeypatch.setattr(auth_tokens, "_ephemeral_jwt_key", None)
    token = create_access_token(user["id"], "alice", False)
    async with _client() as client:
        assert (await client.get("/api/auth/me", headers=_bearer(token))).status_code == 200
        monkeypatch.setattr(auth_tokens, "_ephemeral_jwt_key", None)  # a new process
        assert (await client.get("/api/auth/me", headers=_bearer(token))).status_code == 401


# ---------------------------------------------------------------------------
# Personal access tokens
# ---------------------------------------------------------------------------


_PAT_RE = re.compile(
    r"^pat_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}_[0-9a-f]{64}$"
)


async def _new_pat(client: AsyncClient, jwt: str, **body) -> dict:
    r = await client.post("/api/auth/tokens", json={"name": "ci", **body}, headers=_bearer(jwt))
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.asyncio
async def test_pat_lifecycle_format_listing_last_used_and_revocation(test_db):
    user = await _make_user("alice")
    jwt = create_access_token(user["id"], "alice", False)
    async with _client() as client:
        pat = await _new_pat(client, jwt)
        raw = pat["token"]
        assert _PAT_RE.match(raw)

        listed = (await client.get("/api/auth/tokens", headers=_bearer(jwt))).json()
        assert len(listed) == 1
        assert "token" not in listed[0]
        assert "token_hash" not in listed[0]
        assert raw not in str(listed)
        assert listed[0]["last_used_at"] is None

        me = await client.get("/api/auth/me", headers=_bearer(raw))
        assert me.status_code == 200
        assert me.json()["username"] == "alice"
        assert (await crud_auth.get_pat_by_id(pat["id"]))["last_used_at"] is not None

        # Right id, wrong secret: the sha256 check refuses it.
        tampered = raw[:-4] + ("0000" if not raw.endswith("0000") else "1111")
        assert (await client.get("/api/auth/me", headers=_bearer(tampered))).status_code == 401

        r = await client.delete(f"/api/auth/tokens/{pat['id']}", headers=_bearer(jwt))
        assert r.status_code == 204
        r = await client.get("/api/auth/me", headers=_bearer(raw))
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_pat_create_response_has_no_token_hash(test_db):
    user = await _make_user("alice")
    jwt = create_access_token(user["id"], "alice", False)
    async with _client() as client:
        pat = await _new_pat(client, jwt)
    assert "token_hash" not in pat


@pytest.mark.asyncio
async def test_expired_pat_is_401(test_db):
    user = await _make_user("alice")
    jwt = create_access_token(user["id"], "alice", False)
    async with _client() as client:
        pat = await _new_pat(client, jwt, expires_in_days=1)
        conn = await db.get()
        await conn.execute(
            "UPDATE personal_access_tokens SET expires_at = ? WHERE id = ?",
            ((datetime.now(UTC) - timedelta(minutes=1)).isoformat(), pat["id"]),
        )
        await conn.commit()
        r = await client.get("/api/auth/me", headers=_bearer(pat["token"]))
    assert r.status_code == 401
    assert "expired" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_pat_of_a_deactivated_user_is_401(test_db):
    user = await _make_user("alice")
    jwt = create_access_token(user["id"], "alice", False)
    async with _client() as client:
        pat = await _new_pat(client, jwt)
        conn = await db.get()
        await conn.execute("UPDATE users SET is_active = 0 WHERE id = ?", (user["id"],))
        await conn.commit()
        assert (await client.get("/api/auth/me", headers=_bearer(pat["token"]))).status_code == 401
        assert (await client.get("/api/auth/me", headers=_bearer(jwt))).status_code == 401


@pytest.mark.asyncio
async def test_scoped_pat_on_another_project_is_403(test_db):
    w = await build_world()
    async with _client() as client:
        r = await client.get(f"/api/models/{w.model}", headers=_bearer(w.tokens["pat_b"]))
        assert r.status_code == 403
        r = await client.get(f"/api/models/{w.model}", headers=_bearer(w.tokens["pat_free"]))
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Last owner
# ---------------------------------------------------------------------------


async def _owners(project_id: str) -> int:
    return sum(1 for m in await crud_projects.list_members(project_id) if m["role"] == "owner")


@pytest.mark.asyncio
async def test_removing_the_last_owner_is_refused(test_db):
    w = await build_world()
    owner_id = w.users["owner"]["id"]
    async with _client() as client:
        r = await client.delete(
            f"/api/projects/{w.project_a}/members/{owner_id}",
            headers=_bearer(w.tokens["owner"]),
        )
    assert r.status_code == 409
    assert "last owner" in r.json()["detail"]
    assert await _owners(w.project_a) == 1


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    reason="Finding: remove_member counts owners and deletes in separate statements with "
    "no BEGIN IMMEDIATE, so two concurrent removals of the only two owners both succeed",
)
async def test_two_racing_owner_removals_leave_an_owner(test_db):
    w = await build_world()
    a = w.users["owner"]
    b = w.users["editor"]
    await crud_projects.update_member_role(w.project_a, b["id"], "owner")
    async with _client() as client:
        results = await asyncio.gather(
            client.delete(
                f"/api/projects/{w.project_a}/members/{b['id']}", headers=_bearer(w.tokens["owner"])
            ),
            client.delete(
                f"/api/projects/{w.project_a}/members/{a['id']}",
                headers=_bearer(w.tokens["editor"]),
            ),
        )
    assert sorted(r.status_code for r in results) == [204, 409]
    assert await _owners(w.project_a) == 1


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    reason="Finding: PATCH /projects/{id}/members/{user_id} has no last-owner guard, so the "
    "only owner can be demoted and the project is left with no owner",
)
async def test_demoting_the_last_owner_is_refused(test_db):
    w = await build_world()
    owner_id = w.users["owner"]["id"]
    async with _client() as client:
        r = await client.patch(
            f"/api/projects/{w.project_a}/members/{owner_id}",
            json={"role": "viewer"},
            headers=_bearer(w.tokens["owner"]),
        )
    assert r.status_code == 409
    assert await _owners(w.project_a) == 1


# ---------------------------------------------------------------------------
# Status workflow
# ---------------------------------------------------------------------------

# The documented workflow (bug-bash-plan.md §7.7): pending → in_progress → completed
# → in_review → approved, with failed and archived; archived is terminal.
_ALLOWED = {
    ("pending", "in_progress"),
    ("in_progress", "completed"),
    ("in_progress", "failed"),
    ("failed", "in_progress"),
    ("completed", "in_progress"),
    ("completed", "in_review"),
    ("completed", "archived"),
    ("in_review", "approved"),
    ("in_review", "completed"),
    ("in_review", "archived"),
    ("approved", "in_review"),
    ("approved", "archived"),
}


@pytest.mark.asyncio
async def test_status_workflow_allows_only_the_documented_transitions(test_db):
    w = await build_world()
    statuses = [s.value for s in ModelStatus]
    wrong: list[str] = []
    async with _client() as client:
        for current in statuses:
            for new in statuses:
                await crud.update_threat_model(w.model, status=current)
                r = await client.patch(
                    f"/api/models/{w.model}",
                    json={"status": new},
                    headers=_bearer(w.tokens["editor"]),
                )
                expect = 200 if current == new or (current, new) in _ALLOWED else 422
                stored = (await crud.get_threat_model(w.model))["status"]
                if r.status_code != expect or stored != (new if expect == 200 else current):
                    wrong.append(f"{current}->{new}: {r.status_code}, stored {stored}")
                if expect == 422 and "Cannot transition" not in r.json().get("detail", ""):
                    wrong.append(f"{current}->{new}: unclear message {r.text}")
        r = await client.patch(
            f"/api/models/{w.model}", json={"status": "draft"}, headers=_bearer(w.tokens["editor"])
        )
        assert r.status_code == 422
    assert wrong == []


# ---------------------------------------------------------------------------
# SSE authorization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_sse_needs_editor_and_denied_callers_never_reach_the_pipeline(test_db):
    w = await build_world()
    calls: list[str] = []

    async def _runner(*_args, **_kwargs):
        calls.append("ran")
        return
        yield  # pragma: no cover - makes this an async generator

    form = {"assumptions": "[]", "has_ai_components": "false"}
    with (
        patch("backend.routes.models.build_provider_from_record", return_value=MagicMock()),
        patch("backend.routes.models.build_fast_provider", return_value=None),
        patch("backend.routes.models.run_pipeline_for_model", _runner),
    ):
        async with _client() as client:
            url = f"/api/models/{w.model}/run"
            assert (await client.post(url, data=form)).status_code == 401
            for who in ("stranger", "viewer", "pat_b"):
                r = await client.post(url, data=form, headers=_bearer(w.tokens[who]))
                assert r.status_code == 403, who
                assert not r.headers.get("content-type", "").startswith("text/event-stream")
            assert calls == []

            r = await client.post(url, data=form, headers=_bearer(w.tokens["editor"]))
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert calls == ["ran"]


@pytest.mark.asyncio
async def test_source_events_sse_needs_viewer(test_db):
    w = await build_world()
    url = f"/api/sources/{w.source}/events"
    async with _client() as client:
        assert (await client.get(url)).status_code == 401
        for who in ("stranger", "pat_b"):
            assert (await client.get(url, headers=_bearer(w.tokens[who]))).status_code == 403
        r = await client.get(url, headers=_bearer(w.tokens["viewer"]))
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert '"status": "ready"' in r.text or '"status":"ready"' in r.text


# ---------------------------------------------------------------------------
# Soft delete (archive)
# ---------------------------------------------------------------------------


async def _archive(w: World) -> None:
    async with _client() as client:
        r = await client.delete(f"/api/projects/{w.project_a}", headers=_bearer(w.tokens["owner"]))
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_archiving_a_project_hides_it_and_keeps_its_data(test_db):
    w = await build_world()
    await crud_activity.safe_log_activity(
        project_id=w.project_a,
        user_id=w.users["owner"]["id"],
        entity_type="model",
        entity_id=w.model,
        action="created",
    )
    before = await crud_activity.list_activity(w.project_a, limit=200)
    await _archive(w)

    project = await crud_projects.get_project(w.project_a)
    assert project is not None
    assert project["is_archived"]
    # Not cascade-deleted: the model and its children are still there.
    assert await crud.get_threat_model(w.model) is not None
    assert {t["id"] for t in await crud.list_threats(w.model)} == {w.threat}
    after = await crud_activity.list_activity(w.project_a, limit=200)
    assert {a["id"] for a in before} <= {a["id"] for a in after}
    assert any(a["action"] == "archived" for a in after)

    async with _client() as client:
        for who in ("owner", "viewer"):
            listed = (await client.get("/api/projects", headers=_bearer(w.tokens[who]))).json()
            assert w.project_a not in {p["id"] for p in listed}, who
        r = await client.post(
            "/api/models/",
            json={
                "title": "t",
                "description": "a long enough description",
                "project_id": w.project_a,
            },
            headers=_bearer(w.tokens["editor"]),
        )
        assert r.status_code == 403
        # Reads still work (archived = read-only, not secret).
        r = await client.get(f"/api/models/{w.model}", headers=_bearer(w.tokens["viewer"]))
        assert r.status_code == 200


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    reason="Finding: an archived project is not read-only — require_role ignores "
    "projects.is_archived, so editors still edit models, threats and run pipelines there",
)
async def test_archived_project_refuses_edits(test_db):
    w = await build_world()
    await _archive(w)
    editor = _bearer(w.tokens["editor"])
    async with _client() as client:
        statuses = {
            "PATCH model": (
                await client.patch(f"/api/models/{w.model}", json={"title": "x"}, headers=editor)
            ).status_code,
            "PATCH threat": (
                await client.patch(f"/api/threats/{w.threat}", json={"name": "x"}, headers=editor)
            ).status_code,
            "POST comment": (
                await client.post(
                    f"/api/models/{w.model}/comments", json={"body": "x"}, headers=editor
                )
            ).status_code,
        }
    assert statuses == dict.fromkeys(statuses, 403)
