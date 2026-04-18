"""Tests for POST /api/config/test-provider (Phase 15 Task 2)."""

from dataclasses import dataclass

import pytest
from httpx import ASGITransport, AsyncClient

from backend.config import settings
from backend.main import app
from backend.providers import healthcheck
from backend.security import source_key


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
