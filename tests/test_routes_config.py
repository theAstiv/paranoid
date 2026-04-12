"""Tests for GET /api/config."""

import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app


@pytest.fixture
async def client(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_config_returns_200(client):
    resp = await client.get("/api/config/")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_config_contains_expected_keys(client):
    resp = await client.get("/api/config/")
    data = resp.json()
    for key in ("version", "provider", "model", "default_iterations", "log_level"):
        assert key in data, f"Missing key: {key}"


@pytest.mark.asyncio
async def test_config_no_api_keys(client):
    resp = await client.get("/api/config/")
    data = resp.json()
    body = str(data)
    assert "api_key" not in body
    assert "anthropic_api_key" not in body
    assert "openai_api_key" not in body


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
