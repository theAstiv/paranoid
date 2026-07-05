"""Tests for GET /api/projects/{project_id}/dashboard (Phase 7).

Mocks at the usage site (backend.routes.dashboard.crud_dashboard.*,
backend.routes.dashboard.crud_activity.*) plus the shared
_require_member gate (backend.routes.projects.crud_projects.get_user_role_in_project),
mirroring the pattern already used in test_routes_projects.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app


_STATS = {
    "model_count": 3,
    "open_threats": 12,
    "pending_review": 2,
    "member_count": 4,
    "last_run_at": "2026-07-05T00:00:00",
}
_SEVERITY = {"critical": 1, "high": 3, "medium": 5, "low": 3}
_ACTIVITY = [{"id": "a1", "action": "created", "entity_type": "model", "entity_id": "m1"}]
_ASSIGNED = [
    {"id": "t1", "name": "SQLi", "dread_score": 9.0, "model_id": "m1", "model_title": "Model"}
]


@pytest.fixture
async def client(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_get_dashboard_returns_200_with_all_sections(client):
    with (
        patch(
            "backend.routes.dashboard.crud_dashboard.get_dashboard_stats",
            new=AsyncMock(return_value=_STATS),
        ),
        patch(
            "backend.routes.dashboard.crud_dashboard.get_severity_breakdown",
            new=AsyncMock(return_value=_SEVERITY),
        ),
        patch(
            "backend.routes.dashboard.crud_activity.list_activity",
            new=AsyncMock(return_value=_ACTIVITY),
        ),
        patch(
            "backend.routes.dashboard.crud_dashboard.get_assigned_threats",
            new=AsyncMock(return_value=_ASSIGNED),
        ),
    ):
        res = await client.get("/api/projects/proj-uuid-1/dashboard")

    assert res.status_code == 200
    body = res.json()
    assert body["stats"] == _STATS
    assert body["severity"] == _SEVERITY
    assert body["activity"] == _ACTIVITY
    assert body["assigned_to_you"] == _ASSIGNED


@pytest.mark.asyncio
async def test_get_dashboard_non_member_returns_403_when_auth_enabled(client):
    """Non-member user should get 403 when auth is required (same gate as other project routes)."""
    from backend.auth.dependencies import get_current_user as _gcu

    non_member = {
        "id": "other-user-uuid",
        "username": "stranger",
        "email": "stranger@test.local",
        "is_admin": False,
        "is_active": True,
        "display_name": "Stranger",
    }
    app.dependency_overrides[_gcu] = lambda: non_member

    try:
        with (
            patch(
                "backend.routes.projects.crud_projects.get_user_role_in_project",
                new=AsyncMock(return_value=None),
            ),
            patch("backend.config.settings") as mock_settings,
        ):
            mock_settings.paranoid_require_auth = True
            res = await client.get("/api/projects/proj-uuid-1/dashboard")
    finally:
        app.dependency_overrides.pop(_gcu, None)

    assert res.status_code == 403
