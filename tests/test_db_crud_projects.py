"""Tests for backend/db/crud_projects.py project lists (BB-145: last_activity_at)."""

from __future__ import annotations

import pytest

from backend.db import crud, crud_auth, crud_projects
from backend.db.connection import db


async def _make_user(username: str) -> dict:
    from backend.auth.passwords import hash_password

    return await crud_auth.create_user(
        username=username,
        email=f"{username}@test.local",
        password_hash=hash_password("password123"),
        display_name=username.title(),
    )


async def _set_updated_at(model_id: str, when: str) -> None:
    conn = await db.get()
    await conn.execute("UPDATE threat_models SET updated_at = ? WHERE id = ?", (when, model_id))
    await conn.commit()


@pytest.mark.asyncio
async def test_project_lists_carry_the_latest_model_change(test_db):
    user = await _make_user("alice")
    busy = await crud_projects.create_project(name="Busy", created_by=user["id"])
    empty = await crud_projects.create_project(name="Empty", created_by=user["id"])
    older = await crud.create_threat_model("a", "d", "anthropic", "m", project_id=busy["id"])
    newer = await crud.create_threat_model("b", "d", "anthropic", "m", project_id=busy["id"])
    await _set_updated_at(older, "2026-01-01T00:00:00+00:00")
    await _set_updated_at(newer, "2026-03-01T00:00:00+00:00")

    for listed in (
        await crud_projects.list_projects_for_user(user["id"]),
        await crud_projects.list_all_projects(),
    ):
        by_id = {p["id"]: p for p in listed}
        assert by_id[busy["id"]]["last_activity_at"] == "2026-03-01T00:00:00+00:00"
        assert by_id[empty["id"]]["last_activity_at"] is None


@pytest.mark.asyncio
async def test_member_list_still_carries_the_role(test_db):
    user = await _make_user("bob")
    project = await crud_projects.create_project(name="P", created_by=user["id"])

    listed = await crud_projects.list_projects_for_user(user["id"])

    assert [(p["id"], p["member_role"]) for p in listed] == [(project["id"], "owner")]
