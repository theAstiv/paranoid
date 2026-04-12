"""Tests for /api/models routes.

Uses AsyncClient with ASGITransport — no lifespan triggered.
The test_db fixture sets up DB state before each test so db.get() works.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from backend.db import crud
from backend.main import app


@pytest.fixture
async def client(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def saved_model(test_db):
    """Create a model in the DB and return its record."""
    model_id = await crud.create_threat_model(
        title="Auth Service",
        description="OAuth2 authentication service with JWT tokens and Redis sessions",
        provider="anthropic",
        model="claude-sonnet-4",
        framework="STRIDE",
        iteration_count=3,
    )
    return await crud.get_threat_model(model_id)


# ---------------------------------------------------------------------------
# POST /api/models
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_model_returns_201(client):
    resp = await client.post(
        "/api/models/",
        json={
            "title": "Payment Gateway",
            "description": "Stripe-backed payment processing service with PCI-DSS scope",
            "framework": "STRIDE",
            "iteration_count": 2,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Payment Gateway"
    assert data["framework"] == "STRIDE"
    assert data["status"] == "pending"
    assert "id" in data


@pytest.mark.asyncio
async def test_create_model_defaults_provider_from_settings(client):
    resp = await client.post(
        "/api/models/",
        json={
            "title": "API Gateway",
            "description": "Kong API gateway with rate limiting and mTLS",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    # provider should be set (defaults to settings.default_provider)
    assert data["provider"] in ("anthropic", "openai", "ollama")


@pytest.mark.asyncio
async def test_create_model_validates_short_description(client):
    resp = await client.post(
        "/api/models/",
        json={"title": "X", "description": "short"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/models
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_models_empty(client):
    resp = await client.get("/api/models/")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_models_returns_created(client, saved_model):
    resp = await client.get("/api/models/")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["id"] == saved_model["id"]
    assert "threat_count" in rows[0]


@pytest.mark.asyncio
async def test_list_models_framework_filter(client, test_db):
    await crud.create_threat_model(
        title="A",
        description="STRIDE model for the first service",
        provider="anthropic",
        model="m",
        framework="STRIDE",
    )
    await crud.create_threat_model(
        title="B",
        description="MAESTRO model for AI pipeline",
        provider="anthropic",
        model="m",
        framework="MAESTRO",
    )

    resp = await client.get("/api/models/?framework=MAESTRO")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["framework"] == "MAESTRO"


@pytest.mark.asyncio
async def test_list_models_status_filter(client, test_db):
    mid = await crud.create_threat_model(
        title="C",
        description="Completed service model for filtering tests",
        provider="anthropic",
        model="m",
    )
    await crud.update_threat_model_status(mid, "completed")

    resp = await client.get("/api/models/?status=completed")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["status"] == "completed"


# ---------------------------------------------------------------------------
# GET /api/models/{model_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_model_returns_model_and_threats(client, saved_model, test_db):
    model_id = saved_model["id"]
    await crud.create_threat(
        model_id=model_id,
        name="Token Forgery",
        description="Attacker forges JWT tokens to gain unauthorized access to user accounts",
        target="Auth Service",
        impact="High",
        likelihood="Medium",
        mitigations=["Validate signatures", "Use short expiry"],
        stride_category="Spoofing",
    )

    resp = await client.get(f"/api/models/{model_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == model_id
    assert len(data["threats"]) == 1
    assert data["threats"][0]["name"] == "Token Forgery"


@pytest.mark.asyncio
async def test_get_model_404(client):
    resp = await client.get("/api/models/nonexistent-id")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /api/models/{model_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_model_title(client, saved_model):
    model_id = saved_model["id"]
    resp = await client.patch(
        f"/api/models/{model_id}",
        json={"title": "Renamed Auth Service"},
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "Renamed Auth Service"


@pytest.mark.asyncio
async def test_update_model_status(client, saved_model):
    model_id = saved_model["id"]
    resp = await client.patch(
        f"/api/models/{model_id}",
        json={"status": "completed"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_update_model_404(client):
    resp = await client.patch("/api/models/bad-id", json={"title": "X"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/models/{model_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_model_returns_204(client, saved_model):
    model_id = saved_model["id"]
    resp = await client.delete(f"/api/models/{model_id}")
    assert resp.status_code == 204

    # Confirm gone
    resp2 = await client.get(f"/api/models/{model_id}")
    assert resp2.status_code == 404


@pytest.mark.asyncio
async def test_delete_model_404(client):
    resp = await client.delete("/api/models/nonexistent")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET sub-resources
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_threats_empty(client, saved_model):
    resp = await client.get(f"/api/models/{saved_model['id']}/threats")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_threats_with_status_filter(client, saved_model, test_db):
    model_id = saved_model["id"]
    tid = await crud.create_threat(
        model_id=model_id,
        name="SQL Injection",
        description="Attacker injects SQL into query parameters to exfiltrate database records",
        target="DB",
        impact="High",
        likelihood="High",
        mitigations=["Parameterized queries"],
        stride_category="Tampering",
    )
    await crud.update_threat_status(tid, "approved")

    resp = await client.get(f"/api/models/{model_id}/threats?status=approved")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


@pytest.mark.asyncio
async def test_list_threats_invalid_status(client, saved_model):
    resp = await client.get(f"/api/models/{saved_model['id']}/threats?status=garbage")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_assets_404(client):
    resp = await client.get("/api/models/bad-id/assets")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_flows_returns_empty(client, saved_model):
    resp = await client.get(f"/api/models/{saved_model['id']}/flows")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_trust_boundaries_returns_empty(client, saved_model):
    resp = await client.get(f"/api/models/{saved_model['id']}/trust-boundaries")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_stats_returns_dict(client, saved_model):
    resp = await client.get(f"/api/models/{saved_model['id']}/stats")
    assert resp.status_code == 200
    # Empty stats is still a valid dict (may be {})
    assert isinstance(resp.json(), dict)


@pytest.mark.asyncio
async def test_get_stats_404(client):
    resp = await client.get("/api/models/bad-id/stats")
    assert resp.status_code == 404
