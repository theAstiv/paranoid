"""Route-level tests for dependency_manifest/dependency_lockfile/deps_source_mode
in POST /api/models/{id}/run — W3-2.

Covers: JSON/size/count validation (422 before the SSE stream opens), the
DEPS_ANALYSIS_ENABLED kill switch, code-source auto-detect, and that parsed
manifests are actually threaded into run_pipeline_for_model. Also covers
GET /api/models/{id}/dependencies.
"""

import json
import shutil
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.auth.dependencies import get_current_user
from backend.config import settings
from backend.db import crud
from backend.main import app
from backend.sources.paths import clone_dir_for


@pytest.fixture
async def client(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def model_id(test_db):
    mid = await crud.create_threat_model(
        title="Test Service",
        description="A microservice that handles user authentication with JWT tokens and Redis sessions.",
        provider="anthropic",
        model="claude-sonnet-4",
        framework="STRIDE",
        iteration_count=1,
    )
    return mid


@pytest.fixture
async def ready_source_id(test_db):
    sid = await crud.create_code_source(
        name="MyRepo",
        git_url="https://github.com/example/repo.git",
        ref=None,
        pat=None,
    )
    await crud.update_code_source_status(sid, status="ready")
    clone_dir = clone_dir_for(sid)
    clone_dir.mkdir(parents=True, exist_ok=True)
    yield sid
    shutil.rmtree(clone_dir, ignore_errors=True)


_MINIMAL_FORM = {"assumptions": "[]", "has_ai_components": "false"}

_VALID_MANIFEST = json.dumps({"dependencies": {"lodash": "^4.17.21"}})


def _noop_runner_factory():
    captured: dict = {}

    async def _noop_runner(*args, **kwargs):
        captured.update(kwargs)
        return
        yield  # pragma: no cover - makes this an async generator

    return _noop_runner, captured


def _patched():
    return (
        patch("backend.routes.models.build_provider_from_record", return_value=MagicMock()),
        patch("backend.routes.models.build_fast_provider", return_value=None),
    )


# ---------------------------------------------------------------------------
# Validation (422 before the SSE stream opens)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_invalid_manifest_json_returns_422(client, model_id):
    resp = await client.post(
        f"/api/models/{model_id}/run",
        data={**_MINIMAL_FORM, "dependency_manifest": "not json"},
    )
    assert resp.status_code == 422
    assert "dependency_manifest" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_run_manifest_not_a_json_object_returns_422(client, model_id):
    resp = await client.post(
        f"/api/models/{model_id}/run",
        data={**_MINIMAL_FORM, "dependency_manifest": "[1, 2, 3]"},
    )
    assert resp.status_code == 422
    assert "JSON object" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_run_oversized_manifest_returns_422(client, model_id):
    huge = json.dumps({"dependencies": {f"pkg-{i}": "1.0.0" for i in range(1)}})
    huge = huge[:-1] + (",_pad_" + "x" * (1024 * 1024)) + "}"
    resp = await client.post(
        f"/api/models/{model_id}/run",
        data={**_MINIMAL_FORM, "dependency_manifest": huge},
    )
    assert resp.status_code == 422
    assert "exceeds" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_run_too_many_direct_dependencies_returns_422(client, model_id):
    manifest = json.dumps({"dependencies": {f"pkg-{i}": "1.0.0" for i in range(51)}})
    resp = await client.post(
        f"/api/models/{model_id}/run",
        data={**_MINIMAL_FORM, "dependency_manifest": manifest},
    )
    assert resp.status_code == 422
    assert "51 direct dependencies" in resp.json()["detail"]
    assert "limit is 50" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_run_lockfile_without_manifest_returns_422(client, model_id):
    resp = await client.post(
        f"/api/models/{model_id}/run",
        data={**_MINIMAL_FORM, "dependency_lockfile": json.dumps({"lockfileVersion": 3})},
    )
    assert resp.status_code == 422
    assert "requires" in resp.json()["detail"]
    assert "dependency_manifest" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_run_dependency_count_uses_resolvable_targets_not_raw_entries(client, model_id):
    """An unresolvable range (a git spec) doesn't count against the cap — the
    check must mirror what analyze_manifest() will actually attempt, not a
    naive count of every "dependencies" entry."""
    manifest = json.dumps(
        {
            "dependencies": {
                **{f"pkg-{i}": "1.0.0" for i in range(50)},
                "unresolvable-git-dep": "git+https://example.com/x.git",
            }
        }
    )
    runner, captured = _noop_runner_factory()
    p1, p2 = _patched()
    with (
        p1,
        p2,
        patch("backend.routes.models.run_pipeline_for_model", runner),
    ):
        resp = await client.post(
            f"/api/models/{model_id}/run",
            data={**_MINIMAL_FORM, "dependency_manifest": manifest},
        )
    # 50 resolvable + 1 unresolvable git spec = still at the 50 cap, not over it.
    assert resp.status_code == 200
    assert len(captured["dependency_manifest"]["dependencies"]) == 51


@pytest.mark.asyncio
async def test_run_invalid_lockfile_json_returns_422(client, model_id):
    resp = await client.post(
        f"/api/models/{model_id}/run",
        data={
            **_MINIMAL_FORM,
            "dependency_manifest": _VALID_MANIFEST,
            "dependency_lockfile": "not json",
        },
    )
    assert resp.status_code == 422
    assert "dependency_lockfile" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_run_invalid_deps_source_mode_returns_422(client, model_id):
    resp = await client.post(
        f"/api/models/{model_id}/run",
        data={
            **_MINIMAL_FORM,
            "dependency_manifest": _VALID_MANIFEST,
            "deps_source_mode": "github",
        },
    )
    assert resp.status_code == 422
    assert "deps_source_mode" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_manifest_rejected_when_deps_analysis_disabled(client, model_id, monkeypatch):
    monkeypatch.setattr(settings, "deps_analysis_enabled", False)
    resp = await client.post(
        f"/api/models/{model_id}/run",
        data={**_MINIMAL_FORM, "dependency_manifest": _VALID_MANIFEST},
    )
    assert resp.status_code == 422
    assert "disabled" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_run_auto_detect_skipped_when_deps_analysis_disabled(
    client, model_id, ready_source_id, monkeypatch
):
    monkeypatch.setattr(settings, "deps_analysis_enabled", False)
    (clone_dir_for(ready_source_id) / "package.json").write_text(
        json.dumps({"dependencies": {"lodash": "^4.17.21"}})
    )

    runner, captured = _noop_runner_factory()
    p1, p2 = _patched()
    with (
        p1,
        p2,
        patch("backend.routes.models.run_pipeline_for_model", runner),
    ):
        resp = await client.post(
            f"/api/models/{model_id}/run",
            data={
                **_MINIMAL_FORM,
                "code_source_id": ready_source_id,
                "use_code_source_manifest": "true",
            },
        )

    assert resp.status_code == 200
    assert captured.get("dependency_manifest") is None


# ---------------------------------------------------------------------------
# Auto-detect is opt-in
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_does_not_auto_detect_manifest_without_opt_in_flag(
    client, model_id, ready_source_id
):
    """A ready code source with a root package.json must NOT trigger
    dependency analysis unless use_code_source_manifest=true is explicitly
    sent — auto-detect does registry/codeload fetches and a Semgrep scan
    (up to deps_analysis_timeout_seconds), so it can't silently turn on for
    every code-source run."""
    (clone_dir_for(ready_source_id) / "package.json").write_text(
        json.dumps({"dependencies": {"lodash": "^4.17.21"}})
    )

    runner, captured = _noop_runner_factory()
    p1, p2 = _patched()
    with (
        p1,
        p2,
        patch("backend.routes.models.run_pipeline_for_model", runner),
    ):
        resp = await client.post(
            f"/api/models/{model_id}/run",
            data={**_MINIMAL_FORM, "code_source_id": ready_source_id},
        )

    assert resp.status_code == 200
    assert captured.get("dependency_manifest") is None


# ---------------------------------------------------------------------------
# Successful paths — parsed manifest reaches run_pipeline_for_model
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_passes_parsed_manifest_to_pipeline(client, model_id):
    runner, captured = _noop_runner_factory()
    p1, p2 = _patched()
    with (
        p1,
        p2,
        patch("backend.routes.models.run_pipeline_for_model", runner),
    ):
        resp = await client.post(
            f"/api/models/{model_id}/run",
            data={
                **_MINIMAL_FORM,
                "dependency_manifest": _VALID_MANIFEST,
                "deps_source_mode": "both",
            },
        )

    assert resp.status_code == 200
    assert captured["dependency_manifest"] == {"dependencies": {"lodash": "^4.17.21"}}
    assert captured["dependency_lockfile"] is None
    assert captured["dependency_source_mode"] == "both"


@pytest.mark.asyncio
async def test_run_auto_detects_manifest_from_ready_code_source(client, model_id, ready_source_id):
    manifest = {"dependencies": {"lodash": "^4.17.21"}}
    lockfile = {"lockfileVersion": 3, "packages": {"node_modules/lodash": {"version": "4.17.21"}}}
    (clone_dir_for(ready_source_id) / "package.json").write_text(json.dumps(manifest))
    (clone_dir_for(ready_source_id) / "package-lock.json").write_text(json.dumps(lockfile))

    runner, captured = _noop_runner_factory()
    p1, p2 = _patched()
    with (
        p1,
        p2,
        patch("backend.routes.models.run_pipeline_for_model", runner),
    ):
        resp = await client.post(
            f"/api/models/{model_id}/run",
            data={
                **_MINIMAL_FORM,
                "code_source_id": ready_source_id,
                "use_code_source_manifest": "true",
            },
        )

    assert resp.status_code == 200
    assert captured["dependency_manifest"] == manifest
    assert captured["dependency_lockfile"] == lockfile
    assert captured["dependency_source_mode"] == "npm"


@pytest.mark.asyncio
async def test_run_explicit_manifest_takes_priority_over_auto_detect(
    client, model_id, ready_source_id
):
    (clone_dir_for(ready_source_id) / "package.json").write_text(
        json.dumps({"dependencies": {"should-not-be-used": "1.0.0"}})
    )

    runner, captured = _noop_runner_factory()
    p1, p2 = _patched()
    with (
        p1,
        p2,
        patch("backend.routes.models.run_pipeline_for_model", runner),
    ):
        resp = await client.post(
            f"/api/models/{model_id}/run",
            data={
                **_MINIMAL_FORM,
                "code_source_id": ready_source_id,
                "use_code_source_manifest": "true",
                "dependency_manifest": _VALID_MANIFEST,
            },
        )

    assert resp.status_code == 200
    assert captured["dependency_manifest"] == {"dependencies": {"lodash": "^4.17.21"}}


@pytest.mark.asyncio
async def test_run_auto_detect_missing_package_json_is_silent(client, model_id, ready_source_id):
    """No package.json in the clone: auto-detect degrades to None, doesn't 422."""
    runner, captured = _noop_runner_factory()
    p1, p2 = _patched()
    with (
        p1,
        p2,
        patch("backend.routes.models.run_pipeline_for_model", runner),
    ):
        resp = await client.post(
            f"/api/models/{model_id}/run",
            data={
                **_MINIMAL_FORM,
                "code_source_id": ready_source_id,
                "use_code_source_manifest": "true",
            },
        )

    assert resp.status_code == 200
    assert captured.get("dependency_manifest") is None


@pytest.mark.asyncio
async def test_run_auto_detect_malformed_package_json_is_silent(client, model_id, ready_source_id):
    """A malformed package.json in someone else's repo must not fail the run."""
    (clone_dir_for(ready_source_id) / "package.json").write_text("{not valid json")

    runner, captured = _noop_runner_factory()
    p1, p2 = _patched()
    with (
        p1,
        p2,
        patch("backend.routes.models.run_pipeline_for_model", runner),
    ):
        resp = await client.post(
            f"/api/models/{model_id}/run",
            data={
                **_MINIMAL_FORM,
                "code_source_id": ready_source_id,
                "use_code_source_manifest": "true",
            },
        )

    assert resp.status_code == 200
    assert captured.get("dependency_manifest") is None


@pytest.mark.asyncio
async def test_run_auto_detect_over_cap_manifest_is_silent(client, model_id, ready_source_id):
    """An auto-detected manifest over the 50-dependency cap must degrade the
    same as a missing or malformed one — dropped, not silently truncated deep
    inside analyze_manifest() with no signal, and not a 422 either (it's not
    the user's own upload)."""
    (clone_dir_for(ready_source_id) / "package.json").write_text(
        json.dumps({"dependencies": {f"pkg-{i}": "1.0.0" for i in range(51)}})
    )

    runner, captured = _noop_runner_factory()
    p1, p2 = _patched()
    with (
        p1,
        p2,
        patch("backend.routes.models.run_pipeline_for_model", runner),
    ):
        resp = await client.post(
            f"/api/models/{model_id}/run",
            data={
                **_MINIMAL_FORM,
                "code_source_id": ready_source_id,
                "use_code_source_manifest": "true",
            },
        )

    assert resp.status_code == 200
    assert captured.get("dependency_manifest") is None


# ---------------------------------------------------------------------------
# GET /api/models/{id}/dependencies
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_dependencies_unknown_model_returns_404(client):
    resp = await client.get("/api/models/does-not-exist/dependencies")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_dependencies_empty_list_for_new_model(client, model_id):
    resp = await client.get(f"/api/models/{model_id}/dependencies")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_dependencies_returns_persisted_scans(client, model_id):
    await crud.create_dependency_scan(
        model_id=model_id,
        package="lodash",
        version="4.17.21",
        source_mode="npm",
        analysis={"status": "ok"},
    )
    resp = await client.get(f"/api/models/{model_id}/dependencies")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["package"] == "lodash"
    assert body[0]["analysis"] == {"status": "ok"}


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_with_manifest_rejects_viewer_role(client, model_id):
    """/run (editor-gated) must reject a viewer even when they send a
    perfectly valid dependency_manifest — validation happens after auth."""
    viewer_user = {"id": "viewer-user", "username": "viewer", "is_admin": False, "is_active": True}

    async def _viewer_override():
        return viewer_user

    app.dependency_overrides[get_current_user] = _viewer_override
    try:
        with (
            patch("backend.config.settings.paranoid_require_auth", True),
            patch(
                "backend.db.crud_projects.resolve_project_id_from_model",
                new=AsyncMock(return_value="proj-1"),
            ),
            patch(
                "backend.db.crud_projects.get_user_role_in_project",
                new=AsyncMock(return_value="viewer"),
            ),
        ):
            resp = await client.post(
                f"/api/models/{model_id}/run",
                data={**_MINIMAL_FORM, "dependency_manifest": _VALID_MANIFEST},
            )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_get_dependencies_allows_viewer_role(client, model_id):
    viewer_user = {"id": "viewer-user", "username": "viewer", "is_admin": False, "is_active": True}

    async def _viewer_override():
        return viewer_user

    app.dependency_overrides[get_current_user] = _viewer_override
    try:
        with (
            patch("backend.config.settings.paranoid_require_auth", True),
            patch(
                "backend.db.crud_projects.resolve_project_id_from_model",
                new=AsyncMock(return_value="proj-1"),
            ),
            patch(
                "backend.db.crud_projects.get_user_role_in_project",
                new=AsyncMock(return_value="viewer"),
            ),
        ):
            resp = await client.get(f"/api/models/{model_id}/dependencies")
        assert resp.status_code == 200
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_get_dependencies_rejects_non_member(client, model_id):
    outsider = {"id": "outsider", "username": "outsider", "is_admin": False, "is_active": True}

    async def _outsider_override():
        return outsider

    app.dependency_overrides[get_current_user] = _outsider_override
    try:
        with (
            patch("backend.config.settings.paranoid_require_auth", True),
            patch(
                "backend.db.crud_projects.resolve_project_id_from_model",
                new=AsyncMock(return_value="proj-1"),
            ),
            patch(
                "backend.db.crud_projects.get_user_role_in_project",
                new=AsyncMock(return_value=None),
            ),
        ):
            resp = await client.get(f"/api/models/{model_id}/dependencies")
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)
