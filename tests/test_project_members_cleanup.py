"""Member changes keep an owner and clean up after a removed member.

- BB-48: besides PATCH, a member upsert (POST members) and accepting a
  lower-role invite also demoted the only owner.
- BB-64: removing a member left their assignments (which keep notifying them)
  and their notifications for that project.
- KL-4: a project-scoped token listed and marked the user's notifications from
  every project.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from backend.config import settings
from backend.db import crud, crud_activity, crud_comments, crud_projects
from backend.db.connection import db
from backend.main import app
from tests._rbac_world import build_world


@pytest.fixture
def auth_on(monkeypatch):
    monkeypatch.setattr(settings, "paranoid_require_auth", True)


def _client() -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    )


def _bearer(w, who: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {w.tokens[who]}"}


# ---------------------------------------------------------------------------
# BB-48: every path that changes a role keeps an owner
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_member_upsert_cant_demote_the_last_owner(test_db, auth_on):
    w = await build_world()
    owner = w.users["owner"]
    async with _client() as c:
        r = await c.post(
            f"/api/projects/{w.project_a}/members",
            json={"user_id": owner["id"], "role": "viewer"},
            headers=_bearer(w, "owner"),
        )
    assert r.status_code == 409
    assert (await crud_projects.get_member(w.project_a, owner["id"]))["role"] == "owner"


@pytest.mark.asyncio
async def test_accepting_a_lower_role_invite_cant_demote_the_last_owner(test_db):
    w = await build_world()
    owner = w.users["owner"]
    inv = await crud_projects.create_invitation(
        w.project_a, owner["email"], "editor", invited_by=owner["id"]
    )

    with pytest.raises(crud_projects.LastOwnerError):
        await crud_projects.accept_invitation(inv["id"], owner["id"], owner["email"])

    assert (await crud_projects.get_member(w.project_a, owner["id"]))["role"] == "owner"
    assert (await crud_projects.get_invitation(inv["id"]))["status"] == "pending"


@pytest.mark.asyncio
async def test_an_owner_can_step_down_once_there_is_another_owner(test_db):
    w = await build_world()
    await crud_projects.update_member_role(w.project_a, w.users["editor"]["id"], "owner")

    member = await crud_projects.update_member_role(w.project_a, w.users["owner"]["id"], "editor")

    assert member["role"] == "editor"


@pytest.mark.asyncio
async def test_re_adding_a_member_with_a_new_role_still_works(test_db):
    w = await build_world()

    member = await crud_projects.add_member(w.project_a, w.users["viewer"]["id"], "editor")

    assert member["role"] == "editor"


# ---------------------------------------------------------------------------
# BB-64: removal deletes the member's assignments and notifications there
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_removing_a_member_deletes_their_assignments_and_notifications(test_db):
    w = await build_world()
    editor = w.users["editor"]["id"]
    model_b = await crud.create_threat_model(
        title="B", description="d", provider="anthropic", model="m", project_id=w.project_b
    )
    await crud_projects.add_member(w.project_b, editor, "editor")
    await crud_comments.add_assignee(w.model, editor, assigned_by=None)
    await crud_comments.add_assignee(model_b, editor, assigned_by=None)
    await crud_activity.create_notification(
        editor, "assigned", "A", entity_type="model", entity_id=w.model
    )
    await crud_activity.create_notification(
        editor, "assigned", "B", entity_type="model", entity_id=model_b
    )

    await crud_projects.remove_member(w.project_a, editor)

    assert await crud_comments.get_assignee(w.model, editor) is None
    assert await crud_comments.get_assignee(model_b, editor) is not None
    titles = [n["title"] for n in await crud_activity.list_notifications(editor)]
    assert titles == ["B"]


@pytest.mark.asyncio
async def test_a_refused_removal_deletes_nothing(test_db):
    w = await build_world()
    owner = w.users["owner"]["id"]
    await crud_comments.add_assignee(w.model, owner, assigned_by=None)

    with pytest.raises(crud_projects.LastOwnerError):
        await crud_projects.remove_member(w.project_a, owner)

    assert await crud_comments.get_assignee(w.model, owner) is not None


# ---------------------------------------------------------------------------
# KL-4: notifications know their project; scoped tokens see only theirs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_notification_records_the_project_of_its_entity(test_db):
    w = await build_world()
    user = w.users["owner"]["id"]
    for entity_type, entity_id in (
        ("project", w.project_a),
        ("model", w.model),
        ("threat", w.threat),
        ("comment", w.comment),
    ):
        n = await crud_activity.create_notification(
            user, "t", entity_type, entity_type=entity_type, entity_id=entity_id
        )
        stored = await crud_activity.get_notification(n["id"])
        assert stored["project_id"] == w.project_a, entity_type

    n = await crud_activity.create_notification(user, "t", "none")
    assert (await crud_activity.get_notification(n["id"]))["project_id"] is None


@pytest.mark.asyncio
async def test_a_scoped_token_lists_and_marks_only_its_projects_notifications(test_db, auth_on):
    w = await build_world()
    owner = w.users["owner"]["id"]
    in_a = await crud_activity.create_notification(
        owner, "t", "in A", entity_type="project", entity_id=w.project_a
    )
    await crud_activity.create_notification(
        owner, "t", "in B", entity_type="project", entity_id=w.project_b
    )

    async with _client() as c:
        listed = (await c.get("/api/notifications", headers=_bearer(w, "pat_b"))).json()
        other = await c.patch(f"/api/notifications/{in_a['id']}", headers=_bearer(w, "pat_b"))
        await c.post("/api/notifications/mark-all-read", headers=_bearer(w, "pat_b"))
        everything = (await c.get("/api/notifications", headers=_bearer(w, "owner"))).json()

    assert [n["title"] for n in listed] == ["in B"]
    assert other.status_code == 404
    read = {n["title"]: n["is_read"] for n in everything}
    assert read == {"in A": 0, "in B": 1}


@pytest.mark.asyncio
async def test_migration_0018_backfills_existing_notifications(test_db):
    w = await build_world()
    user = w.users["owner"]["id"]
    n = await crud_activity.create_notification(
        user, "t", "old", entity_type="threat", entity_id=w.threat
    )
    conn = await db.get()
    await conn.execute("UPDATE notifications SET project_id = NULL")
    await conn.commit()

    import importlib

    migration = importlib.import_module("backend.db.migrations.0018_notifications_project")
    await migration.up(conn)
    await conn.commit()

    assert (await crud_activity.get_notification(n["id"]))["project_id"] == w.project_a
