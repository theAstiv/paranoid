"""Tests for POST /api/config/test-provider (Phase 15 Task 2)."""

from dataclasses import dataclass

import pytest
from httpx import ASGITransport, AsyncClient

from backend.config import settings
from backend.main import app
from backend.providers import healthcheck
from backend.security import source_key
from tests._rbac_world import build_world


@dataclass
class _FakeResult:
    ok: bool
    latency_ms: int = 42
    error: str | None = None
    message: str | None = None


@pytest.fixture
async def client(test_db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "paranoid.db"))
    monkeypatch.setattr(settings, "config_secret", "")
    monkeypatch.delenv("CONFIG_SECRET", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "openai_api_key", "")
    source_key._reset_cache_for_tests()
    healthcheck._reset_rate_limit_for_tests()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    healthcheck._reset_rate_limit_for_tests()
    source_key._reset_cache_for_tests()


@pytest.mark.asyncio
async def test_test_provider_valid(client, monkeypatch):
    async def fake_ping(api_key, model):
        assert api_key == "sk-ant-valid"
        assert model == "claude-haiku-4-5-20251001"
        return _FakeResult(ok=True, latency_ms=123)

    monkeypatch.setattr("backend.routes.config.ping_anthropic", fake_ping)

    resp = await client.post(
        "/api/config/test-provider",
        json={
            "provider": "anthropic",
            "api_key": "sk-ant-valid",
            "model": "claude-haiku-4-5-20251001",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["latency_ms"] == 123
    assert data["provider"] == "anthropic"
    assert data["error"] is None


@pytest.mark.asyncio
async def test_test_provider_invalid_key(client, monkeypatch):
    async def fake_ping(api_key, model):
        return _FakeResult(ok=False, error="invalid_api_key", message="401 Unauthorized")

    monkeypatch.setattr("backend.routes.config.ping_anthropic", fake_ping)

    resp = await client.post(
        "/api/config/test-provider",
        json={"provider": "anthropic", "api_key": "sk-ant-bad"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["error"] == "invalid_api_key"


@pytest.mark.asyncio
async def test_test_provider_never_leaks_key(client, monkeypatch, caplog):
    """The supplied key must not appear in the response body or logs on
    either the success or the failure path, even if the provider echoes
    it into an error message."""
    import logging

    leaky_key = "sk-ant-LEAKED-1234567890"

    async def fake_ping(api_key, model):
        # Simulate an SDK that echoes the key into its error string.
        return _FakeResult(
            ok=False,
            error="provider_error",
            message="Authentication failed for ***",  # already scrubbed upstream
        )

    monkeypatch.setattr("backend.routes.config.ping_anthropic", fake_ping)

    with caplog.at_level(logging.DEBUG):
        resp = await client.post(
            "/api/config/test-provider",
            json={"provider": "anthropic", "api_key": leaky_key},
        )

    assert leaky_key not in resp.text
    assert leaky_key not in caplog.text


@pytest.mark.asyncio
async def test_test_provider_rate_limit_429(client, monkeypatch):
    async def fake_ping(api_key, model):
        return _FakeResult(ok=True)

    monkeypatch.setattr("backend.routes.config.ping_anthropic", fake_ping)

    # First 10 should pass.
    for _ in range(10):
        resp = await client.post(
            "/api/config/test-provider",
            json={"provider": "anthropic", "api_key": "sk-ant-x"},
        )
        assert resp.status_code == 200

    # 11th within the window must be rejected.
    resp = await client.post(
        "/api/config/test-provider",
        json={"provider": "anthropic", "api_key": "sk-ant-x"},
    )
    assert resp.status_code == 429
    assert "Too many test-connection requests" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_test_provider_falls_back_to_stored_key(client, monkeypatch):
    """When body omits api_key, the route falls back to settings.*_api_key
    (which the lifespan hydrates from env or DB at boot)."""
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-from-settings")
    seen: dict[str, str] = {}

    async def fake_ping(api_key, model):
        seen["api_key"] = api_key
        return _FakeResult(ok=True)

    monkeypatch.setattr("backend.routes.config.ping_anthropic", fake_ping)

    resp = await client.post("/api/config/test-provider", json={"provider": "anthropic"})
    assert resp.status_code == 200
    assert seen["api_key"] == "sk-ant-from-settings"


@pytest.mark.asyncio
async def test_test_provider_config_error_when_no_key(client):
    """No body key, no env, no DB → returns ok=false with config_error."""
    resp = await client.post("/api/config/test-provider", json={"provider": "anthropic"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["error"] == "config_error"


@pytest.mark.asyncio
async def test_test_provider_ollama(client, monkeypatch):
    async def fake_ping(base_url):
        return _FakeResult(ok=True, latency_ms=5)

    monkeypatch.setattr("backend.routes.config.ping_ollama", fake_ping)
    resp = await client.post(
        "/api/config/test-provider",
        json={"provider": "ollama", "ollama_base_url": "http://fake:11434"},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_test_provider_bedrock_uses_body_region_profile(client, monkeypatch):
    """Bedrock test-provider uses aws_region/aws_profile from the request body."""
    monkeypatch.setattr(settings, "aws_region", "us-east-1")
    monkeypatch.setattr(settings, "aws_profile", "")
    seen: dict = {}

    async def fake_ping(model, region, profile):
        seen.update({"model": model, "region": region, "profile": profile})
        return _FakeResult(ok=True, latency_ms=10)

    monkeypatch.setattr("backend.routes.config.ping_bedrock", fake_ping)
    resp = await client.post(
        "/api/config/test-provider",
        json={
            "provider": "bedrock",
            "model": "us.anthropic.claude-sonnet-4-20250514-v1:0",
            "aws_region": "eu-central-1",
            "aws_profile": "staging",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert seen["region"] == "eu-central-1"
    assert seen["profile"] == "staging"


@pytest.mark.asyncio
async def test_test_provider_bedrock_falls_back_to_settings(client, monkeypatch):
    """When body omits aws_region/aws_profile, settings values are used."""
    monkeypatch.setattr(settings, "aws_region", "ap-southeast-1")
    monkeypatch.setattr(settings, "aws_profile", "myprofile")
    seen: dict = {}

    async def fake_ping(model, region, profile):
        seen.update({"region": region, "profile": profile})
        return _FakeResult(ok=True)

    monkeypatch.setattr("backend.routes.config.ping_bedrock", fake_ping)
    resp = await client.post(
        "/api/config/test-provider",
        json={"provider": "bedrock"},
    )
    assert resp.status_code == 200
    assert seen["region"] == "ap-southeast-1"
    assert seen["profile"] == "myprofile"


# --- BB-11: a caller-chosen Ollama URL (auth + CONFIG_SECRET) ---------------


@pytest.fixture
def probes(monkeypatch):
    """Records every URL the route would contact; nothing touches the network."""
    seen: list[str] = []

    async def fake_ping(base_url):
        seen.append(base_url)
        return _FakeResult(ok=True)

    monkeypatch.setattr("backend.routes.config.ping_ollama", fake_ping)
    monkeypatch.setattr(settings, "ollama_base_url", "http://configured:11434")
    return seen


def _bearer(w, who):
    return {"Authorization": f"Bearer {w.tokens[who]}"}


FOREIGN = {"provider": "ollama", "ollama_base_url": "http://10.0.0.5:6379"}
URL = "/api/config/test-provider"


@pytest.mark.asyncio
async def test_test_provider_anonymous_is_401_with_auth_on(client, probes, monkeypatch):
    monkeypatch.setattr(settings, "paranoid_require_auth", True)
    for body in (FOREIGN, {"provider": "ollama"}):
        assert (await client.post(URL, json=body)).status_code == 401
    assert probes == []


@pytest.mark.asyncio
async def test_test_provider_foreign_url_refused_for_non_admin(client, probes, monkeypatch):
    monkeypatch.setattr(settings, "paranoid_require_auth", True)
    w = await build_world()
    for who in ("owner", "stranger", "pat_b"):
        r = await client.post(URL, json=FOREIGN, headers=_bearer(w, who))
        assert r.status_code == 403, who
    assert probes == []


@pytest.mark.asyncio
async def test_test_provider_foreign_url_refused_for_scoped_admin_pat(client, probes, monkeypatch):
    monkeypatch.setattr(settings, "paranoid_require_auth", True)
    w = await build_world()
    r = await client.post(URL, json=FOREIGN, headers=_bearer(w, "pat_admin_b"))
    assert r.status_code == 403
    assert probes == []


@pytest.mark.asyncio
async def test_test_provider_foreign_url_allowed_for_admin(client, probes, monkeypatch):
    monkeypatch.setattr(settings, "paranoid_require_auth", True)
    w = await build_world()
    r = await client.post(URL, json=FOREIGN, headers=_bearer(w, "admin"))
    assert r.status_code == 200
    assert probes == [FOREIGN["ollama_base_url"]]


@pytest.mark.asyncio
async def test_test_provider_configured_url_open_to_any_logged_in_user(client, probes, monkeypatch):
    monkeypatch.setattr(settings, "paranoid_require_auth", True)
    w = await build_world()
    bodies = (
        {"provider": "ollama"},
        {"provider": "ollama", "ollama_base_url": "http://configured:11434"},
    )
    for body in bodies:
        r = await client.post(URL, json=body, headers=_bearer(w, "stranger"))
        assert r.status_code == 200
    assert probes == ["http://configured:11434", "http://configured:11434"]


@pytest.mark.asyncio
async def test_test_provider_foreign_url_needs_config_secret(client, probes, monkeypatch):
    monkeypatch.setattr(settings, "config_secret", "s3cret")
    for headers in ({}, {"X-Config-Secret": "wrong"}):
        r = await client.post(URL, json=FOREIGN, headers=headers)
        assert r.status_code == 403
    assert probes == []

    r = await client.post(URL, json=FOREIGN, headers={"X-Config-Secret": "s3cret"})
    assert r.status_code == 200
    assert probes == [FOREIGN["ollama_base_url"]]


@pytest.mark.asyncio
async def test_test_provider_secret_not_needed_for_configured_url(client, probes, monkeypatch):
    monkeypatch.setattr(settings, "config_secret", "s3cret")
    r = await client.post(URL, json={"provider": "ollama"})
    assert r.status_code == 200
    assert probes == ["http://configured:11434"]


@pytest.mark.asyncio
async def test_test_provider_rate_limit_is_per_user_with_auth_on(client, probes, monkeypatch):
    """BB-21: one user using up their budget doesn't lock out another."""
    monkeypatch.setattr(settings, "paranoid_require_auth", True)
    w = await build_world()
    body = {"provider": "ollama"}
    for _ in range(healthcheck._RATE_MAX):
        r = await client.post(URL, json=body, headers=_bearer(w, "stranger"))
        assert r.status_code == 200
    assert (await client.post(URL, json=body, headers=_bearer(w, "stranger"))).status_code == 429
    assert (await client.post(URL, json=body, headers=_bearer(w, "admin"))).status_code == 200


@pytest.mark.asyncio
async def test_test_provider_rate_limit_is_per_ip_with_auth_off(client, probes):
    """BB-21: with auth off every caller is the anonymous admin, so the IP is the key."""
    body = {"provider": "ollama"}
    first = {"X-Forwarded-For": "203.0.113.1"}
    for _ in range(healthcheck._RATE_MAX):
        assert (await client.post(URL, json=body, headers=first)).status_code == 200
    assert (await client.post(URL, json=body, headers=first)).status_code == 429
    other = {"X-Forwarded-For": "203.0.113.2"}
    assert (await client.post(URL, json=body, headers=other)).status_code == 200


@pytest.mark.asyncio
async def test_test_provider_refusal_does_not_use_rate_limit(client, probes, monkeypatch):
    monkeypatch.setattr(settings, "paranoid_require_auth", True)
    w = await build_world()
    for _ in range(30):
        await client.post(URL, json=FOREIGN, headers=_bearer(w, "stranger"))
    r = await client.post(URL, json={"provider": "ollama"}, headers=_bearer(w, "stranger"))
    assert r.status_code == 200


# --- BB-20: a caller-chosen AWS profile / region (same rule as the Ollama URL) ---


@pytest.fixture
def aws_probes(monkeypatch):
    """Records the (region, profile) each Bedrock probe would use; no AWS call."""
    seen: list[tuple[str, str]] = []

    async def fake_ping(model, region, profile):
        seen.append((region, profile))
        return _FakeResult(ok=True)

    monkeypatch.setattr("backend.routes.config.ping_bedrock", fake_ping)
    monkeypatch.setattr(settings, "aws_region", "us-east-1")
    monkeypatch.setattr(settings, "aws_profile", "prod")
    return seen


OTHER_PROFILE = {"provider": "bedrock", "aws_profile": "other-team"}
OTHER_REGION = {"provider": "bedrock", "aws_region": "eu-central-1"}


@pytest.mark.asyncio
async def test_test_provider_other_aws_profile_or_region_refused_for_non_admin(
    client, aws_probes, monkeypatch
):
    monkeypatch.setattr(settings, "paranoid_require_auth", True)
    w = await build_world()
    for who in ("owner", "stranger", "pat_b", "pat_admin_b"):
        for body in (OTHER_PROFILE, OTHER_REGION):
            r = await client.post(URL, json=body, headers=_bearer(w, who))
            assert r.status_code == 403, (who, body)
    assert aws_probes == []


@pytest.mark.asyncio
async def test_test_provider_other_aws_profile_allowed_for_admin(client, aws_probes, monkeypatch):
    monkeypatch.setattr(settings, "paranoid_require_auth", True)
    w = await build_world()
    r = await client.post(URL, json=OTHER_PROFILE, headers=_bearer(w, "admin"))
    assert r.status_code == 200
    assert aws_probes == [("us-east-1", "other-team")]


@pytest.mark.asyncio
async def test_test_provider_configured_aws_settings_open_to_any_logged_in_user(
    client, aws_probes, monkeypatch
):
    """Settings sends the current region and profile back with the probe; that
    (or omitting them) must keep working for every logged-in user."""
    monkeypatch.setattr(settings, "paranoid_require_auth", True)
    w = await build_world()
    bodies = (
        {"provider": "bedrock"},
        {"provider": "bedrock", "aws_region": "us-east-1", "aws_profile": "prod"},
    )
    for body in bodies:
        r = await client.post(URL, json=body, headers=_bearer(w, "stranger"))
        assert r.status_code == 200
    assert aws_probes == [("us-east-1", "prod"), ("us-east-1", "prod")]


@pytest.mark.asyncio
async def test_test_provider_other_aws_profile_needs_config_secret(client, aws_probes, monkeypatch):
    monkeypatch.setattr(settings, "config_secret", "s3cret")
    for headers in ({}, {"X-Config-Secret": "wrong"}):
        r = await client.post(URL, json=OTHER_PROFILE, headers=headers)
        assert r.status_code == 403
    assert aws_probes == []

    r = await client.post(URL, json=OTHER_PROFILE, headers={"X-Config-Secret": "s3cret"})
    assert r.status_code == 200
    assert aws_probes == [("us-east-1", "other-team")]
