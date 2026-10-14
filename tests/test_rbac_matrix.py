"""RBAC matrix with PARANOID_REQUIRE_AUTH=true (bug-bash §7.1 / §7.7).

Every project-scoped route is called as each identity from tests/_rbac_world.py:
anonymous, a member of another project, a PAT scoped to that other project (its
owner owns project A), viewer, editor and owner of project A, and an instance
admin. Expected:

- anonymous → 401
- stranger, and the PAT scoped to project B → 403 or 404
- a role below the route's minimum → 403
- the minimum role and above, and the instance admin → anything but 401/403

KNOWN_GAPS lists the cells that are currently wrong (bug-bash-log.md BB-03, BB-04).
Each test asserts its wrong cells are *exactly* those, so a fix fails the test
until its entry here is removed. Routes that would call an LLM only check the
cells that must be denied, and the analyze handlers are stubbed regardless.
"""

from dataclasses import dataclass, field

import pytest
from httpx import ASGITransport, AsyncClient

from backend.auth.tokens import create_access_token
from backend.config import settings
from backend.db import crud, crud_auth
from backend.main import app
from backend.models.api import (
    AnalyzeAssumptionsResponse,
    AnalyzeBundleResponse,
    AnalyzeDescriptionResponse,
)
from tests._rbac_world import World, build_world


ROLE_ORDER = ["viewer", "editor", "owner"]
DENIED = {"anon": {401}, "stranger": {403, 404}, "pat_b": {403, 404}}


@dataclass
class Route:
    method: str
    path: str
    min_role: str
    body: dict | None = None
    # Mutates or removes the fixture data: only the lowest allowed role is called.
    destructive: bool = False
    # Would call an LLM: only the cells that must be denied are checked.
    spends: bool = False
    # Override who's allowed (author-only comment edits).
    allowed: list[str] | None = None
    gaps: set[str] = field(default_factory=set)

    @property
    def id(self) -> str:
        return f"{self.method} {self.path}"


_ANON_GAP = {"anon", "stranger", "pat_b"}  # BB-04 (analyze) + BB-03
_PAT_GAP = {"pat_b"}  # BB-03

ROUTES = [
    # --- model ---
    Route("GET", "/api/models/{model}", "viewer", gaps=_PAT_GAP),
    Route("PATCH", "/api/models/{model}", "editor", {"title": "renamed"}, gaps=_PAT_GAP),
    Route("DELETE", "/api/models/{model}", "owner", destructive=True, gaps=_PAT_GAP),
    Route("GET", "/api/models/{model}/assets", "viewer", gaps=_PAT_GAP),
    Route("GET", "/api/models/{model}/flows", "viewer", gaps=_PAT_GAP),
    Route("GET", "/api/models/{model}/threats", "viewer", gaps=_PAT_GAP),
    Route("GET", "/api/models/{model}/trust-boundaries", "viewer", gaps=_PAT_GAP),
    Route("GET", "/api/models/{model}/stats", "viewer", gaps=_PAT_GAP),
    Route("POST", "/api/models/{model}/analyze", "viewer", spends=True, gaps=_ANON_GAP),
    Route("POST", "/api/models/{model}/extract", "editor", {}, spends=True, gaps=_PAT_GAP),
    Route("POST", "/api/models/{model}/run", "editor", spends=True, gaps=_PAT_GAP),
    Route("GET", "/api/models/{model}/diff?base_id={model}", "viewer", gaps=_PAT_GAP),
    Route("GET", "/api/export/{model}?format=json", "viewer", gaps=_PAT_GAP),
    Route("GET", "/api/export/{model}?format=markdown", "viewer", gaps=_PAT_GAP),
    Route("POST", "/api/models/{model}/assets", "editor", {}, gaps=_PAT_GAP),
    Route("PATCH", "/api/models/{model}/assets/{asset}", "editor", {}, gaps=_PAT_GAP),
    Route(
        "DELETE", "/api/models/{model}/assets/{asset}", "editor", destructive=True, gaps=_PAT_GAP
    ),
    Route("POST", "/api/models/{model}/flows", "editor", {}, gaps=_PAT_GAP),
    Route("PATCH", "/api/models/{model}/flows/{flow}", "editor", {}, gaps=_PAT_GAP),
    Route("DELETE", "/api/models/{model}/flows/{flow}", "editor", destructive=True, gaps=_PAT_GAP),
    Route("POST", "/api/models/{model}/trust-boundaries", "editor", {}, gaps=_PAT_GAP),
    Route("PATCH", "/api/models/{model}/trust-boundaries/{boundary}", "editor", {}, gaps=_PAT_GAP),
    Route(
        "DELETE",
        "/api/models/{model}/trust-boundaries/{boundary}",
        "editor",
        destructive=True,
        gaps=_PAT_GAP,
    ),
    Route("GET", "/api/models/{model}/assignees", "viewer", gaps=_PAT_GAP),
    Route(
        "POST", "/api/models/{model}/assignees", "editor", {"user_id": "{viewer_id}"}, gaps=_PAT_GAP
    ),
    Route(
        "DELETE",
        "/api/models/{model}/assignees/{viewer_id}",
        "editor",
        destructive=True,
        gaps=_PAT_GAP,
    ),
    Route("GET", "/api/models/{model}/comments", "viewer", gaps=_PAT_GAP),
    Route("POST", "/api/models/{model}/comments", "viewer", {"body": "hi"}, gaps=_PAT_GAP),
    Route("GET", "/api/models/{model}/comments/counts", "viewer", gaps=_PAT_GAP),
    Route("GET", "/api/models/{model}/dependencies", "viewer", gaps=_PAT_GAP),
    Route("GET", "/api/models/{model}/diagrams", "viewer", gaps=_PAT_GAP),
    Route("GET", "/api/models/{model}/diagrams/{diagram}", "viewer", gaps=_PAT_GAP),
    # --- threat ---
    Route("GET", "/api/threats/{threat}", "viewer", gaps=_PAT_GAP),
    Route("PATCH", "/api/threats/{threat}", "editor", {"name": "renamed"}, gaps=_PAT_GAP),
    Route("DELETE", "/api/threats/{threat}", "editor", destructive=True, gaps=_PAT_GAP),
    Route("GET", "/api/threats/{threat}/attack-trees", "viewer", gaps=_PAT_GAP),
    Route("POST", "/api/threats/{threat}/attack-tree", "editor", spends=True, gaps=_PAT_GAP),
    Route("GET", "/api/threats/{threat}/test-cases", "viewer", gaps=_PAT_GAP),
    Route("POST", "/api/threats/{threat}/test-cases", "editor", spends=True, gaps=_PAT_GAP),
    Route(
        "POST",
        "/api/threats/bulk-status",
        "editor",
        {"threat_ids": ["{threat}"], "status": "approved"},
        gaps=_PAT_GAP,
    ),
    # --- comment (edit: author only; delete: author or editor+) ---
    Route(
        "PATCH",
        "/api/comments/{comment}",
        "viewer",
        {"body": "edited"},
        allowed=["owner"],
        gaps=_PAT_GAP,
    ),
    Route("DELETE", "/api/comments/{comment}", "editor", destructive=True, gaps=_PAT_GAP),
    # --- project A ---
    Route("GET", "/api/projects/{project_a}", "viewer", gaps=_PAT_GAP),
    Route("PATCH", "/api/projects/{project_a}", "owner", {"name": "renamed"}, gaps=_PAT_GAP),
    Route("DELETE", "/api/projects/{project_a}", "owner", destructive=True, gaps=_PAT_GAP),
    Route("GET", "/api/projects/{project_a}/activity", "viewer", gaps=_PAT_GAP),
    Route("GET", "/api/projects/{project_a}/dashboard", "viewer", gaps=_PAT_GAP),
    Route("GET", "/api/projects/{project_a}/members", "viewer", gaps=_PAT_GAP),
    Route(
        "POST",
        "/api/projects/{project_a}/members",
        "owner",
        {"user_id": "{stranger_id}", "role": "viewer"},
        destructive=True,
        gaps=_PAT_GAP,
    ),
    Route(
        "PATCH",
        "/api/projects/{project_a}/members/{viewer_id}",
        "owner",
        {"role": "editor"},
        destructive=True,
        gaps=_PAT_GAP,
    ),
    Route(
        "DELETE",
        "/api/projects/{project_a}/members/{viewer_id}",
        "owner",
        destructive=True,
        gaps=_PAT_GAP,
    ),
    Route("GET", "/api/projects/{project_a}/invitations", "owner", gaps=_PAT_GAP),
    Route(
        "POST",
        "/api/projects/{project_a}/invitations",
        "owner",
        {"invited_email": "new@test.local", "role": "viewer"},
        destructive=True,
        gaps=_PAT_GAP,
    ),
]


def _fill(value, ids: dict[str, str]):
    if isinstance(value, str):
        return value.format(**ids)
    if isinstance(value, list):
        return [_fill(v, ids) for v in value]
    if isinstance(value, dict):
        return {k: _fill(v, ids) for k, v in value.items()}
    return value


def _ids(w: World) -> dict[str, str]:
    return {
        "model": w.model,
        "threat": w.threat,
        "asset": w.asset,
        "flow": w.flow,
        "boundary": w.boundary,
        "comment": w.comment,
        "diagram": w.diagram,
        "project_a": w.project_a,
        "viewer_id": w.users["viewer"]["id"],
        "stranger_id": w.users["stranger"]["id"],
    }


def _expected_cells(route: Route) -> list[tuple[str, str]]:
    """(identity, "deny"|"allow") in call order.

    The PAT comes after the role denials: while BB-03 is open it succeeds, and on a
    destructive route that deletes the fixture, so it must only precede the allow
    cells (which treat the resulting 404 as "got past auth").
    """
    cells = [("anon", "deny"), ("stranger", "deny")]
    min_index = ROLE_ORDER.index(route.min_role)
    allowed = route.allowed or [*ROLE_ORDER[min_index:], "admin"]
    for role in ROLE_ORDER:
        if role not in allowed:
            cells.append((role, "deny"))
    cells.append(("pat_b", "deny"))
    if not route.spends:
        allows = [r for r in [*ROLE_ORDER, "admin"] if r in allowed]
        cells += [(who, "allow") for who in (allows[:1] if route.destructive else allows)]
    return cells


class _NoNetworkClient:
    def __init__(self, *_args, **_kwargs):
        raise RuntimeError("test_rbac_matrix must never construct a real LLM client")


@pytest.fixture(autouse=True)
def stub_llm(monkeypatch):
    """No matrix cell may reach a real provider, even if authorization breaks and a
    request that should be denied runs its handler (a pipeline run, an analyze)."""
    monkeypatch.setattr("backend.providers.anthropic.Anthropic", _NoNetworkClient)
    monkeypatch.setattr("backend.providers.openai.OpenAI", _NoNetworkClient)

    async def _description(**_kwargs):
        return AnalyzeDescriptionResponse(gaps=[], is_sufficient=True)

    async def _bundle(**_kwargs):
        return AnalyzeBundleResponse(
            description=AnalyzeDescriptionResponse(gaps=[], is_sufficient=True),
            assumptions=AnalyzeAssumptionsResponse(gaps=[], is_sufficient=True),
        )

    monkeypatch.setattr("backend.routes.models.analyze_description_gaps", _description)
    monkeypatch.setattr("backend.routes.analyze.analyze_bundle", _bundle)


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.id)
@pytest.mark.asyncio
async def test_route_enforces_project_roles(route, test_db, monkeypatch):
    monkeypatch.setattr(settings, "paranoid_require_auth", True)
    w = await build_world()
    ids = _ids(w)
    path = _fill(route.path, ids)
    body = _fill(route.body, ids)

    wrong: dict[str, int] = {}
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        for who, want in _expected_cells(route):
            headers = {} if who == "anon" else {"Authorization": f"Bearer {w.tokens[who]}"}
            r = await client.request(route.method, path, json=body, headers=headers)
            if want == "deny":
                ok = r.status_code in DENIED.get(who, {403})
            else:
                ok = r.status_code not in (401, 403)
            if not ok:
                wrong[who] = r.status_code

    assert set(wrong) == route.gaps, (
        f"cells wrong now: {wrong}; KNOWN_GAPS: {sorted(route.gaps)}. A newly fixed gap "
        "must be removed from this route's gaps; a new wrong cell is a regression."
    )


def _bearer(w: World, who: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {w.tokens[who]}"}


def _client() -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    )


async def _model_in(project_id: str, title: str = "B model") -> str:
    model_id = await crud.create_threat_model(
        title=title,
        description="d",
        provider="anthropic",
        model="m",
        project_id=project_id,
    )
    await crud.update_threat_model(model_id, status="completed")
    return model_id


def _ids_in(r) -> set[str]:
    assert r.status_code == 200
    return {m["id"] for m in r.json()}


@pytest.mark.asyncio
async def test_model_list_hides_other_projects(test_db, monkeypatch):
    """BB-02: the list only contains models from the caller's projects."""
    monkeypatch.setattr(settings, "paranoid_require_auth", True)
    w = await build_world()
    model_b = await _model_in(w.project_b)
    async with _client() as client:
        stranger = _ids_in(await client.get("/api/models/", headers=_bearer(w, "stranger")))
        assert stranger == {model_b}
        assert w.model not in stranger
        # owner owns A and views B
        assert _ids_in(await client.get("/api/models/", headers=_bearer(w, "owner"))) == {
            w.model,
            model_b,
        }
        assert _ids_in(await client.get("/api/models/", headers=_bearer(w, "viewer"))) == {w.model}
        assert _ids_in(await client.get("/api/models/", headers=_bearer(w, "admin"))) == {
            w.model,
            model_b,
        }
        r = await client.get(
            f"/api/models/?project_id={w.project_a}", headers=_bearer(w, "stranger")
        )
        assert r.status_code == 403
        r = await client.get(f"/api/models/?project_id={w.project_a}", headers=_bearer(w, "viewer"))
        assert _ids_in(r) == {w.model}


@pytest.mark.asyncio
async def test_model_list_limit_applies_after_project_filter(test_db, monkeypatch):
    """A newer model the caller can't see must not use up their `limit`."""
    monkeypatch.setattr(settings, "paranoid_require_auth", True)
    w = await build_world()
    await _model_in(w.project_b, "newer, hidden from viewer")
    async with _client() as client:
        r = await client.get("/api/models/?limit=1", headers=_bearer(w, "viewer"))
    assert _ids_in(r) == {w.model}


@pytest.mark.asyncio
async def test_model_list_without_projects_is_empty(test_db, monkeypatch):
    monkeypatch.setattr(settings, "paranoid_require_auth", True)
    w = await build_world()
    await crud_auth.create_user(
        username="loner",
        email="loner@test.local",
        password_hash="unusable",  # noqa: S106
    )
    loner = await crud_auth.get_user_by_username("loner")
    token = create_access_token(loner["id"], "loner", False)
    async with _client() as client:
        r = await client.get("/api/models/", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json() == []
    assert w.model  # world exists, so the empty list is the filter's doing


@pytest.mark.asyncio
async def test_diff_requires_both_models_readable(test_db, monkeypatch):
    """BB-02: diff needs viewer on the head and on the base model."""
    monkeypatch.setattr(settings, "paranoid_require_auth", True)
    w = await build_world()
    model_b = await _model_in(w.project_b)
    async with _client() as client:

        async def diff(who: str, head: str, base: str) -> int:
            r = await client.get(f"/api/models/{head}/diff?base_id={base}", headers=_bearer(w, who))
            return r.status_code

        await crud.update_threat_model(w.model, status="completed")
        # viewer of A only: head readable, base (project B) not
        assert await diff("viewer", w.model, model_b) == 403
        # stranger owns B only: head readable, base (project A) not
        assert await diff("stranger", model_b, w.model) == 403
        # head unreadable
        assert await diff("stranger", w.model, model_b) == 403
        # owner is a member of both A and B
        assert await diff("owner", w.model, model_b) == 200
        assert await diff("admin", w.model, model_b) == 200


@pytest.mark.asyncio
async def test_auth_off_reads_every_project(test_db, monkeypatch):
    """Auth off (the default) is unchanged: the anonymous admin sees everything."""
    monkeypatch.setattr(settings, "paranoid_require_auth", False)
    w = await build_world()
    model_b = await _model_in(w.project_b)
    await crud.update_threat_model(w.model, status="completed")
    async with _client() as client:
        assert _ids_in(await client.get("/api/models/")) == {w.model, model_b}
        for sub in ("assets", "flows", "threats", "trust-boundaries", "stats"):
            r = await client.get(f"/api/models/{w.model}/{sub}")
            assert r.status_code == 200, sub
        assert (await client.get(f"/api/models/{w.model}")).status_code == 200
        assert (await client.get(f"/api/threats/{w.threat}")).status_code == 200
        r = await client.get(f"/api/models/{w.model}/diff?base_id={model_b}")
        assert r.status_code == 200


@pytest.mark.parametrize("path", ["/api/analyze/"])
@pytest.mark.asyncio
async def test_llm_endpoint_requires_auth(path, test_db, monkeypatch):
    """BB-04: anonymous callers can reach an endpoint that spends LLM tokens."""
    monkeypatch.setattr(settings, "paranoid_require_auth", True)
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        r = await client.post(path, json={"description": "x" * 300, "assumptions": []})
    # KNOWN GAP (BB-04): an anonymous caller gets past auth (200, or 500 here because the
    # LLM client is stubbed to refuse construction). Expect 401 when fixed.
    assert r.status_code != 401, "BB-04 looks fixed: expect 401 here and update bug-bash-log.md"


@pytest.mark.asyncio
async def test_admin_only_routes(test_db, monkeypatch):
    monkeypatch.setattr(settings, "paranoid_require_auth", True)
    w = await build_world()
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        for path in ("/api/users", "/api/auth/users"):
            assert (await client.get(path)).status_code == 401
            for who in ("owner", "pat_b", "stranger"):
                r = await client.get(path, headers={"Authorization": f"Bearer {w.tokens[who]}"})
                assert r.status_code == 403, (path, who, r.status_code)
            r = await client.get(path, headers={"Authorization": f"Bearer {w.tokens['admin']}"})
            assert r.status_code == 200, (path, r.status_code)
