"""Negative tests (bug-bash-plan.md §6): uploads, dependency input, pipeline bounds, auth.

Each bad input must fail cleanly: the right status, a clear JSON `detail`, no
traceback in the body, nothing half-saved, and (for /run) the pipeline never
starts. Cases already pinned elsewhere are not repeated here: oversize diagrams and
too many diagrams (test_routes_models_diagrams.py), malformed/oversized manifests and
lockfile-without-manifest (test_routes_run_dependencies.py), oversized tarballs
(test_deps_fetcher.py).

Tests marked xfail(strict=True) are bug-bash findings.
"""

import io
import json
import time
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner
from httpx import ASGITransport, AsyncClient
from PIL import Image

from backend.auth.tokens import create_access_token, create_pat
from backend.config import Settings, settings
from backend.db import crud, crud_auth
from backend.db.connection import db
from backend.deps import analyze
from backend.main import app
from cli.commands.run import run


_FORM = {"assumptions": "[]", "has_ai_components": "false"}
_GOOD_DESCRIPTION = "A web application with a Postgres database and an admin panel"


def _client() -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    )


def _assert_clean_error(r: httpx.Response, status: int | tuple[int, ...]) -> str:
    statuses = status if isinstance(status, tuple) else (status,)
    assert r.status_code in statuses, r.text
    assert "Traceback" not in r.text
    detail = r.json()["detail"]
    assert detail
    return detail if isinstance(detail, str) else json.dumps(detail)


@pytest.fixture
async def model_id(test_db) -> str:
    return await crud.create_threat_model(
        title="Neg", description=_GOOD_DESCRIPTION, provider="anthropic", model="m"
    )


@pytest.fixture
def pipeline_spy():
    """Patch the pipeline out of /run and record whether it was started."""
    calls: list[dict] = []

    async def _runner(*_args, **kwargs):
        calls.append(kwargs)
        return
        yield  # pragma: no cover - makes this an async generator

    with (
        patch("backend.routes.models.build_provider_from_record", return_value=MagicMock()),
        patch("backend.routes.models.build_fast_provider", return_value=None),
        patch("backend.routes.models.run_pipeline_for_model", _runner),
    ):
        yield calls


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Uploads
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "content", "status", "needle"),
    [
        ("arch.png", b"this is a text file, not a PNG", 422, "image"),
        ("arch.png", b"", 422, ""),
        ("arch.jpg", _png(), 422, "JPEG"),
        ("arch.mmd", b"", 422, "empty"),
        ("arch.mmd", b"   \n\t  ", 422, "empty"),
        ("arch.mmd", b"\xff\xfe\x00graph", 422, "UTF-8"),
        ("arch.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>", 422, ""),
        ("arch.gif", b"GIF89a", 422, ""),
    ],
    ids=[
        "text-as-png",
        "zero-byte-png",
        "png-as-jpg",
        "empty-mmd",
        "blank-mmd",
        "non-utf8-mmd",
        "svg",
        "gif",
    ],
)
async def test_bad_diagram_upload_fails_cleanly_and_saves_nothing(
    model_id, pipeline_spy, filename, content, status, needle
):
    async with _client() as client:
        r = await client.post(
            f"/api/models/{model_id}/run",
            data=_FORM,
            files={"diagrams": (filename, content, "application/octet-stream")},
        )
    detail = _assert_clean_error(r, status)
    assert needle.lower() in detail.lower()
    assert "PIL" not in detail
    assert "cannot identify image file" not in detail
    assert await crud.list_model_diagrams(model_id) == []
    assert pipeline_spy == []
    assert (await crud.get_threat_model(model_id))["status"] == "pending"


@pytest.mark.asyncio
async def test_one_bad_diagram_in_a_set_rejects_the_whole_set(model_id, pipeline_spy):
    """A good file next to a bad one must not leave the good one half-saved."""
    await crud.replace_model_diagrams(
        model_id,
        [{"name": "old", "kind": "mermaid", "content": "graph TD; X-->Y", "size_bytes": 15}],
    )
    async with _client() as client:
        r = await client.post(
            f"/api/models/{model_id}/run",
            data=_FORM,
            files=[
                ("diagrams", ("good.png", _png(), "image/png")),
                ("diagrams", ("bad.png", b"not an image", "image/png")),
            ],
        )
    _assert_clean_error(r, 422)
    rows = await crud.list_model_diagrams(model_id)
    assert [row["name"] for row in rows] == ["old"]
    assert pipeline_spy == []


@pytest.mark.asyncio
async def test_non_mermaid_text_in_a_mmd_file_is_accepted_as_text(model_id, pipeline_spy):
    """Documented behaviour, not a finding: there is no server-side Mermaid parser
    (tech-decision-rationale.md, Decision 11); the text reaches the LLM as-is and the
    browser shows a parse-error panel. Pinned so a change here is deliberate."""
    async with _client() as client:
        r = await client.post(
            f"/api/models/{model_id}/run",
            data=_FORM,
            files={"diagrams": ("arch.mmd", b"this is not mermaid at all", "text/plain")},
        )
    assert r.status_code == 200
    assert len(pipeline_spy) == 1


# ---------------------------------------------------------------------------
# Dependency input
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lockfile_over_the_upload_cap_is_rejected(model_id, pipeline_spy):
    from backend.routes.models import _MAX_LOCKFILE_BYTES

    manifest = json.dumps({"dependencies": {"chalk": "5.3.0"}}).encode()
    lockfile = b'{"packages": {}, "pad": "' + b"x" * _MAX_LOCKFILE_BYTES + b'"}'
    async with _client() as client:
        r = await client.post(
            f"/api/models/{model_id}/run",
            data=_FORM,
            files={
                "dependency_manifest": ("package.json", manifest, "application/json"),
                "dependency_lockfile": ("package-lock.json", lockfile, "application/json"),
            },
        )
    _assert_clean_error(r, (413, 422))
    assert pipeline_spy == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "manifest",
    [
        {"dependencies": ["chalk"]},
        {"dependencies": {"chalk": 5}},
        {"dependencies": None},
        {},
    ],
    ids=["list", "non-string-version", "null", "no-dependencies"],
)
async def test_manifest_with_no_usable_dependencies_runs_without_a_dependency_step(
    model_id, pipeline_spy, manifest
):
    """Wrong-shaped sections are ignored rather than crashing; the run goes ahead with
    an empty dependency sweep."""
    async with _client() as client:
        r = await client.post(
            f"/api/models/{model_id}/run",
            data=_FORM,
            files={
                "dependency_manifest": (
                    "package.json",
                    json.dumps(manifest).encode(),
                    "application/json",
                )
            },
        )
    assert r.status_code == 200, r.text
    assert "Traceback" not in r.text


def _registry(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_nonexistent_package_is_reported_per_package_not_fatal():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "Not found"})

    async with _registry(handler) as client:
        context = await analyze.analyze_manifest(
            {"dependencies": {"no-such-pkg-xyz": "1.0.0", "also-missing": "^2.0.0"}},
            None,
            client=client,
        )
    assert [pa.ref.name for pa in context.packages] == ["also-missing", "no-such-pkg-xyz"]
    for pa in context.packages:
        assert pa.error is not None
        assert "404" in pa.error


@pytest.mark.asyncio
async def test_nonexistent_version_is_reported_with_a_clear_message():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "name": "chalk",
                "versions": {"5.3.0": {"dist": {"tarball": "https://r/chalk-5.3.0.tgz"}}},
            },
        )

    async with _registry(handler) as client:
        context = await analyze.analyze_manifest(
            {"dependencies": {"chalk": "99.0.0"}}, None, client=client
        )
    (pa,) = context.packages
    assert "chalk@99.0.0 not found on the npm registry" in pa.error


@pytest.mark.asyncio
async def test_registry_outage_is_reported_per_package():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network down", request=request)

    async with _registry(handler) as client:
        context = await analyze.analyze_manifest(
            {"dependencies": {"chalk": "5.3.0"}}, None, client=client
        )
    (pa,) = context.packages
    assert "ConnectError" in pa.error


@pytest.mark.asyncio
async def test_lockfile_entries_not_in_the_manifest_are_ignored():
    seen: list[str] = []

    async def fake_analyze(name, version, *_args):
        seen.append(f"{name}@{version}")
        raise ValueError("stop here")

    lockfile = {
        "packages": {
            "node_modules/chalk": {"version": "5.3.0"},
            "node_modules/left-pad": {"version": "1.3.0"},
        }
    }
    with patch.object(analyze, "analyze_package", new=fake_analyze):
        await analyze.analyze_manifest({"dependencies": {"chalk": "^5.0.0"}}, lockfile)
    assert seen == ["chalk@5.3.0"]


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    reason="Finding: a lockfile pin that doesn't satisfy the manifest range (a lockfile "
    "from another project or an out-of-sync one) is analyzed silently, with no skip "
    "reason or warning",
)
async def test_lockfile_pin_outside_the_manifest_range_is_flagged():
    seen: list[str] = []

    async def fake_analyze(name, version, *_args):
        seen.append(f"{name}@{version}")
        raise ValueError("stop here")

    lockfile = {"packages": {"node_modules/chalk": {"version": "2.4.2"}}}
    with patch.object(analyze, "analyze_package", new=fake_analyze):
        context = await analyze.analyze_manifest({"dependencies": {"chalk": "^5.3.0"}}, lockfile)
    assert "chalk" in context.skipped or seen != ["chalk@2.4.2"]


# ---------------------------------------------------------------------------
# Pipeline bounds (API)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 16, -1])
async def test_iteration_count_out_of_range_is_422(test_db, count):
    async with _client() as client:
        r = await client.post(
            "/api/models/",
            json={"title": "t", "description": _GOOD_DESCRIPTION, "iteration_count": count},
        )
    detail = _assert_clean_error(r, 422)
    assert "iteration_count" in detail
    assert await crud.list_threat_models() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [1, 15])
async def test_iteration_count_at_the_bounds_is_accepted(test_db, count):
    async with _client() as client:
        r = await client.post(
            "/api/models/",
            json={"title": "t", "description": _GOOD_DESCRIPTION, "iteration_count": count},
        )
    assert r.status_code == 201
    assert r.json()["iteration_count"] == count


@pytest.mark.asyncio
@pytest.mark.parametrize("description", ["", "short"], ids=["empty", "too-short"])
async def test_empty_or_short_description_is_422(test_db, description):
    async with _client() as client:
        r = await client.post("/api/models/", json={"title": "t", "description": description})
    _assert_clean_error(r, 422)
    assert await crud.list_threat_models() == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"title": "t", "description": " " * 40},
        {"title": "t", "description": "\n\t" * 20},
        {"title": "   ", "description": _GOOD_DESCRIPTION},
    ],
    ids=["spaces", "newlines-tabs", "blank-title"],
)
async def test_whitespace_only_fields_are_422(test_db, body):
    async with _client() as client:
        r = await client.post("/api/models/", json=body)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_patch_cannot_blank_the_description(model_id):
    async with _client() as client:
        r = await client.patch(f"/api/models/{model_id}", json={"description": ""})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_a_100kb_description_round_trips(test_db):
    """No upper bound on the API (the CLI caps files at 1 MB): 100 KB is stored whole."""
    description = ("A service that talks to a database. " * 3000)[:100_000]
    async with _client() as client:
        r = await client.post("/api/models/", json={"title": "big", "description": description})
        assert r.status_code == 201
        got = await client.get(f"/api/models/{r.json()['id']}")
    assert got.json()["description"] == description


# ---------------------------------------------------------------------------
# Pipeline bounds (CLI)
# ---------------------------------------------------------------------------


def _invoke_cli(monkeypatch, tmp_path, content: str | None, args: list[str]):
    """Run the CLI up to (not into) the pipeline; return (result, pipeline_called)."""
    cli_settings = Settings(
        default_provider="anthropic",
        default_model="claude-sonnet-5",
        anthropic_api_key="sk-ant-test",
        default_iterations=1,
    )
    monkeypatch.setattr("cli.commands.run._load_merged_settings", lambda: cli_settings)

    def _fake_create(provider_type, model, **kwargs):
        provider = MagicMock()
        provider.model = model
        return provider

    monkeypatch.setattr("cli.commands.run.create_provider", _fake_create)
    monkeypatch.setattr("backend.routes._helpers.create_provider", _fake_create)
    called: list[bool] = []

    async def _capture(**_kwargs):
        called.append(True)

    monkeypatch.setattr("cli.commands.run._run_pipeline_async", _capture)
    input_file = tmp_path / "system.md"
    input_file.write_text(content if content is not None else "", encoding="utf-8")
    result = CliRunner().invoke(run, [str(input_file), *args])
    return result, bool(called)


@pytest.mark.parametrize("n", ["0", "16"])
def test_cli_iterations_out_of_range_exit_2(monkeypatch, tmp_path, n):
    result, called = _invoke_cli(monkeypatch, tmp_path, _GOOD_DESCRIPTION, ["-n", n])
    assert result.exit_code == 2
    assert "1<=x<=15" in result.output
    assert "Traceback" not in result.output
    assert not called


@pytest.mark.parametrize("content", ["", "   \n\t \n"], ids=["empty", "whitespace"])
def test_cli_empty_or_whitespace_input_fails_cleanly(monkeypatch, tmp_path, content):
    result, called = _invoke_cli(monkeypatch, tmp_path, content, [])
    assert result.exit_code != 0
    assert "empty" in result.output.lower() or "whitespace" in result.output.lower()
    assert "Traceback" not in result.output
    assert not called


def test_cli_100kb_input_reaches_the_pipeline(monkeypatch, tmp_path):
    result, called = _invoke_cli(monkeypatch, tmp_path, "A web app with a DB. " * 5000, [])
    assert result.exit_code == 0, result.output
    assert called


# ---------------------------------------------------------------------------
# Auth tokens and the config secret
# ---------------------------------------------------------------------------


@pytest.fixture
def auth_on(monkeypatch):
    monkeypatch.setattr(settings, "paranoid_require_auth", True)


async def _user(name: str = "alice") -> dict:
    return await crud_auth.create_user(
        username=name,
        email=f"{name}@test.local",
        password_hash="unusable",  # noqa: S106 - tokens are minted directly
    )


async def _me(token: str) -> httpx.Response:
    async with _client() as client:
        return await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})


@pytest.mark.asyncio
async def test_expired_jwt_is_401(test_db, auth_on):
    import jwt as pyjwt

    from backend.auth.tokens import _get_jwt_key

    user = await _user()
    now = int(time.time())
    expired = pyjwt.encode(
        {"sub": user["id"], "iat": now - 3600, "exp": now - 60, "jti": "j"},
        _get_jwt_key(),
        algorithm="HS256",
    )
    detail = _assert_clean_error(await _me(expired), 401)
    assert "expired" in detail.lower()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "token",
    [
        "not-a-jwt",
        "a.b.c",
        "pat_",
        "pat_nounderscore",
        "pat_00000000-0000-0000-0000-000000000000_ab",
    ],
)
async def test_garbage_tokens_are_401(test_db, auth_on, token):
    _assert_clean_error(await _me(token), 401)


@pytest.mark.asyncio
async def test_unsigned_alg_none_jwt_is_401(test_db, auth_on):
    import base64

    user = await _user()

    def _b64(obj: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    now = int(time.time())
    token = (
        _b64({"alg": "none", "typ": "JWT"})
        + "."
        + _b64({"sub": user["id"], "iat": now, "exp": now + 600, "is_admin": True})
        + "."
    )
    _assert_clean_error(await _me(token), 401)


@pytest.mark.asyncio
async def test_revoked_pat_is_401(test_db, auth_on):
    user = await _user()
    token_id, raw, token_hash = create_pat()
    await crud_auth.create_pat(token_id, user["id"], "ci", token_hash)
    assert (await _me(raw)).status_code == 200
    await crud_auth.delete_pat(token_id, user["id"])
    _assert_clean_error(await _me(raw), 401)


@pytest.mark.asyncio
async def test_deleted_users_tokens_are_401(test_db, auth_on):
    """There is no delete-user route; a row removed directly (or by an admin script)
    must not leave its JWT or PAT working."""
    user = await _user()
    jwt = create_access_token(user["id"], "alice", False)
    token_id, raw, token_hash = create_pat()
    await crud_auth.create_pat(token_id, user["id"], "ci", token_hash)
    conn = await db.get()
    await conn.execute("DELETE FROM users WHERE id = ?", (user["id"],))
    await conn.commit()
    _assert_clean_error(await _me(jwt), 401)
    _assert_clean_error(await _me(raw), 401)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers",
    [{}, {"X-Config-Secret": "wrong"}, {"X-Config-Secret": ""}],
    ids=["missing", "wrong", "empty"],
)
async def test_config_patch_without_the_right_secret_is_403(test_db, monkeypatch, headers):
    monkeypatch.setattr(settings, "config_secret", "the-real-secret")
    before = settings.default_iterations
    async with _client() as client:
        r = await client.patch(
            "/api/config/", json={"default_iterations": before % 15 + 1}, headers=headers
        )
    detail = _assert_clean_error(r, 403)
    assert "X-Config-Secret" in detail
    assert settings.default_iterations == before


@pytest.mark.asyncio
async def test_config_patch_with_the_right_secret_is_200(test_db, monkeypatch):
    monkeypatch.setattr(settings, "config_secret", "the-real-secret")
    monkeypatch.setattr(settings, "default_iterations", 3)
    async with _client() as client:
        r = await client.patch(
            "/api/config/",
            json={"default_iterations": 4},
            headers={"X-Config-Secret": "the-real-secret"},
        )
    assert r.status_code == 200
    assert settings.default_iterations == 4


@pytest.mark.asyncio
async def test_config_patch_needs_a_login_when_auth_is_on(test_db, auth_on, monkeypatch):
    monkeypatch.setattr(settings, "config_secret", "")
    monkeypatch.setattr(settings, "default_iterations", 3)
    async with _client() as client:
        r = await client.patch("/api/config/", json={"default_iterations": 4})
    assert r.status_code == 401
    assert settings.default_iterations == 3
