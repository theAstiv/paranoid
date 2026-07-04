"""Tests for /api/models/{id}/comments, /api/comments/*, and /api/models/{id}/assignees (Phase 3).

Mocks at the usage site (backend.routes.comments.*) so inner dependencies do
not require a real database. The PARANOID_REQUIRE_AUTH=false default makes
get_current_user return the synthetic _ANON_ADMIN user, which is is_admin=True
— giving full access in all anon-mode tests.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app


_ANON_ADMIN_ID = "00000000-0000-0000-0000-000000000001"

_COMMENT_BY_ADMIN = {
    "id": "comment-uuid-1",
    "threat_model_id": "model-uuid-1",
    "user_id": _ANON_ADMIN_ID,
    "parent_id": None,
    "body": "Looks good to me.",
    "created_at": "2026-01-01T00:00:00",
    "updated_at": "2026-01-01T00:00:00",
    "username": "admin",
    "display_name": "Administrator",
}

_COMMENT_BY_OTHER = {
    **_COMMENT_BY_ADMIN,
    "id": "comment-uuid-2",
    "user_id": "other-user-uuid",
    "username": "alice",
    "display_name": "Alice",
}

_ASSIGNEE = {
    "id": "assignee-uuid-1",
    "threat_model_id": "model-uuid-1",
    "user_id": "other-user-uuid",
    "assigned_by": _ANON_ADMIN_ID,
    "created_at": "2026-01-01T00:00:00",
    "username": "alice",
    "email": "alice@test.local",
    "display_name": "Alice",
}


@pytest.fixture
async def client(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# GET /api/models/{model_id}/comments
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_comments_returns_200(client):
    with patch(
        "backend.routes.comments.crud_comments.list_comments",
        new=AsyncMock(return_value=[_COMMENT_BY_ADMIN]),
    ):
        res = await client.get("/api/models/model-uuid-1/comments")
    assert res.status_code == 200
    assert res.json()[0]["body"] == "Looks good to me."


# ---------------------------------------------------------------------------
# POST /api/models/{model_id}/comments
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_comment_returns_201(client):
    with patch(
        "backend.routes.comments.crud_comments.create_comment",
        new=AsyncMock(return_value=_COMMENT_BY_ADMIN),
    ):
        res = await client.post(
            "/api/models/model-uuid-1/comments", json={"body": "Looks good to me."}
        )
    assert res.status_code == 201
    assert res.json()["user_id"] == _ANON_ADMIN_ID


@pytest.mark.asyncio
async def test_create_comment_blank_body_returns_422(client):
    res = await client.post("/api/models/model-uuid-1/comments", json={"body": ""})
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_create_comment_returns_404_when_model_deleted_concurrently(client):
    """create_comment CRUD returning None (TOCTOU) must not surface as a 500."""
    with patch(
        "backend.routes.comments.crud_comments.create_comment",
        new=AsyncMock(return_value=None),
    ):
        res = await client.post(
            "/api/models/model-uuid-1/comments", json={"body": "Looks good to me."}
        )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_create_reply_with_parent_in_other_model_returns_422(client):
    """parent_id must reference a comment belonging to the same threat model."""
    parent_in_other_model = {
        **_COMMENT_BY_ADMIN,
        "id": "comment-other-model",
        "threat_model_id": "model-uuid-2",
    }
    with patch(
        "backend.routes.comments.crud_comments.get_comment",
        new=AsyncMock(return_value=parent_in_other_model),
    ):
        res = await client.post(
            "/api/models/model-uuid-1/comments",
            json={"body": "Stitched reply", "parent_id": "comment-other-model"},
        )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_create_reply_to_a_reply_returns_422(client):
    """Only one level of nesting is supported — replying to a reply is rejected."""
    reply_comment = {**_COMMENT_BY_ADMIN, "id": "comment-is-a-reply", "parent_id": "comment-root"}
    with patch(
        "backend.routes.comments.crud_comments.get_comment",
        new=AsyncMock(return_value=reply_comment),
    ):
        res = await client.post(
            "/api/models/model-uuid-1/comments",
            json={"body": "Reply to a reply", "parent_id": "comment-is-a-reply"},
        )
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# PATCH /api/comments/{comment_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_comment_by_author_returns_200(client):
    updated = {**_COMMENT_BY_ADMIN, "body": "Edited."}
    with (
        patch(
            "backend.routes.comments.crud_comments.get_comment",
            new=AsyncMock(return_value=_COMMENT_BY_ADMIN),
        ),
        patch(
            "backend.routes.comments.crud_comments.update_comment",
            new=AsyncMock(return_value=updated),
        ),
    ):
        res = await client.patch("/api/comments/comment-uuid-1", json={"body": "Edited."})
    assert res.status_code == 200
    assert res.json()["body"] == "Edited."


@pytest.mark.asyncio
async def test_update_comment_not_found_returns_404(client):
    with patch(
        "backend.routes.comments.crud_comments.get_comment", new=AsyncMock(return_value=None)
    ):
        res = await client.patch("/api/comments/nonexistent", json={"body": "Edited."})
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_update_comment_returns_404_when_deleted_concurrently(client):
    """update_comment CRUD returning None (TOCTOU) must not surface as a 500."""
    with (
        patch(
            "backend.routes.comments.crud_comments.get_comment",
            new=AsyncMock(return_value=_COMMENT_BY_ADMIN),
        ),
        patch(
            "backend.routes.comments.crud_comments.update_comment",
            new=AsyncMock(return_value=None),
        ),
    ):
        res = await client.patch("/api/comments/comment-uuid-1", json={"body": "Edited."})
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_update_comment_non_author_returns_403(client):
    """A non-admin user who did not author the comment cannot edit it."""
    from backend.auth.dependencies import get_current_user as _gcu

    non_author = {
        "id": "stranger-uuid",
        "username": "stranger",
        "email": "stranger@test.local",
        "is_admin": False,
        "is_active": True,
        "display_name": "Stranger",
    }

    async def _non_author_user():
        return non_author

    app.dependency_overrides[_gcu] = _non_author_user
    try:
        with patch(
            "backend.routes.comments.crud_comments.get_comment",
            new=AsyncMock(return_value=_COMMENT_BY_ADMIN),  # authored by admin, not stranger
        ):
            res = await client.patch("/api/comments/comment-uuid-1", json={"body": "Hack"})
    finally:
        app.dependency_overrides.pop(_gcu, None)

    assert res.status_code == 403


# ---------------------------------------------------------------------------
# DELETE /api/comments/{comment_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_comment_by_author_returns_204(client):
    with (
        patch(
            "backend.routes.comments.crud_comments.get_comment",
            new=AsyncMock(return_value=_COMMENT_BY_ADMIN),
        ),
        patch(
            "backend.routes.comments.crud_comments.delete_comment",
            new=AsyncMock(return_value=None),
        ),
    ):
        res = await client.delete("/api/comments/comment-uuid-1")
    assert res.status_code == 204


@pytest.mark.asyncio
async def test_delete_comment_not_found_returns_404(client):
    with patch(
        "backend.routes.comments.crud_comments.get_comment", new=AsyncMock(return_value=None)
    ):
        res = await client.delete("/api/comments/nonexistent")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_delete_comment_by_editor_returns_204_when_auth_enabled(client):
    """A non-author with editor+ role in the project may moderate-delete."""
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
                "backend.routes.comments.crud_comments.get_comment",
                new=AsyncMock(return_value=_COMMENT_BY_OTHER),  # authored by alice, not editor
            ),
            patch(
                "backend.routes.comments.crud_comments.delete_comment",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "backend.db.crud_projects.resolve_project_id_from_comment",
                new=AsyncMock(return_value="proj-uuid-1"),
            ),
            patch(
                "backend.db.crud_projects.get_user_role_in_project",
                new=AsyncMock(return_value="editor"),
            ),
            patch("backend.config.settings") as mock_settings,
        ):
            mock_settings.paranoid_require_auth = True
            res = await client.delete("/api/comments/comment-uuid-2")
    finally:
        app.dependency_overrides.pop(_gcu, None)

    assert res.status_code == 204


@pytest.mark.asyncio
async def test_delete_comment_by_plain_member_returns_403_when_auth_enabled(client):
    """A non-author viewer-role member cannot moderate-delete someone else's comment."""
    from backend.auth.dependencies import get_current_user as _gcu

    viewer_user = {
        "id": "viewer-user-uuid",
        "username": "viewer",
        "email": "viewer@test.local",
        "is_admin": False,
        "is_active": True,
        "display_name": "Viewer",
    }

    async def _viewer_user():
        return viewer_user

    app.dependency_overrides[_gcu] = _viewer_user
    try:
        with (
            patch(
                "backend.routes.comments.crud_comments.get_comment",
                new=AsyncMock(return_value=_COMMENT_BY_OTHER),  # authored by alice, not viewer
            ),
            patch(
                "backend.db.crud_projects.resolve_project_id_from_comment",
                new=AsyncMock(return_value="proj-uuid-1"),
            ),
            patch(
                "backend.db.crud_projects.get_user_role_in_project",
                new=AsyncMock(return_value="viewer"),
            ),
            patch("backend.config.settings") as mock_settings,
        ):
            mock_settings.paranoid_require_auth = True
            res = await client.delete("/api/comments/comment-uuid-2")
    finally:
        app.dependency_overrides.pop(_gcu, None)

    assert res.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/models/{model_id}/assignees
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_assignees_returns_200(client):
    with patch(
        "backend.routes.comments.crud_comments.list_assignees",
        new=AsyncMock(return_value=[_ASSIGNEE]),
    ):
        res = await client.get("/api/models/model-uuid-1/assignees")
    assert res.status_code == 200
    assert res.json()[0]["username"] == "alice"


# ---------------------------------------------------------------------------
# POST /api/models/{model_id}/assignees
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_assignee_returns_201(client):
    with patch(
        "backend.routes.comments.crud_comments.add_assignee",
        new=AsyncMock(return_value=_ASSIGNEE),
    ):
        res = await client.post(
            "/api/models/model-uuid-1/assignees", json={"user_id": "other-user-uuid"}
        )
    assert res.status_code == 201
    assert res.json()["user_id"] == "other-user-uuid"


@pytest.mark.asyncio
async def test_add_assignee_missing_user_id_returns_422(client):
    res = await client.post("/api/models/model-uuid-1/assignees", json={})
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_add_assignee_nonexistent_user_returns_404(client):
    """add_assignee CRUD returning None (FK violation on a bogus user_id) must not 500."""
    with patch(
        "backend.routes.comments.crud_comments.add_assignee",
        new=AsyncMock(return_value=None),
    ):
        res = await client.post(
            "/api/models/model-uuid-1/assignees", json={"user_id": "does-not-exist"}
        )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_add_assignee_non_project_member_returns_404_when_auth_enabled(client):
    """The target user_id must be a member of the model's project."""
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
                "backend.db.crud_projects.resolve_project_id_from_model",
                new=AsyncMock(return_value="proj-uuid-1"),
            ),
            patch(
                "backend.db.crud_projects.get_user_role_in_project",
                # First call (require_role, for the requester) → editor; second call
                # (_require_project_member, for the target user_id) → not a member.
                new=AsyncMock(side_effect=["editor", None]),
            ),
            patch("backend.config.settings") as mock_settings,
        ):
            mock_settings.paranoid_require_auth = True
            res = await client.post(
                "/api/models/model-uuid-1/assignees", json={"user_id": "not-a-member-uuid"}
            )
    finally:
        app.dependency_overrides.pop(_gcu, None)

    assert res.status_code == 404


@pytest.mark.asyncio
async def test_add_assignee_viewer_returns_403_when_auth_enabled(client):
    """Viewer role cannot assign users to a threat model (owner/editor only)."""
    from backend.auth.dependencies import get_current_user as _gcu

    viewer_user = {
        "id": "viewer-user-uuid",
        "username": "viewer",
        "email": "viewer@test.local",
        "is_admin": False,
        "is_active": True,
        "display_name": "Viewer",
    }

    async def _viewer_user():
        return viewer_user

    app.dependency_overrides[_gcu] = _viewer_user
    try:
        with (
            patch(
                "backend.db.crud_projects.resolve_project_id_from_model",
                new=AsyncMock(return_value="proj-uuid-1"),
            ),
            patch(
                "backend.db.crud_projects.get_user_role_in_project",
                new=AsyncMock(return_value="viewer"),
            ),
            patch("backend.config.settings") as mock_settings,
        ):
            mock_settings.paranoid_require_auth = True
            res = await client.post(
                "/api/models/model-uuid-1/assignees", json={"user_id": "other-user-uuid"}
            )
    finally:
        app.dependency_overrides.pop(_gcu, None)

    assert res.status_code == 403


# ---------------------------------------------------------------------------
# DELETE /api/models/{model_id}/assignees/{user_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remove_assignee_returns_204(client):
    with patch(
        "backend.routes.comments.crud_comments.remove_assignee",
        new=AsyncMock(return_value=None),
    ):
        res = await client.delete("/api/models/model-uuid-1/assignees/other-user-uuid")
    assert res.status_code == 204
