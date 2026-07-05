"""Tests for backend/db/crud_dashboard.py (Phase 7: dashboard aggregate queries)."""

from __future__ import annotations

import pytest

from backend.db import crud, crud_auth, crud_dashboard, crud_projects


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


async def _make_model(project_id: str, status: str = "completed") -> str:
    model_id = await crud.create_threat_model(
        title="Model",
        description="desc",
        provider="anthropic",
        model="claude",
        project_id=project_id,
    )
    await crud.update_threat_model_status(model_id, status)
    return model_id


async def _make_threat(model_id: str, dread_score: float | None, status: str = "pending") -> str:
    threat_id = await crud.create_threat(
        model_id=model_id,
        name="Threat",
        description="desc",
        target="target",
        impact="High",
        likelihood="High",
        mitigations=["mitigate"],
        dread_score=dread_score,
    )
    if status != "pending":
        await crud.update_threat_status(threat_id, status)
    return threat_id


@pytest.mark.asyncio
async def test_get_dashboard_stats_counts(test_db):
    user = await _make_user("alice")
    project = await _make_project(user["id"])

    m1 = await _make_model(project["id"])
    await _make_model(project["id"], status="in_review")
    await _make_threat(m1, dread_score=9.0)
    await _make_threat(m1, dread_score=None, status="approved")

    stats = await crud_dashboard.get_dashboard_stats(project["id"])
    assert stats["model_count"] == 2
    assert stats["open_threats"] == 1
    assert stats["pending_review"] == 1
    assert stats["member_count"] == 1  # creator is auto-added as owner


@pytest.mark.asyncio
async def test_get_severity_breakdown_buckets(test_db):
    user = await _make_user("bob")
    project = await _make_project(user["id"])
    model_id = await _make_model(project["id"])

    await _make_threat(model_id, dread_score=9.0)  # critical
    await _make_threat(model_id, dread_score=6.5)  # high
    await _make_threat(model_id, dread_score=4.0)  # medium
    await _make_threat(model_id, dread_score=1.0)  # low
    await _make_threat(model_id, dread_score=9.9, status="approved")  # not open

    breakdown = await crud_dashboard.get_severity_breakdown(project["id"])
    assert breakdown == {"critical": 1, "high": 1, "medium": 1, "low": 1}


@pytest.mark.asyncio
async def test_get_assigned_threats_scoped_and_ordered(test_db):
    from backend.db import crud_comments

    user = await _make_user("carol")
    project = await _make_project(user["id"])
    model_id = await _make_model(project["id"])
    other_model = await _make_model(project["id"])

    low = await _make_threat(model_id, dread_score=2.0)
    high = await _make_threat(model_id, dread_score=8.0)
    await _make_threat(other_model, dread_score=10.0)  # not assigned — excluded

    await crud_comments.add_assignee(model_id, user["id"], assigned_by=user["id"])

    assigned = await crud_dashboard.get_assigned_threats(project["id"], user["id"])
    ids = [t["id"] for t in assigned]
    assert ids == [high, low]
