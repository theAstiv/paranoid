"""Tests for POST /api/threats/bulk-status endpoint."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.auth.dependencies import get_current_user
from backend.db import crud
from backend.main import app


@pytest.fixture
async def client(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def model_with_threats(test_db):
    """Create a model with 3 threats and return (model_id, [threat_ids])."""
    model_id = await crud.create_threat_model(
        title="Bulk Test Model",
        description="Model for bulk status testing",
        provider="anthropic",
        model="claude-sonnet-4",
    )
    threat_ids = []
    for i in range(3):
        tid = await crud.create_threat(
            model_id=model_id,
            name=f"Threat {i + 1}",
            description=f"Test threat number {i + 1} for bulk operations",
            target=f"Component {i + 1}",
            impact="High",
            likelihood="Medium",
            mitigations=["Mitigation A"],
            stride_category="Tampering",
        )
        threat_ids.append(tid)
    return model_id, threat_ids


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_approve_updates_all(client, model_with_threats):
    _, threat_ids = model_with_threats
    resp = await client.post(
        "/api/threats/bulk-status",
        json={"threat_ids": threat_ids, "status": "approved"},
    )
    assert resp.status_code == 200
    assert resp.json()["updated"] == 3

    for tid in threat_ids:
        threat = await crud.get_threat(tid)
        assert threat["status"] == "approved"


@pytest.mark.asyncio
async def test_bulk_reject(client, model_with_threats):
    _, threat_ids = model_with_threats
    resp = await client.post(
        "/api/threats/bulk-status",
        json={"threat_ids": threat_ids, "status": "rejected"},
    )
    assert resp.status_code == 200
    assert resp.json()["updated"] == 3


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_threat_id_returns_404(client, model_with_threats):
    _, threat_ids = model_with_threats
    resp = await client.post(
        "/api/threats/bulk-status",
        json={"threat_ids": [threat_ids[0], "nonexistent-id"], "status": "approved"},
    )
    assert resp.status_code == 404
    assert "nonexistent-id" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_empty_threat_ids_returns_422(client, test_db):
    resp = await client.post(
        "/api/threats/bulk-status",
        json={"threat_ids": [], "status": "approved"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_threats_from_different_models_returns_400(client, test_db):
    model_a = await crud.create_threat_model(
        title="Model A",
        description="A",
        provider="anthropic",
        model="claude-sonnet-4",
    )
    model_b = await crud.create_threat_model(
        title="Model B",
        description="B",
        provider="anthropic",
        model="claude-sonnet-4",
    )
    tid_a = await crud.create_threat(
        model_id=model_a,
        name="T-A",
        description="x",
        target="X",
        impact="High",
        likelihood="High",
        mitigations=[],
        stride_category="Spoofing",
    )
    tid_b = await crud.create_threat(
        model_id=model_b,
        name="T-B",
        description="y",
        target="Y",
        impact="High",
        likelihood="High",
        mitigations=[],
        stride_category="Spoofing",
    )
    resp = await client.post(
        "/api/threats/bulk-status",
        json={"threat_ids": [tid_a, tid_b], "status": "approved"},
    )
    assert resp.status_code == 400
    assert "same model" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_viewer_role_returns_403(test_db, model_with_threats):
    """A user with only viewer role should be rejected."""
    _, threat_ids = model_with_threats

    viewer_user = {"id": "viewer-user", "username": "viewer", "is_admin": False, "is_active": True}

    async def _viewer_override():
        return viewer_user

    app.dependency_overrides[get_current_user] = _viewer_override
    try:
        with (
            patch("backend.config.settings.paranoid_require_auth", True),
            patch(
                "backend.routes.threats.crud_projects.resolve_project_id_from_model",
                new=AsyncMock(return_value="proj-1"),
            ),
            patch(
                "backend.routes.threats.crud_projects.get_user_role_in_project",
                new=AsyncMock(return_value="viewer"),
            ),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                resp = await c.post(
                    "/api/threats/bulk-status",
                    json={"threat_ids": threat_ids, "status": "approved"},
                )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_admin_bypasses_role_check(test_db, model_with_threats):
    """An admin user should bypass the role check even with require_auth=True."""
    _, threat_ids = model_with_threats

    admin_user = {"id": "admin-user", "username": "admin", "is_admin": True, "is_active": True}

    async def _admin_override():
        return admin_user

    app.dependency_overrides[get_current_user] = _admin_override
    try:
        with patch("backend.config.settings.paranoid_require_auth", True):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                resp = await c.post(
                    "/api/threats/bulk-status",
                    json={"threat_ids": threat_ids, "status": "approved"},
                )
        assert resp.status_code == 200
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_anon_mode_allows_without_role(client, model_with_threats):
    """When paranoid_require_auth is false, any user passes."""
    _, threat_ids = model_with_threats
    resp = await client.post(
        "/api/threats/bulk-status",
        json={"threat_ids": threat_ids, "status": "approved"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# RAG vector handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_approve_embeds_vectors(client, model_with_threats):
    """Approving previously-pending threats should embed each one."""
    _, threat_ids = model_with_threats

    with (
        patch(
            "backend.routes.threats.crud_projects.resolve_project_id_from_model",
            new=AsyncMock(return_value="proj-1"),
        ),
        patch(
            "backend.routes.threats.vectors.upsert_threat_vector",
            new=AsyncMock(),
        ) as mock_upsert,
    ):
        resp = await client.post(
            "/api/threats/bulk-status",
            json={"threat_ids": threat_ids, "status": "approved"},
        )

    assert resp.status_code == 200
    assert mock_upsert.await_count == 3


@pytest.mark.asyncio
async def test_bulk_approve_already_approved_no_duplicate_embed(client, model_with_threats):
    """Threats already approved should not be re-embedded."""
    _, threat_ids = model_with_threats

    # Pre-approve them
    await crud.bulk_update_threat_status(threat_ids, "approved")

    with (
        patch(
            "backend.routes.threats.crud_projects.resolve_project_id_from_model",
            new=AsyncMock(return_value="proj-1"),
        ),
        patch(
            "backend.routes.threats.vectors.upsert_threat_vector",
            new=AsyncMock(),
        ) as mock_upsert,
    ):
        resp = await client.post(
            "/api/threats/bulk-status",
            json={"threat_ids": threat_ids, "status": "approved"},
        )

    assert resp.status_code == 200
    assert mock_upsert.await_count == 0
