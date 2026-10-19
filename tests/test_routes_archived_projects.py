"""No new sources or models in an archived project (bug-bash-log.md BB-25).

`check_project_role` ignores `projects.is_archived`, and an admin bypasses membership, so
before this fix the API accepted a create into an archived project that no list then showed.
The refusal is independent of role and of PARANOID_REQUIRE_AUTH."""

from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.config import settings
from backend.db import crud, crud_projects
from backend.main import app
from backend.sources import manager as mgr
from tests._rbac_world import World, build_world


@pytest.fixture(autouse=True)
def _no_clone(monkeypatch):
    monkeypatch.setattr(mgr, "schedule_clone_and_index", lambda _sid: None)


def _client() -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    )


def _bearer(w: World, who: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {w.tokens[who]}"}


def _source_body(project_id: str) -> dict:
    return {"name": "repo", "git_url": "https://github.com/acme/repo.git", "project_id": project_id}


def _model_body(project_id: str) -> dict:
    return {"title": "t", "description": "a long enough description", "project_id": project_id}


@pytest.mark.asyncio
@pytest.mark.parametrize("who", ["editor", "owner", "admin"])
async def test_create_in_an_archived_project_is_refused_for_every_role(test_db, monkeypatch, who):
    monkeypatch.setattr(settings, "paranoid_require_auth", True)
    w = await build_world()
    await crud_projects.archive_project(w.project_a)
    async with _client() as c:
        s = await c.post("/api/sources", json=_source_body(w.project_a), headers=_bearer(w, who))
        m = await c.post("/api/models/", json=_model_body(w.project_a), headers=_bearer(w, who))
    assert s.status_code == 403, s.text
    assert m.status_code == 403, m.text
    assert "archived" in s.json()["detail"].lower()
    assert "archived" in m.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_in_an_archived_project_is_refused_with_auth_off(test_db):
    w = await build_world()
    await crud_projects.archive_project(w.project_a)
    async with _client() as c:
        s = await c.post("/api/sources", json=_source_body(w.project_a))
        m = await c.post("/api/models/", json=_model_body(w.project_a))
    assert s.status_code == 403, s.text
    assert m.status_code == 403, m.text


@pytest.mark.asyncio
async def test_the_same_creates_succeed_in_an_active_project(test_db, monkeypatch):
    monkeypatch.setattr(settings, "paranoid_require_auth", True)
    w = await build_world()
    async with _client() as c:
        s = await c.post(
            "/api/sources", json=_source_body(w.project_a), headers=_bearer(w, "editor")
        )
        m = await c.post(
            "/api/models/", json=_model_body(w.project_a), headers=_bearer(w, "editor")
        )
    assert s.status_code == 202, s.text
    assert m.status_code == 201, m.text


@pytest.mark.asyncio
async def test_a_non_member_still_gets_the_membership_403_not_a_leak_of_archived_state(
    test_db, monkeypatch
):
    monkeypatch.setattr(settings, "paranoid_require_auth", True)
    w = await build_world()
    await crud_projects.archive_project(w.project_a)
    async with _client() as c:
        r = await c.post(
            "/api/sources", json=_source_body(w.project_a), headers=_bearer(w, "stranger")
        )
    assert r.status_code == 403
    assert "archived" not in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Bug-bash run order item 24: the BB-25 cases left out (same root cause as BB-50)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    reason=(
        "Bug-bash finding (item 24, BB-50 root cause): POST /api/models/{id}/run only "
        "checks the editor role, which ignores is_archived, so a model in an archived "
        "project can still be re-run (its data is cleared and rewritten)."
    ),
)
async def test_running_a_model_in_an_archived_project_is_refused(test_db, monkeypatch):
    monkeypatch.setattr(settings, "paranoid_require_auth", True)
    w = await build_world()
    await crud_projects.archive_project(w.project_a)

    async def noop_runner(*args, **kwargs):
        return
        yield  # pragma: no cover - makes this an async generator

    with (
        patch("backend.routes.models.build_provider_from_record", return_value=MagicMock()),
        patch("backend.routes.models.build_fast_provider", return_value=None),
        patch("backend.routes.models.run_pipeline_for_model", noop_runner),
    ):
        async with _client() as c:
            r = await c.post(
                f"/api/models/{w.model}/run",
                data={"assumptions": "[]"},
                headers=_bearer(w, "editor"),
            )
    assert r.status_code == 403, r.text
    assert "archived" in r.json()["detail"].lower()


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    reason=(
        "Bug-bash finding (item 24, BB-50 root cause): PATCH /api/sources/{id} checks the "
        "editor role on the target project but not is_archived, so a source can be moved "
        "into an archived project, where no list shows it."
    ),
)
async def test_moving_a_source_into_an_archived_project_is_refused(test_db, monkeypatch):
    monkeypatch.setattr(settings, "paranoid_require_auth", True)
    w = await build_world()
    project_c = (await crud_projects.create_project("C", w.users["owner"]["id"]))["id"]
    source_c = await crud.create_code_source(
        name="repo-c",
        git_url="https://github.com/acme/repo-c.git",
        ref=None,
        pat=None,
        project_id=project_c,
        created_by=w.users["owner"]["id"],
    )
    await crud_projects.archive_project(w.project_a)
    async with _client() as c:
        r = await c.patch(
            f"/api/sources/{source_c}",
            json={"project_id": w.project_a},
            headers=_bearer(w, "owner"),
        )
    assert r.status_code == 403, r.text
    assert "archived" in r.json()["detail"].lower()
