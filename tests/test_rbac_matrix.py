"""RBAC matrix with PARANOID_REQUIRE_AUTH=true (bug-bash §7.1 / §7.7).

Every project-scoped route is called as each identity from tests/_rbac_world.py:
anonymous, a member of another project, a PAT scoped to that other project (its
owner owns project A), viewer, editor and owner of project A, and an instance
admin. Expected:

- anonymous → 401
- stranger, and the PAT scoped to project B → 403 or 404
- a role below the route's minimum → 403
- the minimum role and above, and the instance admin → anything but 401/403

KNOWN_GAPS lists the cells that are currently wrong (none at the moment).
Each test asserts its wrong cells are *exactly* those, so a fix fails the test
until its entry here is removed. Routes that would call an LLM only check the
cells that must be denied, and the analyze handlers are stubbed regardless.
"""

from dataclasses import dataclass, field

import pytest
from httpx import ASGITransport, AsyncClient

from backend.auth.tokens import create_access_token
from backend.config import settings
from backend.db import crud, crud_auth, crud_projects
from backend.main import app
from backend.models.api import (
    AnalyzeAssumptionsResponse,
    AnalyzeBundleResponse,
    AnalyzeDescriptionResponse,
)
from backend.providers.base import ProviderError
from tests._rbac_world import World, build_world


ROLE_ORDER = ["viewer", "editor", "owner"]
DENIED = {
    "anon": {401},
    "stranger": {403, 404},
    "pat_b": {403, 404},
    "pat_admin_b": {403, 404},
}


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


ROUTES = [
    Route(
        "POST",
        "/api/models/",
        "editor",
        {"title": "t", "description": "a long enough description", "project_id": "{project_a}"},
    ),
    # --- model ---
    Route("GET", "/api/models/{model}", "viewer"),
    Route("PATCH", "/api/models/{model}", "editor", {"title": "renamed"}),
    Route("DELETE", "/api/models/{model}", "owner", destructive=True),
    Route("GET", "/api/models/{model}/assets", "viewer"),
    Route("GET", "/api/models/{model}/flows", "viewer"),
    Route("GET", "/api/models/{model}/threats", "viewer"),
    Route("GET", "/api/models/{model}/trust-boundaries", "viewer"),
    Route("GET", "/api/models/{model}/stats", "viewer"),
    Route("POST", "/api/models/{model}/analyze", "viewer", spends=True),
    Route("POST", "/api/models/{model}/extract", "editor", {}, spends=True),
    Route("POST", "/api/models/{model}/run", "editor", spends=True),
    Route("GET", "/api/models/{model}/diff?base_id={model}", "viewer"),
    Route("GET", "/api/export/{model}?format=json", "viewer"),
    Route("GET", "/api/export/{model}?format=markdown", "viewer"),
    Route("POST", "/api/models/{model}/assets", "editor", {}),
    Route("PATCH", "/api/models/{model}/assets/{asset}", "editor", {}),
    Route("DELETE", "/api/models/{model}/assets/{asset}", "editor", destructive=True),
    Route("POST", "/api/models/{model}/flows", "editor", {}),
    Route("PATCH", "/api/models/{model}/flows/{flow}", "editor", {}),
    Route("DELETE", "/api/models/{model}/flows/{flow}", "editor", destructive=True),
    Route("POST", "/api/models/{model}/trust-boundaries", "editor", {}),
    Route("PATCH", "/api/models/{model}/trust-boundaries/{boundary}", "editor", {}),
    Route("DELETE", "/api/models/{model}/trust-boundaries/{boundary}", "editor", destructive=True),
    Route("GET", "/api/models/{model}/assignees", "viewer"),
    Route("POST", "/api/models/{model}/assignees", "editor", {"user_id": "{viewer_id}"}),
    Route("DELETE", "/api/models/{model}/assignees/{viewer_id}", "editor", destructive=True),
    Route("GET", "/api/models/{model}/comments", "viewer"),
    Route("POST", "/api/models/{model}/comments", "viewer", {"body": "hi"}),
    Route("GET", "/api/models/{model}/comments/counts", "viewer"),
    Route("GET", "/api/models/{model}/dependencies", "viewer"),
    Route("GET", "/api/models/{model}/diagrams", "viewer"),
    Route("GET", "/api/models/{model}/diagrams/{diagram}", "viewer"),
    # --- code source (BB-19) ---
    Route(
        "POST",
        "/api/sources",
        "editor",
        {
            "name": "new",
            "git_url": "https://github.com/acme/new.git",
            "project_id": "{project_a}",
        },
    ),
    Route("GET", "/api/sources/{source}", "viewer"),
    Route(
        "PATCH", "/api/sources/{source}", "owner", {"project_id": "{project_a}"}, destructive=True
    ),
    Route("GET", "/api/sources/{source}/events", "viewer"),
    Route("POST", "/api/sources/{source}/reindex", "editor"),
    Route("DELETE", "/api/sources/{source}", "owner", destructive=True),
    # --- threat ---
    Route("GET", "/api/threats/{threat}", "viewer"),
    Route("PATCH", "/api/threats/{threat}", "editor", {"name": "renamed"}),
    Route("DELETE", "/api/threats/{threat}", "editor", destructive=True),
    Route("GET", "/api/threats/{threat}/attack-trees", "viewer"),
    Route("POST", "/api/threats/{threat}/attack-tree", "editor", spends=True),
    Route("GET", "/api/threats/{threat}/test-cases", "viewer"),
    Route("POST", "/api/threats/{threat}/test-cases", "editor", spends=True),
    Route(
        "POST",
        "/api/threats/bulk-status",
        "editor",
        {"threat_ids": ["{threat}"], "status": "approved"},
    ),
    # --- comment (edit: author only; delete: author or editor+) ---
    Route("PATCH", "/api/comments/{comment}", "viewer", {"body": "edited"}, allowed=["owner"]),
    Route("DELETE", "/api/comments/{comment}", "editor", destructive=True),
    # --- project A ---
    Route("GET", "/api/projects/{project_a}", "viewer"),
    Route("PATCH", "/api/projects/{project_a}", "owner", {"name": "renamed"}),
    Route("DELETE", "/api/projects/{project_a}", "owner", destructive=True),
    Route("GET", "/api/projects/{project_a}/activity", "viewer"),
    Route("GET", "/api/projects/{project_a}/dashboard", "viewer"),
    Route("GET", "/api/projects/{project_a}/members", "viewer"),
    Route(
        "POST",
        "/api/projects/{project_a}/members",
        "owner",
        {"user_id": "{stranger_id}", "role": "viewer"},
        destructive=True,
    ),
    Route(
        "PATCH",
        "/api/projects/{project_a}/members/{viewer_id}",
        "owner",
        {"role": "editor"},
        destructive=True,
    ),
    Route("DELETE", "/api/projects/{project_a}/members/{viewer_id}", "owner", destructive=True),
    Route("GET", "/api/projects/{project_a}/invitations", "owner"),
    Route(
        "POST",
        "/api/projects/{project_a}/invitations",
        "owner",
        {"invited_email": "new@test.local", "role": "viewer"},
        destructive=True,
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
        "source": w.source,
        "project_a": w.project_a,
        "viewer_id": w.users["viewer"]["id"],
        "stranger_id": w.users["stranger"]["id"],
    }


def _expected_cells(route: Route) -> list[tuple[str, str]]:
    """(identity, "deny"|"allow") in call order.

    The PAT comes after the role denials and before the allow cells: if its scope
    were not enforced it would succeed, and on a destructive route that deletes the
    fixture, which the allow cells treat as "got past auth" (a 404).
    """
    cells = [("anon", "deny"), ("stranger", "deny")]
    min_index = ROLE_ORDER.index(route.min_role)
    allowed = route.allowed or [*ROLE_ORDER[min_index:], "admin"]
    for role in ROLE_ORDER:
        if role not in allowed:
            cells.append((role, "deny"))
    # A PAT scoped to B, even one whose owner is an instance admin, is denied in A.
    cells.extend([("pat_b", "deny"), ("pat_admin_b", "deny")])
    if not route.spends:
        allows = [r for r in [*ROLE_ORDER, "admin"] if r in allowed]
        cells += [(who, "allow") for who in (allows[:1] if route.destructive else allows)]
    return cells


class _FakeProvider:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None

    async def generate_structured(self, *_args, **_kwargs):
        # The filler description in these tests must never reach the LLM; if it does,
        # fail loudly with the provider error the pre-flight fallback is built to catch.
        raise ProviderError("LLM call not expected in the matrix")


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
    # An allowed source create/reindex must not start a real git clone.
    monkeypatch.setattr("backend.sources.manager.schedule_clone_and_index", lambda _sid: None)


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
async def test_archived_project_models_leave_the_list_but_stay_readable(test_db, monkeypatch):
    """Deliberate: archived projects are hidden from a member's list (as in GET /projects)
    and the explicit project filter says why; direct reads of their models still work
    (archived = read-only, not secret). Admins still see everything."""
    monkeypatch.setattr(settings, "paranoid_require_auth", True)
    w = await build_world()
    await crud_projects.archive_project(w.project_a)
    async with _client() as client:
        assert w.model not in _ids_in(
            await client.get("/api/models/", headers=_bearer(w, "viewer"))
        )
        r = await client.get(f"/api/models/?project_id={w.project_a}", headers=_bearer(w, "viewer"))
        assert r.status_code == 403
        assert "archived" in r.json()["detail"]
        r = await client.get(f"/api/models/{w.model}", headers=_bearer(w, "viewer"))
        assert r.status_code == 200
        assert w.model in _ids_in(await client.get("/api/models/", headers=_bearer(w, "admin")))


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
    """BB-04: an endpoint that spends LLM tokens needs a login when auth is on."""
    monkeypatch.setattr(settings, "paranoid_require_auth", True)
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        r = await client.post(path, json={"description": "x" * 300, "assumptions": []})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_pre_flight_analyze_open_to_any_logged_in_user(test_db, monkeypatch):
    """/analyze/ is project-independent: a member, a scoped PAT and an admin may call it."""
    monkeypatch.setattr(settings, "paranoid_require_auth", True)
    monkeypatch.setattr("backend.routes.analyze.create_provider", lambda **_kw: _FakeProvider())
    w = await build_world()
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        for who in ("viewer", "stranger", "pat_b", "admin"):
            r = await client.post(
                "/api/analyze/",
                json={"description": "x" * 300, "assumptions": []},
                headers=_bearer(w, who),
            )
            assert r.status_code == 200, (who, r.status_code)


@pytest.mark.asyncio
async def test_admin_only_routes(test_db, monkeypatch):
    monkeypatch.setattr(settings, "paranoid_require_auth", True)
    w = await build_world()
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        for path in ("/api/users", "/api/auth/users"):
            assert (await client.get(path)).status_code == 401
            for who in ("owner", "pat_b", "pat_admin_b", "stranger"):
                r = await client.get(path, headers={"Authorization": f"Bearer {w.tokens[who]}"})
                assert r.status_code == 403, (path, who, r.status_code)
            r = await client.get(path, headers={"Authorization": f"Bearer {w.tokens['admin']}"})
            assert r.status_code == 200, (path, r.status_code)
