"""Tests for /api/notifications routes (Phase 5).

Notifications are user-scoped, not project-scoped — no require_role RBAC,
just get_current_user. Mocks at the usage site (backend.routes.notifications.*).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app


_ANON_ADMIN_ID = "00000000-0000-0000-0000-000000000001"

_NOTIFICATION = {
    "id": "notif-uuid-1",
    "user_id": _ANON_ADMIN_ID,
    "type": "comment_added",
    "title": "Someone commented on your model",
    "body": None,
    "entity_type": "comment",
    "entity_id": "comment-uuid-1",
    "is_read": 0,
    "created_at": "2026-01-01T00:00:00",
}


@pytest.fixture
async def client(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_list_notifications_returns_200(client):
    with patch(
        "backend.routes.notifications.crud_activity.list_notifications",
        new=AsyncMock(return_value=[_NOTIFICATION]),
    ):
        res = await client.get("/api/notifications")
    assert res.status_code == 200
    assert res.json()[0]["title"] == "Someone commented on your model"


@pytest.mark.asyncio
async def test_mark_notification_read_returns_200(client):
    updated = {**_NOTIFICATION, "is_read": 1}
    with patch(
        "backend.routes.notifications.crud_activity.mark_notification_read",
        new=AsyncMock(return_value=updated),
    ):
        res = await client.patch("/api/notifications/notif-uuid-1")
    assert res.status_code == 200
    assert res.json()["is_read"] == 1


@pytest.mark.asyncio
async def test_mark_notification_read_not_found_returns_404(client):
    """Also covers another user's notification_id — CRUD returns None either way."""
    with patch(
        "backend.routes.notifications.crud_activity.mark_notification_read",
        new=AsyncMock(return_value=None),
    ):
        res = await client.patch("/api/notifications/not-mine")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_mark_all_notifications_read_returns_204(client):
    with patch(
        "backend.routes.notifications.crud_activity.mark_all_read",
        new=AsyncMock(return_value=None),
    ) as mock_mark_all:
        res = await client.post("/api/notifications/mark-all-read", json={})
    assert res.status_code == 204
    mock_mark_all.assert_awaited_once_with(_ANON_ADMIN_ID)
