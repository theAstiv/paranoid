"""Tests for backend/db/crud_activity.py (Phase 5: activity log + notifications)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from backend.db import crud_activity, crud_auth, crud_projects


async def _make_user(username: str) -> dict:
    from backend.auth.passwords import hash_password

    return await crud_auth.create_user(
        username=username,
        email=f"{username}@test.local",
        password_hash=hash_password("password123"),
        display_name=username.title(),
    )


async def _make_project(created_by: str) -> dict:
    return await crud_projects.create_project(name="Test Project", created_by=created_by)


# ---------------------------------------------------------------------------
# Activity log
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_activity_and_list_activity_ordering(test_db):
    user = await _make_user("alice")
    project = await _make_project(user["id"])

    await crud_activity.log_activity(
        project_id=project["id"],
        user_id=user["id"],
        entity_type="model",
        entity_id="model-1",
        action="created",
        details={"title": "First"},
    )
    await crud_activity.log_activity(
        project_id=project["id"],
        user_id=user["id"],
        entity_type="model",
        entity_id="model-2",
        action="created",
        details={"title": "Second"},
    )

    entries = await crud_activity.list_activity(project["id"])
    assert len(entries) == 2
    # Newest first
    assert entries[0]["entity_id"] == "model-2"
    assert entries[0]["details"] == {"title": "Second"}
    assert entries[0]["username"] == "alice"


@pytest.mark.asyncio
async def test_list_activity_respects_limit(test_db):
    user = await _make_user("bob")
    project = await _make_project(user["id"])
    for i in range(5):
        await crud_activity.log_activity(
            project_id=project["id"],
            user_id=user["id"],
            entity_type="model",
            entity_id=f"model-{i}",
            action="created",
        )

    entries = await crud_activity.list_activity(project["id"], limit=2)
    assert len(entries) == 2


@pytest.mark.asyncio
async def test_list_activity_scoped_to_project(test_db):
    user = await _make_user("carol")
    project_a = await _make_project(user["id"])
    project_b = await _make_project(user["id"])

    await crud_activity.log_activity(
        project_id=project_a["id"],
        user_id=user["id"],
        entity_type="model",
        entity_id="model-a",
        action="created",
    )
    await crud_activity.log_activity(
        project_id=project_b["id"],
        user_id=user["id"],
        entity_type="model",
        entity_id="model-b",
        action="created",
    )

    entries = await crud_activity.list_activity(project_a["id"])
    assert len(entries) == 1
    assert entries[0]["entity_id"] == "model-a"


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_and_list_notifications(test_db):
    user = await _make_user("dave")
    await crud_activity.create_notification(
        user_id=user["id"],
        notification_type="comment_added",
        title="Someone commented",
        entity_type="comment",
        entity_id="comment-1",
    )
    notifications = await crud_activity.list_notifications(user["id"])
    assert len(notifications) == 1
    assert notifications[0]["title"] == "Someone commented"
    assert notifications[0]["is_read"] == 0


@pytest.mark.asyncio
async def test_list_notifications_unread_only_filter(test_db):
    user = await _make_user("erin")
    n1 = await crud_activity.create_notification(user["id"], "assigned", "You were assigned")
    await crud_activity.create_notification(user["id"], "assigned", "Another one")
    await crud_activity.mark_notification_read(n1["id"], user["id"])

    unread = await crud_activity.list_notifications(user["id"], unread_only=True)
    assert len(unread) == 1
    assert unread[0]["title"] == "Another one"


@pytest.mark.asyncio
async def test_mark_notification_read_wrong_owner_returns_none(test_db):
    owner = await _make_user("frank")
    stranger = await _make_user("gina")
    notification = await crud_activity.create_notification(owner["id"], "assigned", "Hi")

    result = await crud_activity.mark_notification_read(notification["id"], stranger["id"])
    assert result is None

    # Untouched — still unread for the real owner
    fetched = await crud_activity.get_notification(notification["id"])
    assert fetched["is_read"] == 0


@pytest.mark.asyncio
async def test_mark_notification_read_nonexistent_returns_none(test_db):
    result = await crud_activity.mark_notification_read("does-not-exist", "some-user")
    assert result is None


@pytest.mark.asyncio
async def test_mark_all_read(test_db):
    user = await _make_user("hank")
    await crud_activity.create_notification(user["id"], "assigned", "One")
    await crud_activity.create_notification(user["id"], "assigned", "Two")

    await crud_activity.mark_all_read(user["id"])

    notifications = await crud_activity.list_notifications(user["id"])
    assert all(n["is_read"] == 1 for n in notifications)


@pytest.mark.asyncio
async def test_notify_users_dedupes_and_skips_empty(test_db):
    user_a = await _make_user("ivy")
    user_b = await _make_user("jack")

    await crud_activity.notify_users(
        {user_a["id"], user_b["id"], user_a["id"], "", None},
        notification_type="assigned",
        title="You were assigned",
    )

    notifications_a = await crud_activity.list_notifications(user_a["id"])
    notifications_b = await crud_activity.list_notifications(user_b["id"])
    assert len(notifications_a) == 1
    assert len(notifications_b) == 1


# ---------------------------------------------------------------------------
# Best-effort wrappers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_safe_log_activity_swallows_exceptions():
    with patch(
        "backend.db.crud_activity.log_activity",
        new=AsyncMock(side_effect=RuntimeError("db exploded")),
    ):
        await crud_activity.safe_log_activity(None, None, "model", "x", "created")
    # No exception propagated — test passes by reaching this line


@pytest.mark.asyncio
async def test_safe_notify_users_swallows_exceptions():
    with patch(
        "backend.db.crud_activity.notify_users",
        new=AsyncMock(side_effect=RuntimeError("db exploded")),
    ):
        await crud_activity.safe_notify_users({"user-1"}, "assigned", "Hi")
    # No exception propagated — test passes by reaching this line
