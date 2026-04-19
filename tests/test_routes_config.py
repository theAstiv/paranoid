"""Tests for /api/config GET + PATCH (Phase 15 Task 1)."""

import pytest
from httpx import ASGITransport, AsyncClient

from backend.config import settings
from backend.db.crud import get_config_value
from backend.main import app
from backend.security import source_key


@pytest.fixture
async def client(test_db, tmp_path, monkeypatch):
    # Route the source-key file fallback into the per-test tmp dir so tests
    # never touch the user's real ./data directory and each test starts with
    # a fresh key.
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "paranoid.db"))
    monkeypatch.setattr(settings, "config_secret", "")
    monkeypatch.delenv("CONFIG_SECRET", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "default_provider", "anthropic")
    source_key._reset_cache_for_tests()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    source_key._reset_cache_for_tests()


@pytest.mark.asyncio
async def test_config_returns_200(client):
    resp = await client.get("/api/config/")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_config_contains_expected_keys(client):
    resp = await client.get("/api/config/")
    data = resp.json()
    for key in (
        "version",
        "provider",
        "model",
        "default_iterations",
        "log_level",
        "anthropic_api_key_set",
        "anthropic_api_key_source",
        "first_run",
    ):
        assert key in data, f"Missing key: {key}"


@pytest.mark.asyncio
async def test_get_never_leaks_key_values(client, monkeypatch):
    """GET must expose only presence+source booleans, never the raw value."""
    # Store a value via PATCH so we can verify a later GET doesn't echo it.
    secret_value = "sk-ant-supersecret123"  # noqa: S105 — test fixture, not a real credential
    resp = await client.patch("/api/config/", json={"anthropic_api_key": secret_value})
    assert resp.status_code == 200

    resp = await client.get("/api/config/")
    body = resp.text
    assert secret_value not in body
    data = resp.json()
    assert data["anthropic_api_key_set"] is True
    assert data["anthropic_api_key_source"] == "db"


@pytest.mark.asyncio
async def test_env_sourced_field_rejects_patch(client, monkeypatch):
    """When the env var is set, PATCH to the same key returns 400."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fromenv")
    resp = await client.patch("/api/config/", json={"anthropic_api_key": "sk-ant-other"})
    assert resp.status_code == 400
    assert "environment variable" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_db_sourced_field_accepts_patch(client):
    """No env → PATCH persists the value (encrypted) and updates settings live."""
    resp = await client.patch("/api/config/", json={"anthropic_api_key": "sk-ant-live"})
    assert resp.status_code == 200

    stored = await get_config_value("anthropic_api_key")
    assert stored == "sk-ant-live"
    assert settings.anthropic_api_key == "sk-ant-live"


@pytest.mark.asyncio
async def test_patch_response_includes_recomputed_first_run(client):
    """PATCH that saves a key must flip first_run → False in the same response."""
    resp = await client.get("/api/config/")
    assert resp.json()["first_run"] is True

    resp = await client.patch("/api/config/", json={"anthropic_api_key": "sk-ant-abc"})
    assert resp.status_code == 200
    assert resp.json()["first_run"] is False

    # Switching default provider to one without a key flips it back.
    resp = await client.patch("/api/config/", json={"default_provider": "openai"})
    assert resp.status_code == 200
    assert resp.json()["first_run"] is True


@pytest.mark.asyncio
async def test_empty_string_rejected(client):
    """Empty string key value → 400 with the documented message."""
    resp = await client.patch("/api/config/", json={"anthropic_api_key": ""})
    assert resp.status_code == 400
    assert "use null to clear" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_whitespace_only_key_rejected(client):
    """Whitespace-only value collapses to empty after trim → 400."""
    resp = await client.patch("/api/config/", json={"anthropic_api_key": "   \n\t"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_key_stored_value_is_trimmed(client):
    """Trailing newlines from a pasted key are stripped before storage."""
    resp = await client.patch("/api/config/", json={"anthropic_api_key": "  sk-ant-trimmed\n"})
    assert resp.status_code == 200
    assert await get_config_value("anthropic_api_key") == "sk-ant-trimmed"


@pytest.mark.asyncio
async def test_explicit_null_clears_key(client):
    """Explicit null in the request body deletes the DB row."""
    await client.patch("/api/config/", json={"anthropic_api_key": "sk-ant-zzz"})
    assert await get_config_value("anthropic_api_key") == "sk-ant-zzz"

    resp = await client.patch("/api/config/", json={"anthropic_api_key": None})
    assert resp.status_code == 200
    assert await get_config_value("anthropic_api_key") is None
    assert resp.json()["anthropic_api_key_set"] is False


@pytest.mark.asyncio
async def test_omitted_field_is_noop(client):
    """Field absent from the body leaves the stored value alone."""
    await client.patch("/api/config/", json={"anthropic_api_key": "sk-ant-stable"})
    resp = await client.patch("/api/config/", json={"default_iterations": 5})
    assert resp.status_code == 200
    assert await get_config_value("anthropic_api_key") == "sk-ant-stable"


@pytest.mark.asyncio
async def test_first_run_true_when_no_anthropic_key(client):
    resp = await client.get("/api/config/")
    assert resp.json()["first_run"] is True


@pytest.mark.asyncio
async def test_first_run_false_after_key_set(client):
    await client.patch("/api/config/", json={"anthropic_api_key": "sk-ant-val"})
    resp = await client.get("/api/config/")
    assert resp.json()["first_run"] is False


@pytest.mark.asyncio
async def test_first_run_false_for_ollama(client, monkeypatch):
    """Ollama is exempt from first-run because it has no API key concept."""
    monkeypatch.setattr(settings, "default_provider", "ollama")
    resp = await client.get("/api/config/")
    assert resp.json()["first_run"] is False


@pytest.mark.asyncio
async def test_config_version_is_string(client):
    resp = await client.get("/api/config/")
    assert isinstance(resp.json()["version"], str)


@pytest.mark.asyncio
async def test_config_iterations_are_integers(client):
    resp = await client.get("/api/config/")
    data = resp.json()
    assert isinstance(data["default_iterations"], int)
    assert isinstance(data["max_iteration_count"], int)
    assert data["max_iteration_count"] >= data["default_iterations"]


def test_api_key_fields_in_sync_with_request_model():
    """API_KEY_FIELDS and UpdateConfigRequest must declare the same providers.

    Catches the drift case where someone adds a provider to the hydration
    map but forgets the matching PATCH body field (or vice versa).
    """
    from backend.config import API_KEY_FIELDS
    from backend.routes.config import UpdateConfigRequest

    map_keys = {db_key for _env, db_key in API_KEY_FIELDS.values()}
    model_keys = {name for name in UpdateConfigRequest.model_fields if name.endswith("_api_key")}
    assert map_keys == model_keys, (
        f"API_KEY_FIELDS and UpdateConfigRequest diverged: "
        f"only in map={map_keys - model_keys}, only in model={model_keys - map_keys}"
    )
