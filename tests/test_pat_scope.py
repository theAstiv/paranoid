"""Project-scoped PATs (bug-bash-log.md BB-03): a PAT with a project_id only acts
inside that project, even when its owner is an instance admin. An unscoped PAT keeps
its owner's memberships. The per-route denial cells live in test_rbac_matrix.py."""

import pytest
from httpx import ASGITransport, AsyncClient

from backend.config import settings
from backend.db import crud, crud_auth, crud_projects
from backend.main import app
from tests._rbac_world import World, build_world


def _client() -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    )


def _bearer(w: World, who: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {w.tokens[who]}"}


@pytest.fixture
def auth_on(monkeypatch):
    monkeypatch.setattr(settings, "paranoid_require_auth", True)


async def _model_in(project_id: str) -> str:
    return await crud.create_threat_model(
        title="m",
        description="d",
        provider="anthropic",
        model="m",
        project_id=project_id,
    )


@pytest.mark.asyncio
async def test_unscoped_pat_keeps_owner_rights(test_db, auth_on):
    w = await build_world()
    async with _client() as c:
        r = await c.patch(
            f"/api/projects/{w.project_a}", json={"name": "A2"}, headers=_bearer(w, "pat_free")
        )
        assert r.status_code == 200
        r = await c.get(f"/api/projects/{w.project_b}", headers=_bearer(w, "pat_free"))
        assert r.status_code == 200
        r = await c.get(f"/api/models/{w.model}", headers=_bearer(w, "pat_free"))
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_admin_scoped_pat_is_limited_to_its_project(test_db, auth_on):
    w = await build_world()
    model_b = await _model_in(w.project_b)
    h = _bearer(w, "pat_admin_b")
    async with _client() as c:
        for method, path, body in [
            ("GET", f"/api/projects/{w.project_a}", None),
            ("PATCH", f"/api/projects/{w.project_a}", {"name": "x"}),
            ("GET", f"/api/projects/{w.project_a}/members", None),
            ("GET", f"/api/models/{w.model}", None),
            ("PATCH", f"/api/threats/{w.threat}", {"name": "x"}),
            (
                "POST",
                "/api/threats/bulk-status",
                {"threat_ids": [w.threat], "status": "approved"},
            ),
        ]:
            r = await c.request(method, path, json=body, headers=h)
            assert r.status_code == 403, (method, path, r.status_code)
        # Inside its own project the admin still has access.
        assert (await c.get(f"/api/projects/{w.project_b}", headers=h)).status_code == 200
        assert (await c.get(f"/api/models/{model_b}", headers=h)).status_code == 200


@pytest.mark.asyncio
async def test_bulk_status_denied_across_projects_for_scoped_pat(test_db, auth_on):
    w = await build_world()
    async with _client() as c:
        r = await c.post(
            "/api/threats/bulk-status",
            json={"threat_ids": [w.threat], "status": "approved"},
            headers=_bearer(w, "pat_b"),
        )
    assert r.status_code == 403
    assert (await crud.get_threat(w.threat))["status"] != "approved"


@pytest.mark.asyncio
async def test_lists_show_only_the_scoped_project(test_db, auth_on):
    w = await build_world()
    model_b = await _model_in(w.project_b)
    async with _client() as c:
        for who in ("pat_b", "pat_admin_b"):
            h = _bearer(w, who)
            projects = (await c.get("/api/projects", headers=h)).json()
            assert [p["id"] for p in projects] == [w.project_b], who
            models = (await c.get("/api/models/", headers=h)).json()
            assert {m["id"] for m in models} == {model_b}, who
            r = await c.get(f"/api/models/?project_id={w.project_a}", headers=h)
            assert r.status_code == 403, who
        # The unscoped PAT sees everything its owner can.
        projects = (await c.get("/api/projects", headers=_bearer(w, "pat_free"))).json()
        assert {p["id"] for p in projects} >= {w.project_a, w.project_b}


@pytest.mark.asyncio
async def test_scoped_pat_cannot_create_outside_its_project(test_db, auth_on):
    w = await build_world()
    body = {"title": "t", "description": "a long enough description", "project_id": w.project_a}
    async with _client() as c:
        h = _bearer(w, "pat_b")
        assert (await c.post("/api/projects", json={"name": "new"}, headers=h)).status_code == 403
        assert (await c.post("/api/models/", json=body, headers=h)).status_code == 403
        # The owner is only a viewer of B, so the role check still applies in-scope.
        body["project_id"] = w.project_b
        assert (await c.post("/api/models/", json=body, headers=h)).status_code == 403
        r = await c.post("/api/models/", json=body, headers=_bearer(w, "pat_admin_b"))
        assert r.status_code == 201
        assert (
            await c.post("/api/projects", json={"name": "new"}, headers=_bearer(w, "pat_free"))
        ).status_code == 201


@pytest.mark.asyncio
async def test_scoped_pat_cannot_answer_other_projects_invitations(test_db, auth_on):
    w = await build_world()
    other = (await crud_projects.create_project("C", w.users["stranger"]["id"]))["id"]
    inv_id = (
        await crud_projects.create_invitation(
            other, w.users["owner"]["email"], "viewer", w.users["stranger"]["id"]
        )
    )["id"]
    async with _client() as c:
        for action in ("accept", "decline"):
            r = await c.post(f"/api/invitations/{inv_id}/{action}", headers=_bearer(w, "pat_b"))
            assert r.status_code == 403, action
        r = await c.post(f"/api/invitations/{inv_id}/accept", headers=_bearer(w, "pat_free"))
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_scoped_pat_cannot_manage_tokens(test_db, auth_on):
    """Otherwise it could mint an unscoped token for the same user."""
    w = await build_world()
    async with _client() as c:
        h = _bearer(w, "pat_b")
        assert (await c.post("/api/auth/tokens", json={"name": "x"}, headers=h)).status_code == 403
        assert (await c.get("/api/auth/tokens", headers=h)).status_code == 403
        assert (await c.delete("/api/auth/tokens/anything", headers=h)).status_code == 403
        for who in ("owner", "pat_free"):
            r = await c.post("/api/auth/tokens", json={"name": "x"}, headers=_bearer(w, who))
            assert r.status_code == 201, who
            assert r.json()["project_id"] is None


@pytest.mark.asyncio
async def test_token_creation_accepts_a_project(test_db, auth_on):
    w = await build_world()
    async with _client() as c:
        # owner is a member of A and a viewer of B
        r = await c.post(
            "/api/auth/tokens",
            json={"name": "ci", "project_id": w.project_b},
            headers=_bearer(w, "owner"),
        )
        assert r.status_code == 201
        assert r.json()["project_id"] == w.project_b
        scoped = {"Authorization": f"Bearer {r.json()['token']}"}
        assert (await c.get(f"/api/projects/{w.project_a}", headers=scoped)).status_code == 403
        assert (await c.get(f"/api/projects/{w.project_b}", headers=scoped)).status_code == 200
        # the new token appears in the list with its scope
        listed = (await c.get("/api/auth/tokens", headers=_bearer(w, "owner"))).json()
        assert w.project_b in {t["project_id"] for t in listed}

        # a project the caller doesn't belong to, and one that doesn't exist
        r = await c.post(
            "/api/auth/tokens",
            json={"name": "x", "project_id": w.project_b},
            headers=_bearer(w, "viewer"),
        )
        assert r.status_code == 403
        r = await c.post(
            "/api/auth/tokens",
            json={"name": "x", "project_id": "no-such-project"},
            headers=_bearer(w, "owner"),
        )
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_auth_off_ignores_token_scope(test_db, monkeypatch):
    """Auth off resolves every request to the anonymous admin, which has no scope."""
    monkeypatch.setattr(settings, "paranoid_require_auth", False)
    w = await build_world()
    async with _client() as c:
        assert (await c.get(f"/api/projects/{w.project_a}")).status_code == 200
        assert (await c.get(f"/api/models/{w.model}")).status_code == 200
        listed = (await c.get("/api/projects")).json()
        assert {p["id"] for p in listed} >= {w.project_a, w.project_b}


@pytest.mark.asyncio
async def test_world_pat_rows_carry_the_expected_scope(test_db):
    """Guards the fixture the scope tests rely on."""
    w = await build_world()
    scopes = {}
    for who in ("pat_b", "pat_free", "pat_admin_b"):
        pat = await crud_auth.get_pat_by_id(w.tokens[who].split("_")[1])
        scopes[who] = pat["project_id"]
    assert scopes == {"pat_b": w.project_b, "pat_free": None, "pat_admin_b": w.project_b}


@pytest.mark.asyncio
async def test_admin_scoped_pat_is_refused_on_admin_routes(test_db, auth_on):
    w = await build_world()
    async with _client() as c:
        for path in ("/api/users", "/api/auth/users"):
            r = await c.get(path, headers=_bearer(w, "pat_admin_b"))
            assert r.status_code == 403, path
            r = await c.get(path, headers=_bearer(w, "admin"))
            assert r.status_code == 200, path


@pytest.mark.asyncio
async def test_create_model_requires_editor_in_the_project(test_db, auth_on):
    w = await build_world()
    body = {"title": "t", "description": "a long enough description", "project_id": w.project_a}
    async with _client() as c:
        for who, want in [("stranger", 403), ("viewer", 403), ("editor", 201), ("admin", 201)]:
            r = await c.post("/api/models/", json=body, headers=_bearer(w, who))
            assert r.status_code == want, who


@pytest.mark.asyncio
async def test_scoped_pat_to_archived_project_sees_empty_list(test_db, auth_on):
    w = await build_world()
    await crud_projects.archive_project(w.project_b)
    async with _client() as c:
        r = await c.get("/api/models/", headers=_bearer(w, "pat_b"))
    assert r.status_code == 200
    assert r.json() == []
