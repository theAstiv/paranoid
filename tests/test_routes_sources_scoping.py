"""Code sources are project-scoped (bug-bash-log.md BB-19). The per-route role cells live
in test_rbac_matrix.py; this file covers lists, creation, SSE, and running with a source."""

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


@pytest.fixture
def auth_on(monkeypatch):
    monkeypatch.setattr(settings, "paranoid_require_auth", True)


def _client() -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    )


def _bearer(w: World, who: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {w.tokens[who]}"}


async def _source_in(project_id: str, name: str = "repo-b") -> str:
    sid = await crud.create_code_source(
        name=name,
        git_url=f"https://github.com/acme/{name}.git",
        ref=None,
        pat=None,
        project_id=project_id,
    )
    await crud.update_code_source_status(sid, status="ready")
    return sid


def _ids(r) -> set[str]:
    assert r.status_code == 200, r.text
    return {s["id"] for s in r.json()}


@pytest.mark.asyncio
async def test_source_list_only_shows_the_callers_projects(test_db, auth_on):
    w = await build_world()
    source_b = await _source_in(w.project_b)
    async with _client() as c:
        assert _ids(await c.get("/api/sources", headers=_bearer(w, "stranger"))) == {source_b}
        assert _ids(await c.get("/api/sources", headers=_bearer(w, "viewer"))) == {w.source}
        # owner owns A and views B
        assert _ids(await c.get("/api/sources", headers=_bearer(w, "owner"))) == {
            w.source,
            source_b,
        }
        assert _ids(await c.get("/api/sources", headers=_bearer(w, "admin"))) == {
            w.source,
            source_b,
        }


@pytest.mark.asyncio
async def test_source_list_project_filter(test_db, auth_on):
    w = await build_world()
    source_b = await _source_in(w.project_b)
    async with _client() as c:
        r = await c.get(f"/api/sources?project_id={w.project_a}", headers=_bearer(w, "owner"))
        assert _ids(r) == {w.source}
        r = await c.get(f"/api/sources?project_id={w.project_a}", headers=_bearer(w, "stranger"))
        assert r.status_code == 403
        r = await c.get(f"/api/sources?project_id={w.project_b}", headers=_bearer(w, "admin"))
        assert _ids(r) == {source_b}


@pytest.mark.asyncio
async def test_scoped_pat_lists_only_its_project(test_db, auth_on):
    w = await build_world()
    source_b = await _source_in(w.project_b)
    async with _client() as c:
        for who in ("pat_b", "pat_admin_b"):
            assert _ids(await c.get("/api/sources", headers=_bearer(w, who))) == {source_b}, who
            r = await c.get(f"/api/sources?project_id={w.project_a}", headers=_bearer(w, who))
            assert r.status_code == 403, who
        assert _ids(await c.get("/api/sources", headers=_bearer(w, "pat_free"))) == {
            w.source,
            source_b,
        }


@pytest.mark.asyncio
async def test_create_stores_project_and_creator(test_db, auth_on):
    w = await build_world()
    body = {
        "name": "mine",
        "git_url": "https://github.com/acme/mine.git",
        "project_id": w.project_a,
    }
    async with _client() as c:
        r = await c.post("/api/sources", json=body, headers=_bearer(w, "editor"))
    assert r.status_code == 202, r.text
    assert r.json()["project_id"] == w.project_a
    row = await crud.get_code_source(r.json()["id"])
    assert row["created_by"] == w.users["editor"]["id"]


@pytest.mark.asyncio
async def test_create_is_refused_outside_the_callers_projects(test_db, auth_on):
    w = await build_world()
    body = {"name": "x", "git_url": "https://github.com/acme/x.git", "project_id": w.project_a}
    async with _client() as c:
        for who in ("viewer", "stranger", "pat_b"):  # pat_b is scoped to B, not A
            r = await c.post("/api/sources", json=body, headers=_bearer(w, who))
            assert r.status_code == 403, who
        body["project_id"] = w.project_b
        # the owner is only a viewer of B, so even the in-scope PAT cannot create there
        r = await c.post("/api/sources", json=body, headers=_bearer(w, "pat_b"))
        assert r.status_code == 403
        r = await c.post("/api/sources", json=body, headers=_bearer(w, "pat_admin_b"))
        assert r.status_code == 202, r.text
    assert [s["id"] for s in await crud.list_code_sources(project_id=w.project_a)] == [w.source]
    assert [s["name"] for s in await crud.list_code_sources(project_id=w.project_b)] == ["x"]


@pytest.mark.asyncio
async def test_create_defaults_to_the_default_project_when_auth_is_off(test_db):
    async with _client() as c:
        r = await c.post(
            "/api/sources", json={"name": "d", "git_url": "https://github.com/acme/d.git"}
        )
    assert r.status_code == 202, r.text
    assert r.json()["project_id"] == crud_projects.DEFAULT_PROJECT_ID


@pytest.mark.asyncio
@pytest.mark.parametrize("auth", [True, False])
async def test_create_in_an_unknown_project_is_404_not_a_false_409(test_db, monkeypatch, auth):
    monkeypatch.setattr(settings, "paranoid_require_auth", auth)
    w = await build_world()
    body = {"name": "x", "git_url": "https://github.com/acme/x.git", "project_id": "nope"}
    headers = _bearer(w, "admin") if auth else {}
    async with _client() as c:
        r = await c.post("/api/sources", json=body, headers=headers)
    assert r.status_code == 404, r.text
    assert "Project" in r.json()["detail"]


# --- moving a source to another project ----------------------------------------
# Sources that predate projects all landed in the Default Project, so upgrading
# installs need a way to put them where their models are.


@pytest.mark.asyncio
async def test_move_source_changes_its_project_and_unlocks_runs(test_db, auth_on):
    w = await build_world()
    model_b = await crud.create_threat_model(
        title="B", description="d", provider="anthropic", model="m", project_id=w.project_b
    )
    async with _client() as c:
        r = await _run_with_source(c, model_b, w.source, _bearer(w, "admin"))
        assert r.status_code == 403  # in A, model in B
        r = await c.patch(
            f"/api/sources/{w.source}",
            json={"project_id": w.project_b},
            headers=_bearer(w, "admin"),
        )
        assert r.status_code == 200, r.text
        assert r.json()["project_id"] == w.project_b
        r = await _run_with_source(c, model_b, w.source, _bearer(w, "admin"))
        assert r.status_code == 200, r.text
        # And it left A's list.
        assert w.source not in _ids(await c.get("/api/sources", headers=_bearer(w, "viewer")))


@pytest.mark.asyncio
async def test_move_source_needs_owner_here_and_editor_there(test_db, auth_on):
    w = await build_world()
    project_c = (await crud_projects.create_project("C", w.users["owner"]["id"]))["id"]
    url = f"/api/sources/{w.source}"
    async with _client() as c:
        # editor of A may not move it away
        r = await c.patch(url, json={"project_id": project_c}, headers=_bearer(w, "editor"))
        assert r.status_code == 403
        # owner of A who is only a viewer of B may not move it into B
        r = await c.patch(url, json={"project_id": w.project_b}, headers=_bearer(w, "owner"))
        assert r.status_code == 403
        # a scoped token cannot move it out of its project
        r = await c.patch(url, json={"project_id": w.project_b}, headers=_bearer(w, "pat_b"))
        assert r.status_code == 403
        assert (await crud.get_code_source(w.source))["project_id"] == w.project_a
        # owner of both can
        r = await c.patch(url, json={"project_id": project_c}, headers=_bearer(w, "owner"))
        assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_move_source_to_an_unknown_project_is_404(test_db, auth_on):
    w = await build_world()
    async with _client() as c:
        r = await c.patch(
            f"/api/sources/{w.source}", json={"project_id": "nope"}, headers=_bearer(w, "admin")
        )
    assert r.status_code == 404
    assert (await crud.get_code_source(w.source))["project_id"] == w.project_a


@pytest.mark.asyncio
async def test_move_source_works_with_auth_off(test_db):
    w = await build_world()
    async with _client() as c:
        r = await c.patch(f"/api/sources/{w.source}", json={"project_id": w.project_b})
    assert r.status_code == 200, r.text
    assert (await crud.get_code_source(w.source))["project_id"] == w.project_b


@pytest.mark.asyncio
async def test_events_refuse_before_the_stream_opens(test_db, auth_on):
    w = await build_world()
    async with _client() as c:
        r = await c.get(f"/api/sources/{w.source}/events", headers=_bearer(w, "stranger"))
        assert r.status_code == 403
        assert "text/event-stream" not in r.headers.get("content-type", "")
        r = await c.get(f"/api/sources/{w.source}/events", headers=_bearer(w, "viewer"))
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]


@pytest.mark.asyncio
async def test_source_response_has_no_credentials_or_ciphertext(test_db, auth_on):
    w = await build_world()
    async with _client() as c:
        r = await c.get(f"/api/sources/{w.source}", headers=_bearer(w, "viewer"))
    assert r.status_code == 200
    assert "pat_ciphertext" not in r.json()


# --- running a model with a source ------------------------------------------------


async def _noop_runner(*_args, **_kwargs):
    return
    yield


async def _run_with_source(c, model_id: str, source_id: str, headers=None):
    with (
        patch("backend.routes.models.build_provider_from_record", return_value=MagicMock()),
        patch("backend.routes.models.build_fast_provider", return_value=None),
        patch("backend.routes.models.run_pipeline_for_model", _noop_runner),
    ):
        return await c.post(
            f"/api/models/{model_id}/run",
            data={"assumptions": "[]", "code_source_id": source_id},
            headers=headers or {},
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("auth", [True, False])
async def test_run_refuses_a_source_from_another_project(test_db, monkeypatch, auth):
    monkeypatch.setattr(settings, "paranoid_require_auth", auth)
    w = await build_world()
    source_b = await _source_in(w.project_b)
    async with _client() as c:
        r = await _run_with_source(c, w.model, source_b, _bearer(w, "admin") if auth else None)
        assert r.status_code == 403, r.text
        assert "different project" in r.json()["detail"]
        r = await _run_with_source(c, w.model, w.source, _bearer(w, "editor") if auth else None)
        assert r.status_code == 200, r.text
