"""Tests for /api/threats routes.

Covers CRUD, status patching, and 404 paths.
Attack tree / test case generation endpoints require a live LLM provider
and are not tested here (covered by pipeline integration tests).
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
async def saved_threat(test_db):
    """Create a model + threat and return the threat record."""
    model_id = await crud.create_threat_model(
        title="Auth Service",
        description="OAuth2 service with JWT and Redis session store",
        provider="anthropic",
        model="claude-sonnet-4",
    )
    threat_id = await crud.create_threat(
        model_id=model_id,
        name="Session Hijacking",
        description=(
            "An attacker steals a valid session token via XSS or network sniffing "
            "to impersonate an authenticated user and gain unauthorized access"
        ),
        target="Session Store",
        impact="High",
        likelihood="Medium",
        mitigations=["HttpOnly cookies", "Secure flag", "CSRF tokens"],
        stride_category="Spoofing",
    )
    return await crud.get_threat(threat_id)


# ---------------------------------------------------------------------------
# GET /api/threats/{threat_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_threat_returns_record(client, saved_threat):
    resp = await client.get(f"/api/threats/{saved_threat['id']}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == saved_threat["id"]
    assert data["name"] == "Session Hijacking"
    assert isinstance(data["mitigations"], list)


@pytest.mark.asyncio
async def test_get_threat_404(client):
    resp = await client.get("/api/threats/nonexistent-id")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /api/threats/{threat_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_threat_status(client, saved_threat):
    resp = await client.patch(
        f"/api/threats/{saved_threat['id']}",
        json={"status": "approved"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"


@pytest.mark.asyncio
async def test_patch_threat_name_and_target(client, saved_threat):
    resp = await client.patch(
        f"/api/threats/{saved_threat['id']}",
        json={"name": "Cookie Theft", "target": "Browser"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Cookie Theft"
    assert data["target"] == "Browser"


@pytest.mark.asyncio
async def test_patch_threat_mitigations(client, saved_threat):
    new_mitigations = ["Rotate tokens", "Short TTL", "IP binding"]
    resp = await client.patch(
        f"/api/threats/{saved_threat['id']}",
        json={"mitigations": new_mitigations},
    )
    assert resp.status_code == 200
    assert resp.json()["mitigations"] == new_mitigations


@pytest.mark.asyncio
async def test_patch_threat_dread_scores(client, saved_threat):
    resp = await client.patch(
        f"/api/threats/{saved_threat['id']}",
        json={
            "dread_damage": 8.0,
            "dread_reproducibility": 7.0,
            "dread_exploitability": 6.0,
            "dread_affected_users": 9.0,
            "dread_discoverability": 5.0,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["dread_damage"] == 8.0
    assert data["dread_affected_users"] == 9.0


@pytest.mark.asyncio
async def test_patch_threat_dread_out_of_range(client, saved_threat):
    resp = await client.patch(
        f"/api/threats/{saved_threat['id']}",
        json={"dread_damage": 11.0},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_threat_invalid_status(client, saved_threat):
    resp = await client.patch(
        f"/api/threats/{saved_threat['id']}",
        json={"status": "invalid_status"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_threat_404(client):
    resp = await client.patch("/api/threats/nonexistent", json={"status": "approved"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/threats/{threat_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_threat_returns_204(client, saved_threat):
    resp = await client.delete(f"/api/threats/{saved_threat['id']}")
    assert resp.status_code == 204

    resp2 = await client.get(f"/api/threats/{saved_threat['id']}")
    assert resp2.status_code == 404


@pytest.mark.asyncio
async def test_delete_threat_404(client):
    resp = await client.delete("/api/threats/nonexistent")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET sub-resources (attack-trees, test-cases) — list endpoints only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_attack_trees_empty(client, saved_threat):
    resp = await client.get(f"/api/threats/{saved_threat['id']}/attack-trees")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_attack_trees_404_on_bad_threat(client):
    resp = await client.get("/api/threats/bad-id/attack-trees")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_test_cases_empty(client, saved_threat):
    resp = await client.get(f"/api/threats/{saved_threat['id']}/test-cases")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_test_cases_404_on_bad_threat(client):
    resp = await client.get("/api/threats/bad-id/test-cases")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_attack_trees_shows_saved_tree(client, saved_threat, test_db):
    """Attack tree saved directly via CRUD appears in the list endpoint."""
    tree_id = await crud.create_attack_tree(
        threat_id=saved_threat["id"],
        mermaid_source="graph TD\n  A[Attacker] --> B[Steal Cookie]",
    )

    resp = await client.get(f"/api/threats/{saved_threat['id']}/attack-trees")
    assert resp.status_code == 200
    trees = resp.json()
    assert len(trees) == 1
    assert trees[0]["id"] == tree_id
    assert "mermaid_source" in trees[0]


@pytest.mark.asyncio
async def test_list_test_cases_shows_saved_case(client, saved_threat, test_db):
    """Test case saved directly via CRUD appears in the list endpoint."""
    case_id = await crud.create_test_case(
        threat_id=saved_threat["id"],
        gherkin_source="Feature: Session security\n  Scenario: Cookie theft",
    )

    resp = await client.get(f"/api/threats/{saved_threat['id']}/test-cases")
    assert resp.status_code == 200
    cases = resp.json()
    assert len(cases) == 1
    assert cases[0]["id"] == case_id
    assert "gherkin_source" in cases[0]
