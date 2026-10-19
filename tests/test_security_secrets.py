"""Secrets handling (bug-bash plan §7.4, run order item 23).

Covers what the existing config and auth tests leave out: a provider error that
echoes the key, through the real probe and route; the PATCH response and log;
both providers' env-managed keys; a PATCH that is refused half way; and what a
password change does to the user's other sessions. No network: the probe's
HTTP client is a mock transport.

Tests marked xfail(strict=True) are bug-bash findings: the app is wrong and the
test states the expected behaviour.
"""

import logging

import anthropic
import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from backend.auth.passwords import hash_password
from backend.config import settings
from backend.db import crud_auth
from backend.main import app
from backend.providers import healthcheck
from backend.security import source_key


_LEAKY_KEY = "sk-ant-api03-bugbashLEAK-0123456789"
_PASSWORD = "correct horse battery"  # noqa: S105 - test-only credential


@pytest.fixture
async def client(test_db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "paranoid.db"))
    monkeypatch.setattr(settings, "config_secret", "")
    monkeypatch.delenv("CONFIG_SECRET", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "default_provider", "anthropic")
    source_key._reset_cache_for_tests()
    healthcheck._reset_rate_limit_for_tests()
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as c:
        yield c
    healthcheck._reset_rate_limit_for_tests()
    source_key._reset_cache_for_tests()


def _anthropic_echoing_the_key(monkeypatch, status: int) -> None:
    """Make every AsyncAnthropic client answer `status` with the key in the body."""
    real = anthropic.AsyncAnthropic

    def handler(request: httpx.Request) -> httpx.Response:
        key = request.headers.get("x-api-key", "")
        return httpx.Response(
            status,
            json={"type": "error", "error": {"type": "x", "message": f"bad key {key}"}},
        )

    def factory(*args, **kwargs):
        kwargs["http_client"] = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        kwargs["max_retries"] = 0
        return real(*args, **kwargs)

    monkeypatch.setattr(anthropic, "AsyncAnthropic", factory)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 400, 500])
async def test_probe_error_that_echoes_the_key_is_scrubbed_end_to_end(
    client, monkeypatch, caplog, status
):
    _anthropic_echoing_the_key(monkeypatch, status)
    with caplog.at_level(logging.DEBUG):
        resp = await client.post(
            "/api/config/test-provider",
            json={"provider": "anthropic", "api_key": _LEAKY_KEY, "model": "claude-x"},
        )
    assert resp.status_code == 200
    assert resp.json()["ok"] is False
    assert "bad key ***" in resp.json()["message"]  # the echo happened, and was scrubbed
    assert _LEAKY_KEY not in resp.text
    assert _LEAKY_KEY not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["anthropic_api_key", "openai_api_key"])
async def test_patch_never_echoes_or_logs_a_key(client, caplog, field):
    with caplog.at_level(logging.DEBUG):
        resp = await client.patch("/api/config/", json={field: _LEAKY_KEY})
        again = await client.get("/api/config/")
    assert resp.status_code == 200
    assert _LEAKY_KEY not in resp.text
    assert _LEAKY_KEY not in again.text
    assert _LEAKY_KEY not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "env_name"),
    [("anthropic_api_key", "ANTHROPIC_API_KEY"), ("openai_api_key", "OPENAI_API_KEY")],
)
@pytest.mark.parametrize("value", ["sk-other", None])
async def test_env_managed_key_cannot_be_replaced_or_cleared(
    client, monkeypatch, field, env_name, value
):
    monkeypatch.setenv(env_name, "sk-from-env")
    monkeypatch.setattr(settings, field, "sk-from-env")
    resp = await client.patch("/api/config/", json={field: value})
    assert resp.status_code == 400
    assert getattr(settings, field) == "sk-from-env"


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    reason=(
        "Bug-bash finding (item 23): PATCH /api/config applies the non-key fields (and an "
        "earlier key) before it checks whether a key is env-managed, so a request that "
        "gets 400 has still changed the instance's settings."
    ),
)
async def test_a_refused_config_patch_changes_nothing(client, monkeypatch):
    # The route writes settings directly; these make monkeypatch restore them.
    monkeypatch.setattr(settings, "default_iterations", settings.default_iterations)
    monkeypatch.setattr(settings, "default_provider", settings.default_provider)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    resp = await client.patch(
        "/api/config/",
        json={
            "default_provider": "ollama",
            "default_iterations": 7,
            "anthropic_api_key": "sk-ant-new",
            "openai_api_key": "sk-other",
        },
    )
    assert resp.status_code == 400
    assert settings.default_provider == "anthropic"
    assert settings.default_iterations != 7
    assert settings.anthropic_api_key == ""


async def _login(client: AsyncClient, username: str, password: str = _PASSWORD) -> dict:
    r = await client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    reason=(
        "Bug-bash finding (item 23): PATCH /api/auth/me changes the password hash but "
        "revokes no session, so a refresh token issued before the change keeps working "
        "for its full 7 days. docs/authentication.md doesn't say either way."
    ),
)
async def test_password_change_ends_the_users_other_sessions(client, monkeypatch):
    monkeypatch.setattr(settings, "paranoid_require_auth", True)
    await crud_auth.create_user(
        username="alice",
        email="alice@test.local",
        password_hash=hash_password(_PASSWORD),
        is_admin=False,
    )
    stolen = await _login(client, "alice")  # e.g. a session on a lost laptop
    mine = await _login(client, "alice")

    r = await client.patch(
        "/api/auth/me",
        json={"current_password": _PASSWORD, "password": "a brand new passphrase"},
        headers={"Authorization": f"Bearer {mine['access_token']}"},
    )
    assert r.status_code == 200

    client.cookies.clear()
    r = await client.post("/api/auth/refresh", json={"refresh_token": stolen["refresh_token"]})
    assert r.status_code == 401
