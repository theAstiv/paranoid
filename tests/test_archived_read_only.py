"""An archived project is read-only (BB-50, BB-135).

Archiving only hid the project from non-admin lists: require_role looked at
membership, so editors kept editing models, threats and comments and running
pipelines there. Every non-GET route on a project's content now answers 403
while it is archived, for every role and with auth off; member management and
unarchive still work.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from backend.config import settings
from backend.db import crud_projects
from backend.main import app
from tests._rbac_world import build_world
from tests.test_rbac_matrix import ROUTES, _fill, _ids, stub_llm  # noqa: F401 - fixture


# Still allowed in an archived project: managing members, and archiving again.
_ALLOWED = {
    "POST /api/projects/{project_a}/members",
    "PATCH /api/projects/{project_a}/members/{viewer_id}",
    "DELETE /api/projects/{project_a}/members/{viewer_id}",
    "DELETE /api/projects/{project_a}",
}
_MUTATIONS = [r for r in ROUTES if r.method != "GET" and r.id not in _ALLOWED]


def _client() -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    )


@pytest.fixture
def auth_on(monkeypatch):
    monkeypatch.setattr(settings, "paranoid_require_auth", True)


async def _archived_world():
    w = await build_world()
    await crud_projects.archive_project(w.project_a)
    return w


@pytest.mark.parametrize("who", ["owner", "admin"])
@pytest.mark.parametrize("route", _MUTATIONS, ids=lambda r: r.id)
@pytest.mark.asyncio
async def test_every_content_mutation_is_refused_in_an_archived_project(
    test_db, auth_on, route, who
):
    w = await _archived_world()
    ids = _ids(w)
    async with _client() as c:
        r = await c.request(
            route.method,
            _fill(route.path, ids),
            json=_fill(route.body, ids) if route.body is not None else None,
            headers={"Authorization": f"Bearer {w.tokens[who]}"},
        )
    assert r.status_code == 403, r.text
    assert "archived" in r.json()["detail"]


@pytest.mark.parametrize("route", _MUTATIONS, ids=lambda r: r.id)
@pytest.mark.asyncio
async def test_with_auth_off_an_archived_project_is_read_only_too(test_db, route):
    w = await _archived_world()
    ids = _ids(w)
    async with _client() as c:
        r = await c.request(
            route.method,
            _fill(route.path, ids),
            json=_fill(route.body, ids) if route.body is not None else None,
        )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_reads_still_work_in_an_archived_project(test_db, auth_on):
    w = await _archived_world()
    async with _client() as c:
        r = await c.get(
            f"/api/models/{w.model}", headers={"Authorization": f"Bearer {w.tokens['owner']}"}
        )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_an_owner_can_find_and_unarchive_their_project(test_db, auth_on):
    w = await _archived_world()
    owner = {"Authorization": f"Bearer {w.tokens['owner']}"}
    async with _client() as c:
        default = [p["id"] for p in (await c.get("/api/projects", headers=owner)).json()]
        with_archived = (await c.get("/api/projects?include_archived=true", headers=owner)).json()
        restored = await c.post(f"/api/projects/{w.project_a}/unarchive", headers=owner)
        edit = await c.patch(f"/api/models/{w.model}", json={"title": "renamed"}, headers=owner)
    assert w.project_a not in default
    assert any(p["id"] == w.project_a and p["is_archived"] for p in with_archived)
    assert restored.status_code == 200
    assert not restored.json()["is_archived"]
    assert edit.status_code == 200


@pytest.mark.asyncio
async def test_only_an_owner_can_unarchive(test_db, auth_on):
    w = await _archived_world()
    async with _client() as c:
        r = await c.post(
            f"/api/projects/{w.project_a}/unarchive",
            headers={"Authorization": f"Bearer {w.tokens['editor']}"},
        )
    assert r.status_code == 403
    assert (await crud_projects.get_project(w.project_a))["is_archived"]


@pytest.mark.asyncio
async def test_a_non_member_still_gets_the_membership_403(test_db, auth_on):
    w = await _archived_world()
    async with _client() as c:
        r = await c.patch(
            f"/api/models/{w.model}",
            json={"title": "x"},
            headers={"Authorization": f"Bearer {w.tokens['stranger']}"},
        )
    assert r.status_code == 403
    assert "archived" not in r.json()["detail"]
