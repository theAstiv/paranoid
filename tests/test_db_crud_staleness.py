"""Tests for backend.db.crud_staleness — stale model detection and dedup."""

from datetime import UTC, datetime, timedelta

import pytest

from backend.db import crud
from backend.db.connection import db
from backend.db.crud_staleness import find_stale_models, get_recently_notified_model_ids


async def _create_project(name: str = "Test Project", threshold: int | None = None) -> str:
    """Insert a project row and return its id."""
    import uuid

    project_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    conn = await db.get()
    await conn.execute(
        """INSERT INTO projects (id, name, is_archived, created_by, created_at, updated_at, staleness_threshold_days)
           VALUES (?, ?, 0, NULL, ?, ?, ?)""",
        (project_id, name, now, now, threshold),
    )
    await conn.commit()
    return project_id


async def _create_model(
    project_id: str,
    title: str = "Test Model",
    status: str = "completed",
    days_ago: int = 31,
) -> str:
    """Insert a threat model updated `days_ago` days in the past."""
    model_id = await crud.create_threat_model(
        title=title,
        description="Test description",
        provider="anthropic",
        model="claude-sonnet-4",
        project_id=project_id,
    )
    updated_at = (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()
    conn = await db.get()
    await conn.execute(
        "UPDATE threat_models SET status = ?, updated_at = ? WHERE id = ?",
        (status, updated_at, model_id),
    )
    await conn.commit()
    return model_id


async def _ensure_test_user() -> str:
    """Create a test user if not exists and return user_id."""
    user_id = "test-user-00000000"
    conn = await db.get()
    await conn.execute(
        """INSERT OR IGNORE INTO users (id, username, email, password_hash, display_name, is_admin, is_active, created_at, updated_at)
           VALUES (?, 'testuser', 'test@example.com', 'hash', 'Test', 0, 1, datetime('now'), datetime('now'))""",
        (user_id,),
    )
    await conn.commit()
    return user_id


async def _insert_staleness_notification(model_id: str, hours_ago: int = 1) -> None:
    """Insert a model_stale notification in the past."""
    import uuid

    user_id = await _ensure_test_user()
    conn = await db.get()
    await conn.execute(
        """INSERT INTO notifications (id, user_id, type, title, entity_type, entity_id, is_read, created_at)
           VALUES (?, ?, 'model_stale', 'Stale', 'model', ?, 0, datetime('now', ?))""",
        (str(uuid.uuid4()), user_id, model_id, f"-{hours_ago} hours"),
    )
    await conn.commit()


# ---------------------------------------------------------------------------
# find_stale_models
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_model_past_threshold_is_stale(test_db):
    project_id = await _create_project()
    model_id = await _create_model(project_id, days_ago=31)
    stale = await find_stale_models()
    assert any(m["id"] == model_id for m in stale)


@pytest.mark.asyncio
async def test_model_under_threshold_is_not_stale(test_db):
    """Model updated fewer days ago than the threshold should not be stale."""
    project_id = await _create_project()
    model_id = await _create_model(project_id, days_ago=29)
    stale = await find_stale_models()
    assert not any(m["id"] == model_id for m in stale)


@pytest.mark.asyncio
async def test_per_project_threshold_override(test_db):
    project_id = await _create_project(threshold=7)
    model_id = await _create_model(project_id, days_ago=8)
    stale = await find_stale_models()
    assert any(m["id"] == model_id for m in stale)


@pytest.mark.asyncio
async def test_per_project_short_threshold_excludes_recent(test_db):
    project_id = await _create_project(threshold=7)
    model_id = await _create_model(project_id, days_ago=5)
    stale = await find_stale_models()
    assert not any(m["id"] == model_id for m in stale)


@pytest.mark.asyncio
async def test_only_completed_models_returned(test_db):
    project_id = await _create_project()
    model_id = await _create_model(project_id, status="in_progress", days_ago=60)
    stale = await find_stale_models()
    assert not any(m["id"] == model_id for m in stale)


@pytest.mark.asyncio
async def test_model_with_no_project_uses_default(test_db):
    """Model with project_id pointing to default project (no staleness_threshold_days)."""

    model_id = await crud.create_threat_model(
        title="Orphan Model",
        description="No explicit project",
        provider="anthropic",
        model="claude-sonnet-4",
    )
    updated_at = (datetime.now(UTC) - timedelta(days=31)).isoformat()
    conn = await db.get()
    await conn.execute(
        "UPDATE threat_models SET status = 'completed', updated_at = ? WHERE id = ?",
        (updated_at, model_id),
    )
    await conn.commit()
    stale = await find_stale_models()
    assert any(m["id"] == model_id for m in stale)


# ---------------------------------------------------------------------------
# get_recently_notified_model_ids
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dedup_within_23h(test_db):
    project_id = await _create_project()
    model_id = await _create_model(project_id, days_ago=31)
    await _insert_staleness_notification(model_id, hours_ago=10)
    recently_notified = await get_recently_notified_model_ids(since_hours=23)
    assert model_id in recently_notified


@pytest.mark.asyncio
async def test_dedup_outside_23h(test_db):
    project_id = await _create_project()
    model_id = await _create_model(project_id, days_ago=31)
    await _insert_staleness_notification(model_id, hours_ago=24)
    recently_notified = await get_recently_notified_model_ids(since_hours=23)
    assert model_id not in recently_notified
