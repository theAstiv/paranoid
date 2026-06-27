"""Tests for /api/projects/* and /api/users routes (Phase 2).

Mocks at the usage site (backend.routes.projects.*) so inner dependencies
do not require a real database.  The PARANOID_REQUIRE_AUTH=false default
makes get_current_user return the synthetic _ANON_ADMIN user, which is
is_admin=True — giving full access in all anon-mode tests.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_ANON_ADMIN_ID = "00000000-0000-0000-0000-000000000001"

_PROJECT = {
    "id": "proj-uuid-1",
    "name": "Test Project",
    "description": "A test project",
    "is_archived": 0,
    "created_by": _ANON_ADMIN_ID,
    "created_at": "2026-01-01T00:00:00",
    "updated_at": "2026-01-01T00:00:00",
    "default_provider": None,
    "default_model": None,
    "default_iterations": None,
    "default_temperature": None,
}

_MEMBER = {
    "id": "member-uuid-1",
    "project_id": "proj-uuid-1",
    "user_id": _ANON_ADMIN_ID,
    "role": "owner",
    "created_at": "2026-01-01T00:00:00",
    "username": "admin",
    "email": "admin@test.local",
    "display_name": "Administrator",
}

_USER = {
    "id": "user-plain-uuid",
    "username": "alice",
    "email": "alice@test.local",
    "display_name": "Alice",
    "is_active": 1,
    "is_admin": 0,
    "created_at": "2026-01-01T00:00:00",
    "updated_at": "2026-01-01T00:00:00",
    "last_login_at": None,
}

_INVITATION = {
    "id": "inv-uuid-1",
    "project_id": "proj-uuid-1",
    "invited_email": "bob@test.local",
    "role": "viewer",
    "invited_by": _ANON_ADMIN_ID,
    "status": "pending",
    "created_at": "2026-01-01T00:00:00",
    "expires_at": "2026-01-08T00:00:00",
}


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
async def client(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# POST /api/projects
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_project_returns_201(client):
    with patch(
        "backend.routes.projects.crud_projects.create_project", new=AsyncMock(return_value=_PROJECT)
    ):
        res = await client.post("/api/projects", json={"name": "Test Project"})
    assert res.status_code == 201
    assert res.json()["name"] == "Test Project"


@pytest.mark.asyncio
async def test_create_project_missing_name_returns_422(client):
    res = await client.post("/api/projects", json={})
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_create_project_blank_name_returns_422(client):
    res = await client.post("/api/projects", json={"name": "  "})
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/projects
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_projects_admin_returns_all(client):
    # Anon admin → list_all_projects
    with patch(
        "backend.routes.projects.crud_projects.list_all_projects",
        new=AsyncMock(return_value=[_PROJECT]),
    ):
        res = await client.get("/api/projects")
    assert res.status_code == 200
    assert isinstance(res.json(), list)
    assert res.json()[0]["id"] == "proj-uuid-1"


# ---------------------------------------------------------------------------
# GET /api/projects/{project_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_project_returns_200(client):
    with patch(
        "backend.routes.projects.crud_projects.get_project", new=AsyncMock(return_value=_PROJECT)
    ):
        res = await client.get("/api/projects/proj-uuid-1")
    assert res.status_code == 200
    assert res.json()["id"] == "proj-uuid-1"


@pytest.mark.asyncio
async def test_get_project_not_found_returns_404(client):
    with patch(
        "backend.routes.projects.crud_projects.get_project", new=AsyncMock(return_value=None)
    ):
        res = await client.get("/api/projects/nonexistent")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /api/projects/{project_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_project_returns_200(client):
    updated = {**_PROJECT, "name": "Renamed", "description": "Updated"}
    with patch(
        "backend.routes.projects.crud_projects.update_project", new=AsyncMock(return_value=updated)
    ):
        res = await client.patch("/api/projects/proj-uuid-1", json={"name": "Renamed"})
    assert res.status_code == 200
    assert res.json()["name"] == "Renamed"


@pytest.mark.asyncio
async def test_update_project_not_found_returns_404(client):
    with patch(
        "backend.routes.projects.crud_projects.update_project", new=AsyncMock(return_value=None)
    ):
        res = await client.patch("/api/projects/nonexistent", json={"name": "X"})
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/projects/{project_id}  (soft-archive)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_archive_project_returns_204(client):
    with patch(
        "backend.routes.projects.crud_projects.archive_project", new=AsyncMock(return_value=None)
    ):
        res = await client.delete("/api/projects/proj-uuid-1")
    assert res.status_code == 204


# ---------------------------------------------------------------------------
# GET /api/projects/{project_id}/members
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_members_returns_200(client):
    with patch(
        "backend.routes.projects.crud_projects.list_members", new=AsyncMock(return_value=[_MEMBER])
    ):
        res = await client.get("/api/projects/proj-uuid-1/members")
    assert res.status_code == 200
    assert res.json()[0]["role"] == "owner"


# ---------------------------------------------------------------------------
# POST /api/projects/{project_id}/members
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_member_returns_201(client):
    viewer_member = {**_MEMBER, "role": "viewer"}
    with patch(
        "backend.routes.projects.crud_projects.add_member",
        new=AsyncMock(return_value=viewer_member),
    ):
        res = await client.post(
            "/api/projects/proj-uuid-1/members",
            json={"user_id": "user-plain-uuid", "role": "viewer"},
        )
    assert res.status_code == 201
    assert res.json()["role"] == "viewer"


@pytest.mark.asyncio
async def test_add_member_missing_user_id_returns_422(client):
    res = await client.post("/api/projects/proj-uuid-1/members", json={"role": "viewer"})
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_add_member_invalid_role_returns_422(client):
    res = await client.post(
        "/api/projects/proj-uuid-1/members",
        json={"user_id": "user-plain-uuid", "role": "superuser"},
    )
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# PATCH /api/projects/{project_id}/members/{user_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_member_role_returns_200(client):
    updated = {**_MEMBER, "role": "editor"}
    with patch(
        "backend.routes.projects.crud_projects.update_member_role",
        new=AsyncMock(return_value=updated),
    ):
        res = await client.patch(
            f"/api/projects/proj-uuid-1/members/{_ANON_ADMIN_ID}",
            json={"role": "editor"},
        )
    assert res.status_code == 200
    assert res.json()["role"] == "editor"


@pytest.mark.asyncio
async def test_update_member_role_not_found_returns_404(client):
    with patch(
        "backend.routes.projects.crud_projects.update_member_role",
        new=AsyncMock(return_value=None),
    ):
        res = await client.patch(
            "/api/projects/proj-uuid-1/members/nonexistent",
            json={"role": "editor"},
        )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_update_member_invalid_role_returns_422(client):
    res = await client.patch(
        f"/api/projects/proj-uuid-1/members/{_ANON_ADMIN_ID}",
        json={"role": "superuser"},
    )
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /api/projects/{project_id}/members/{user_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remove_member_returns_204(client):
    with patch(
        "backend.routes.projects.crud_projects.remove_member",
        new=AsyncMock(return_value=None),
    ):
        res = await client.delete(f"/api/projects/proj-uuid-1/members/{_ANON_ADMIN_ID}")
    assert res.status_code == 204


@pytest.mark.asyncio
async def test_remove_last_owner_returns_409(client):
    with patch(
        "backend.routes.projects.crud_projects.remove_member",
        new=AsyncMock(side_effect=ValueError("Cannot remove the last owner of a project")),
    ):
        res = await client.delete(f"/api/projects/proj-uuid-1/members/{_ANON_ADMIN_ID}")
    assert res.status_code == 409
    assert "last owner" in res.json()["detail"]


# ---------------------------------------------------------------------------
# POST /api/projects/{project_id}/invitations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_invitation_returns_201(client):
    with patch(
        "backend.routes.projects.crud_projects.create_invitation",
        new=AsyncMock(return_value=_INVITATION),
    ):
        res = await client.post(
            "/api/projects/proj-uuid-1/invitations",
            json={"invited_email": "bob@test.local", "role": "viewer"},
        )
    assert res.status_code == 201
    assert res.json()["invited_email"] == "bob@test.local"


@pytest.mark.asyncio
async def test_create_invitation_missing_email_returns_422(client):
    res = await client.post(
        "/api/projects/proj-uuid-1/invitations",
        json={"role": "viewer"},
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_create_invitation_invalid_role_returns_422(client):
    res = await client.post(
        "/api/projects/proj-uuid-1/invitations",
        json={"invited_email": "bob@test.local", "role": "admin"},
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_create_invitation_duplicate_returns_409(client):
    with patch(
        "backend.routes.projects.crud_projects.create_invitation",
        new=AsyncMock(side_effect=ValueError("bob@test.local already has a pending invitation")),
    ):
        res = await client.post(
            "/api/projects/proj-uuid-1/invitations",
            json={"invited_email": "bob@test.local", "role": "viewer"},
        )
    assert res.status_code == 409


# ---------------------------------------------------------------------------
# GET /api/projects/{project_id}/invitations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_invitations_returns_200(client):
    with patch(
        "backend.routes.projects.crud_projects.list_invitations",
        new=AsyncMock(return_value=[_INVITATION]),
    ):
        res = await client.get("/api/projects/proj-uuid-1/invitations")
    assert res.status_code == 200
    assert res.json()[0]["status"] == "pending"


# ---------------------------------------------------------------------------
# POST /api/invitations/{invitation_id}/accept
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accept_invitation_returns_200(client):
    with (
        patch(
            "backend.routes.projects.crud_projects.get_invitation",
            new=AsyncMock(return_value=_INVITATION),
        ),
        patch(
            "backend.routes.projects.crud_projects.accept_invitation",
            new=AsyncMock(return_value=_MEMBER),
        ),
    ):
        res = await client.post("/api/invitations/inv-uuid-1/accept")
    assert res.status_code == 200
    assert res.json()["role"] == "owner"


@pytest.mark.asyncio
async def test_accept_invitation_not_found_returns_404(client):
    """Unknown invitation ID → 404, not 409."""
    with patch(
        "backend.routes.projects.crud_projects.get_invitation",
        new=AsyncMock(return_value=None),
    ):
        res = await client.post("/api/invitations/nonexistent/accept")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_accept_invitation_wrong_email_returns_403(client):
    """Invitation sent to a different email → 403."""
    with (
        patch(
            "backend.routes.projects.crud_projects.get_invitation",
            new=AsyncMock(return_value=_INVITATION),
        ),
        patch(
            "backend.routes.projects.crud_projects.accept_invitation",
            new=AsyncMock(
                side_effect=PermissionError("This invitation was not sent to your email address")
            ),
        ),
    ):
        res = await client.post("/api/invitations/inv-uuid-1/accept")
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_accept_invitation_already_used_returns_409(client):
    with (
        patch(
            "backend.routes.projects.crud_projects.get_invitation",
            new=AsyncMock(return_value=_INVITATION),
        ),
        patch(
            "backend.routes.projects.crud_projects.accept_invitation",
            new=AsyncMock(side_effect=ValueError("Invitation is already accepted")),
        ),
    ):
        res = await client.post("/api/invitations/inv-uuid-1/accept")
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_accept_invitation_expired_returns_409(client):
    with (
        patch(
            "backend.routes.projects.crud_projects.get_invitation",
            new=AsyncMock(return_value=_INVITATION),
        ),
        patch(
            "backend.routes.projects.crud_projects.accept_invitation",
            new=AsyncMock(side_effect=ValueError("Invitation has expired")),
        ),
    ):
        res = await client.post("/api/invitations/inv-uuid-1/accept")
    assert res.status_code == 409


# ---------------------------------------------------------------------------
# POST /api/invitations/{invitation_id}/decline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decline_invitation_returns_204(client):
    with (
        patch(
            "backend.routes.projects.crud_projects.get_invitation",
            new=AsyncMock(return_value=_INVITATION),
        ),
        patch(
            "backend.routes.projects.crud_projects.decline_invitation",
            new=AsyncMock(return_value=None),
        ),
    ):
        res = await client.post("/api/invitations/inv-uuid-1/decline")
    assert res.status_code == 204


@pytest.mark.asyncio
async def test_decline_invitation_not_found_returns_404(client):
    with patch(
        "backend.routes.projects.crud_projects.get_invitation",
        new=AsyncMock(return_value=None),
    ):
        res = await client.post("/api/invitations/nonexistent/decline")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_decline_invitation_unauthorized_user_returns_403_when_auth_enabled(client):
    """A stranger who is neither the invitee nor a project owner gets 403."""
    from backend.auth.dependencies import get_current_user as _gcu

    stranger = {
        "id": "stranger-uuid",
        "username": "stranger",
        "email": "stranger@test.local",
        "is_admin": False,
        "is_active": True,
        "display_name": "Stranger",
    }

    async def _stranger():
        return stranger

    app.dependency_overrides[_gcu] = _stranger
    try:
        with (
            patch(
                "backend.routes.projects.crud_projects.get_invitation",
                new=AsyncMock(return_value=_INVITATION),  # invited_email = "bob@test.local"
            ),
            patch(
                "backend.routes.projects.crud_projects.get_user_role_in_project",
                new=AsyncMock(return_value=None),  # not a member
            ),
            patch("backend.config.settings") as mock_settings,
        ):
            mock_settings.paranoid_require_auth = True
            res = await client.post("/api/invitations/inv-uuid-1/decline")
    finally:
        app.dependency_overrides.pop(_gcu, None)

    assert res.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/users  (admin-only)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_users_admin_returns_200(client):
    # Anon admin (is_admin=True) passes require_admin. The route imports
    # crud_auth lazily inside the function body, so patch at the module level.
    with patch("backend.db.crud_auth.list_users", new=AsyncMock(return_value=[_USER])):
        res = await client.get("/api/users")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert data[0]["username"] == "alice"


# ---------------------------------------------------------------------------
# RBAC enforcement when PARANOID_REQUIRE_AUTH=true
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_project_non_member_returns_403_when_auth_enabled(client):
    """Non-member user should get 403 when auth is required.

    Override get_current_user via app.dependency_overrides so FastAPI resolves
    the non-member user, then patch settings so the _require_member guard runs.
    """
    from backend.auth.dependencies import get_current_user as _gcu

    non_member = {
        "id": "other-user-uuid",
        "username": "stranger",
        "email": "stranger@test.local",
        "is_admin": False,
        "is_active": True,
        "display_name": "Stranger",
    }

    async def _non_member_user():
        return non_member

    app.dependency_overrides[_gcu] = _non_member_user
    try:
        with (
            patch(
                "backend.routes.projects.crud_projects.get_project",
                new=AsyncMock(return_value=_PROJECT),
            ),
            patch(
                "backend.routes.projects.crud_projects.get_user_role_in_project",
                new=AsyncMock(return_value=None),
            ),
            patch("backend.config.settings") as mock_settings,
        ):
            mock_settings.paranoid_require_auth = True
            res = await client.get("/api/projects/proj-uuid-1")
    finally:
        app.dependency_overrides.pop(_gcu, None)

    assert res.status_code == 403


@pytest.mark.asyncio
async def test_update_project_non_owner_returns_403_when_auth_enabled(client):
    """Editor role cannot update project settings (owner-only)."""
    from backend.auth.dependencies import get_current_user as _gcu

    editor_user = {
        "id": "editor-user-uuid",
        "username": "editor",
        "email": "editor@test.local",
        "is_admin": False,
        "is_active": True,
        "display_name": "Editor",
    }

    async def _editor_user():
        return editor_user

    app.dependency_overrides[_gcu] = _editor_user
    try:
        with (
            patch(
                "backend.routes.projects.crud_projects.get_user_role_in_project",
                new=AsyncMock(return_value="editor"),
            ),
            patch("backend.config.settings") as mock_settings,
        ):
            mock_settings.paranoid_require_auth = True
            res = await client.patch("/api/projects/proj-uuid-1", json={"name": "Hack"})
    finally:
        app.dependency_overrides.pop(_gcu, None)

    assert res.status_code == 403


# ---------------------------------------------------------------------------
# Anon-mode passthrough (PARANOID_REQUIRE_AUTH=false, the default)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_project_no_auth_header_succeeds_in_anon_mode(client):
    """No Authorization header → anon admin → full access."""
    with patch(
        "backend.routes.projects.crud_projects.create_project",
        new=AsyncMock(return_value=_PROJECT),
    ):
        # Explicitly no auth header
        res = await client.post("/api/projects", json={"name": "Anon project"})
    assert res.status_code == 201


@pytest.mark.asyncio
async def test_owner_operations_allowed_in_anon_mode(client):
    """Owner-gated operations (archive) pass through in anon mode."""
    with patch(
        "backend.routes.projects.crud_projects.archive_project",
        new=AsyncMock(return_value=None),
    ):
        res = await client.delete("/api/projects/proj-uuid-1")
    assert res.status_code == 204
