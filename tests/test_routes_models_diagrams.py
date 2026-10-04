"""Tests for model_diagrams persistence (migration 0008) — 4b-1.

Covers: crud round-trip, GET /api/models/{id}/diagrams[/{diagram_id}] RBAC
and content, that clear_model_data() preserves diagrams across a re-run
(a diagram is user input, not pipeline output), and _persist_diagram_data()
mapping DiagramData -> model_diagrams for both the mermaid and image
branches, including replacing an existing diagram on a fresh upload.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.auth.dependencies import get_current_user
from backend.db import crud
from backend.main import app
from backend.models.enums import DiagramFormat
from backend.models.extended import DiagramData
from backend.routes.models import _persist_diagram_data


_MINIMAL_FORM = {"assumptions": "[]", "has_ai_components": "false"}


@pytest.fixture
async def client(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def model_id(test_db):
    return await crud.create_threat_model(
        title="Test Service",
        description="A service with an uploaded architecture diagram.",
        provider="anthropic",
        model="claude-sonnet-4",
        framework="STRIDE",
        iteration_count=1,
    )


# ---------------------------------------------------------------------------
# crud
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_and_list_model_diagram(test_db, model_id):
    diagram_id = await crud.create_model_diagram(
        model_id=model_id,
        name="arch.mmd",
        kind="mermaid",
        content="graph TD; A-->B",
        size_bytes=15,
    )
    rows = await crud.list_model_diagrams(model_id)
    assert len(rows) == 1
    assert rows[0]["id"] == diagram_id
    assert rows[0]["kind"] == "mermaid"
    assert rows[0]["content"] == "graph TD; A-->B"
    assert rows[0]["media_type"] is None


@pytest.mark.asyncio
async def test_get_model_diagram_by_id(test_db, model_id):
    diagram_id = await crud.create_model_diagram(
        model_id=model_id,
        name="arch.png",
        kind="png",
        content="aGVsbG8=",
        size_bytes=8,
        media_type="image/png",
    )
    row = await crud.get_model_diagram(diagram_id)
    assert row is not None
    assert row["model_id"] == model_id
    assert row["media_type"] == "image/png"


@pytest.mark.asyncio
async def test_get_model_diagram_missing_returns_none(test_db):
    assert await crud.get_model_diagram("does-not-exist") is None


@pytest.mark.asyncio
async def test_clear_model_data_preserves_diagrams(test_db, model_id):
    """A diagram is user input (like a user_edited asset), not pipeline
    output like dependency_scans — a re-run that doesn't re-upload one must
    not wipe it, or the Results diagram tab would disappear after one re-run."""
    await crud.create_model_diagram(
        model_id=model_id, name="a.mmd", kind="mermaid", content="graph TD; A-->B", size_bytes=15
    )
    await crud.clear_model_data(model_id)
    rows = await crud.list_model_diagrams(model_id)
    assert len(rows) == 1
    assert rows[0]["name"] == "a.mmd"


@pytest.mark.asyncio
async def test_replace_model_diagram_is_atomic_delete_then_insert(test_db, model_id):
    await crud.create_model_diagram(
        model_id=model_id, name="a.mmd", kind="mermaid", content="graph TD; A-->B", size_bytes=15
    )
    new_id = await crud.replace_model_diagram(
        model_id=model_id, name="b.mmd", kind="mermaid", content="graph TD; C-->D", size_bytes=15
    )
    rows = await crud.list_model_diagrams(model_id)
    assert len(rows) == 1
    assert rows[0]["id"] == new_id
    assert rows[0]["name"] == "b.mmd"


# ---------------------------------------------------------------------------
# _persist_diagram_data
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_diagram_data_mermaid_branch(test_db, model_id):
    diagram_data = DiagramData(
        format=DiagramFormat.MERMAID,
        source_path="arch.mmd",
        mermaid_source="graph TD; A-->B",
    )
    await _persist_diagram_data(model_id, diagram_data)
    rows = await crud.list_model_diagrams(model_id)
    assert len(rows) == 1
    assert rows[0]["kind"] == "mermaid"
    assert rows[0]["content"] == "graph TD; A-->B"
    assert rows[0]["size_bytes"] == len(b"graph TD; A-->B")


@pytest.mark.asyncio
async def test_persist_diagram_data_image_branch(test_db, model_id):
    diagram_data = DiagramData(
        format=DiagramFormat.PNG,
        source_path="arch.png",
        base64_data="aGVsbG8=",
        media_type="image/png",
        size_bytes=8,
    )
    await _persist_diagram_data(model_id, diagram_data)
    rows = await crud.list_model_diagrams(model_id)
    assert len(rows) == 1
    assert rows[0]["kind"] == "png"
    assert rows[0]["content"] == "aGVsbG8="
    assert rows[0]["media_type"] == "image/png"
    assert rows[0]["size_bytes"] == 8


@pytest.mark.asyncio
async def test_persist_diagram_data_replaces_existing_diagram(test_db, model_id):
    """A fresh upload replaces the model's previous diagram(s) — the only
    case model_diagrams rows are ever removed before the run completes."""
    await _persist_diagram_data(
        model_id,
        DiagramData(
            format=DiagramFormat.MERMAID, source_path="old.mmd", mermaid_source="graph TD; A-->B"
        ),
    )
    await _persist_diagram_data(
        model_id,
        DiagramData(
            format=DiagramFormat.MERMAID, source_path="new.mmd", mermaid_source="graph TD; C-->D"
        ),
    )
    rows = await crud.list_model_diagrams(model_id)
    assert len(rows) == 1
    assert rows[0]["name"] == "new.mmd"


# ---------------------------------------------------------------------------
# POST /api/models/{id}/run — the real upload path, not just _persist_diagram_data
# directly (mirrors test_routes_run_dependencies.py's pattern for manifests).
# ---------------------------------------------------------------------------


def _noop_runner_factory():
    async def _noop_runner(*args, **kwargs):
        return
        yield  # pragma: no cover - makes this an async generator

    return _noop_runner


@pytest.mark.asyncio
async def test_run_with_diagram_upload_persists_row(client, model_id):
    with (
        patch("backend.routes.models.build_provider_from_record", return_value=MagicMock()),
        patch("backend.routes.models.build_fast_provider", return_value=None),
        patch("backend.routes.models.run_pipeline_for_model", _noop_runner_factory()),
    ):
        resp = await client.post(
            f"/api/models/{model_id}/run",
            data=_MINIMAL_FORM,
            files={"diagram": ("arch.mmd", "graph TD; A-->B", "text/plain")},
        )
    assert resp.status_code == 200
    rows = await crud.list_model_diagrams(model_id)
    assert len(rows) == 1
    assert rows[0]["kind"] == "mermaid"
    assert rows[0]["content"] == "graph TD; A-->B"


@pytest.mark.asyncio
async def test_run_without_diagram_preserves_existing_one(client, model_id):
    """Re-running a model without re-uploading a diagram must not delete the
    one already on file — the regression this unit's review caught."""
    await crud.create_model_diagram(
        model_id=model_id, name="a.mmd", kind="mermaid", content="graph TD; A-->B", size_bytes=15
    )
    with (
        patch("backend.routes.models.build_provider_from_record", return_value=MagicMock()),
        patch("backend.routes.models.build_fast_provider", return_value=None),
        patch("backend.routes.models.run_pipeline_for_model", _noop_runner_factory()),
    ):
        resp = await client.post(
            f"/api/models/{model_id}/run",
            data=_MINIMAL_FORM,
        )
    assert resp.status_code == 200
    rows = await crud.list_model_diagrams(model_id)
    assert len(rows) == 1
    assert rows[0]["name"] == "a.mmd"


# ---------------------------------------------------------------------------
# GET /api/models/{id}/diagrams
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_diagrams_unknown_model_returns_404(client):
    resp = await client.get("/api/models/does-not-exist/diagrams")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_diagrams_empty_list_for_new_model(client, model_id):
    resp = await client.get(f"/api/models/{model_id}/diagrams")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_diagrams_returns_persisted_rows(client, model_id):
    await crud.create_model_diagram(
        model_id=model_id, name="a.mmd", kind="mermaid", content="graph TD; A-->B", size_bytes=15
    )
    resp = await client.get(f"/api/models/{model_id}/diagrams")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["name"] == "a.mmd"


@pytest.mark.asyncio
async def test_get_single_diagram(client, model_id):
    diagram_id = await crud.create_model_diagram(
        model_id=model_id, name="a.mmd", kind="mermaid", content="graph TD; A-->B", size_bytes=15
    )
    resp = await client.get(f"/api/models/{model_id}/diagrams/{diagram_id}")
    assert resp.status_code == 200
    assert resp.json()["content"] == "graph TD; A-->B"


@pytest.mark.asyncio
async def test_get_single_diagram_missing_returns_404(client, model_id):
    resp = await client.get(f"/api/models/{model_id}/diagrams/does-not-exist")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_single_diagram_wrong_model_returns_404(client, model_id, test_db):
    other_model_id = await crud.create_threat_model(
        title="Other",
        description="Another model entirely.",
        provider="anthropic",
        model="claude-sonnet-4",
        framework="STRIDE",
        iteration_count=1,
    )
    diagram_id = await crud.create_model_diagram(
        model_id=other_model_id, name="a.mmd", kind="mermaid", content="x", size_bytes=1
    )
    resp = await client.get(f"/api/models/{model_id}/diagrams/{diagram_id}")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Authorization — mirrors test_get_dependencies_allows_viewer_role /
# test_get_dependencies_rejects_non_member in test_routes_run_dependencies.py
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_diagrams_allows_viewer_role(client, model_id):
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
            resp = await client.get(f"/api/models/{model_id}/diagrams")
        assert resp.status_code == 200
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_get_diagrams_rejects_non_member(client, model_id):
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
            resp = await client.get(f"/api/models/{model_id}/diagrams")
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)
