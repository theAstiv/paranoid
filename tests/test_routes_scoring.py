"""Tests for POST /api/cvss/score — stateless CVSS v3.1 recomputation."""

import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app


@pytest.fixture
async def client(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_score_valid_vector_returns_score_and_severity(client):
    resp = await client.post(
        "/api/cvss/score", json={"vector": "AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["score"] == pytest.approx(9.8)
    assert data["severity"] == "critical"


@pytest.mark.asyncio
async def test_score_canonicalizes_metric_order(client):
    """Metric order and the optional CVSS:3.1/ prefix don't affect the score —
    mirrors UpdateThreatRequest.cvss_vector's validator."""
    resp = await client.post(
        "/api/cvss/score", json={"vector": "CVSS:3.1/A:H/I:H/C:H/S:U/UI:N/PR:N/AC:L/AV:N"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["score"] == pytest.approx(9.8)
    assert data["severity"] == "critical"


@pytest.mark.asyncio
async def test_score_malformed_vector_returns_422(client):
    resp = await client.post("/api/cvss/score", json={"vector": "not a vector"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_score_missing_vector_returns_422(client):
    resp = await client.post("/api/cvss/score", json={})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_score_low_severity_vector(client):
    resp = await client.post(
        "/api/cvss/score", json={"vector": "AV:P/AC:H/PR:H/UI:R/S:U/C:L/I:N/A:N"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["severity"] in ("low", "none")
