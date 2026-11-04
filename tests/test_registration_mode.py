"""PARANOID_REGISTRATION=open|admin_only (Phase 1B).

With auth on, POST /api/auth/register was open to anyone who could reach the
server, and any signed-in user could create a project and spend the
instance's provider keys. admin_only lets only an instance admin create
accounts and projects.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from backend.config import Settings, settings
from backend.main import app
from tests._rbac_world import build_world


def _client() -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    )


def _bearer(w, who: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {w.tokens[who]}"}


def _new_user(name: str) -> dict:
    return {"username": name, "email": f"{name}@test.local", "password": "password123"}


@pytest.fixture
def auth_on(monkeypatch):
    monkeypatch.setattr(settings, "paranoid_require_auth", True)


@pytest.fixture
def admin_only(monkeypatch):
    monkeypatch.setattr(settings, "paranoid_registration", "admin_only")


@pytest.mark.asyncio
async def test_registration_is_open_by_default(test_db, auth_on):
    async with _client() as c:
        r = await c.post("/api/auth/register", json=_new_user("alice"))
    assert r.status_code == 201


@pytest.mark.asyncio
async def test_admin_only_refuses_anonymous_and_member_registration(test_db, auth_on, admin_only):
    w = await build_world()
    async with _client() as c:
        anonymous = await c.post("/api/auth/register", json=_new_user("alice"))
        member = await c.post(
            "/api/auth/register", json=_new_user("bob"), headers=_bearer(w, "editor")
        )
        scoped_admin = await c.post(
            "/api/auth/register", json=_new_user("carol"), headers=_bearer(w, "pat_admin_b")
        )
    assert anonymous.status_code == 403
    assert "ask an instance admin" in anonymous.json()["detail"]
    assert member.status_code == 403
    assert scoped_admin.status_code == 403


@pytest.mark.asyncio
async def test_admin_only_lets_an_instance_admin_create_accounts(test_db, auth_on, admin_only):
    w = await build_world()
    async with _client() as c:
        r = await c.post("/api/auth/register", json=_new_user("dave"), headers=_bearer(w, "admin"))
    assert r.status_code == 201
    assert r.json()["is_admin"] in (0, False)


@pytest.mark.asyncio
async def test_admin_only_with_auth_off_still_registers(test_db, admin_only):
    """With auth off every caller is the anonymous admin (KL-9)."""
    async with _client() as c:
        r = await c.post("/api/auth/register", json=_new_user("erin"))
    assert r.status_code == 201


@pytest.mark.asyncio
async def test_options_are_readable_without_a_login(test_db, auth_on, admin_only):
    async with _client() as c:
        r = await c.get("/api/auth/options")
    assert r.status_code == 200
    assert r.json() == {"require_auth": True, "registration": "admin_only"}


@pytest.mark.asyncio
async def test_config_reports_the_registration_mode(test_db, admin_only):
    async with _client() as c:
        r = await c.get("/api/config/")
    assert r.json()["registration"] == "admin_only"


@pytest.mark.asyncio
async def test_admin_only_limits_project_creation_to_admins(test_db, auth_on, admin_only):
    w = await build_world()
    async with _client() as c:
        member = await c.post("/api/projects", json={"name": "P"}, headers=_bearer(w, "editor"))
        admin = await c.post("/api/projects", json={"name": "P"}, headers=_bearer(w, "admin"))
    assert member.status_code == 403
    assert admin.status_code == 201


@pytest.mark.asyncio
async def test_open_registration_still_lets_members_create_projects(test_db, auth_on):
    w = await build_world()
    async with _client() as c:
        r = await c.post("/api/projects", json={"name": "P"}, headers=_bearer(w, "editor"))
    assert r.status_code == 201


def test_a_blank_setting_means_open():
    assert Settings(paranoid_registration="").paranoid_registration == "open"
    assert Settings(paranoid_registration="admin_only").paranoid_registration == "admin_only"


def test_an_unknown_setting_is_rejected():
    with pytest.raises(ValueError, match="paranoid_registration"):
        Settings(paranoid_registration="invite")
