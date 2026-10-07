"""Tests for model_diagrams persistence (migration 0008) — 4b-1.

Covers: crud round-trip, GET /api/models/{id}/diagrams[/{diagram_id}] RBAC
and content, that clear_model_data() preserves diagrams across a re-run
(a diagram is user input, not pipeline output), and _persist_diagram_data()
mapping DiagramData -> model_diagrams for both the mermaid and image
branches, including replacing an existing diagram on a fresh upload.
"""

import base64
import io
import json
import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

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
async def test_list_model_diagrams_without_image_content(test_db, model_id):
    """include_image_content=False omits png/jpeg content but keeps Mermaid
    text inline — unit-tested at the crud level in 5a-1 even though the
    route itself only switches to it in 5a-2."""
    await crud.create_model_diagram(
        model_id=model_id,
        name="arch.png",
        kind="png",
        content="aGVsbG8=",
        size_bytes=8,
        media_type="image/png",
    )
    await crud.create_model_diagram(
        model_id=model_id, name="flow.mmd", kind="mermaid", content="graph TD; A-->B", size_bytes=15
    )

    rows = await crud.list_model_diagrams(model_id, include_image_content=False)
    png_row = next(r for r in rows if r["kind"] == "png")
    mermaid_row = next(r for r in rows if r["kind"] == "mermaid")

    assert png_row["content"] is None
    assert png_row["has_content"] is False
    assert mermaid_row["content"] == "graph TD; A-->B"
    assert mermaid_row["has_content"] is True


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
async def test_replace_model_diagrams_is_atomic_delete_then_insert(test_db, model_id):
    await crud.create_model_diagram(
        model_id=model_id, name="a.mmd", kind="mermaid", content="graph TD; A-->B", size_bytes=15
    )
    new_ids = await crud.replace_model_diagrams(
        model_id,
        [{"name": "b.mmd", "kind": "mermaid", "content": "graph TD; C-->D", "size_bytes": 15}],
    )
    rows = await crud.list_model_diagrams(model_id)
    assert len(rows) == 1
    assert rows[0]["id"] == new_ids[0]
    assert rows[0]["name"] == "b.mmd"


@pytest.mark.asyncio
async def test_replace_model_diagrams_keeps_position_order(test_db, model_id):
    """3 rows in one replace must come back in the order they were given."""
    new_ids = await crud.replace_model_diagrams(
        model_id,
        [
            {"name": "first", "kind": "mermaid", "content": "graph TD; A", "size_bytes": 10},
            {"name": "second", "kind": "mermaid", "content": "graph TD; B", "size_bytes": 10},
            {"name": "third", "kind": "mermaid", "content": "graph TD; C", "size_bytes": 10},
        ],
    )
    rows = await crud.list_model_diagrams(model_id)
    assert [r["id"] for r in rows] == new_ids
    assert [r["name"] for r in rows] == ["first", "second", "third"]
    assert [r["position"] for r in rows] == [0, 1, 2]


@pytest.mark.asyncio
async def test_replace_model_diagrams_rolls_back_delete_on_failed_insert(test_db, model_id):
    """Regression: a plain execute+execute+commit left the DELETE pending
    on the shared connection when the INSERT failed, so an unrelated later
    write on that connection would commit it and silently wipe the diagram.
    db.writer()'s BEGIN IMMEDIATE must roll back both statements together."""
    await crud.create_model_diagram(
        model_id=model_id, name="a.mmd", kind="mermaid", content="graph TD; A-->B", size_bytes=15
    )
    with pytest.raises(sqlite3.IntegrityError):  # the kind CHECK constraint
        await crud.replace_model_diagrams(
            model_id,
            [
                {
                    "name": "b.mmd",
                    "kind": "not-a-valid-kind",
                    "content": "graph TD; C-->D",
                    "size_bytes": 15,
                }
            ],
        )
    # The original diagram must survive the failed replace.
    rows = await crud.list_model_diagrams(model_id)
    assert len(rows) == 1
    assert rows[0]["name"] == "a.mmd"

    # An unrelated later write on the shared connection must not resurrect
    # or commit any stray state left by the failed replace.
    await crud.update_threat_model(model_id, title="Renamed")
    rows = await crud.list_model_diagrams(model_id)
    assert len(rows) == 1
    assert rows[0]["name"] == "a.mmd"


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
    await _persist_diagram_data(model_id, [diagram_data])
    rows = await crud.list_model_diagrams(model_id)
    assert len(rows) == 1
    assert rows[0]["kind"] == "mermaid"
    assert rows[0]["content"] == "graph TD; A-->B"
    assert rows[0]["size_bytes"] == len(b"graph TD; A-->B")
    assert rows[0]["name"] == "arch"  # defaults to the source_path stem


@pytest.mark.asyncio
async def test_persist_diagram_data_image_branch(test_db, model_id):
    diagram_data = DiagramData(
        format=DiagramFormat.PNG,
        source_path="arch.png",
        base64_data="aGVsbG8=",
        media_type="image/png",
        size_bytes=8,
    )
    await _persist_diagram_data(model_id, [diagram_data])
    rows = await crud.list_model_diagrams(model_id)
    assert len(rows) == 1
    assert rows[0]["kind"] == "png"
    assert rows[0]["content"] == "aGVsbG8="
    assert rows[0]["media_type"] == "image/png"
    assert rows[0]["size_bytes"] == 8


@pytest.mark.asyncio
async def test_persist_diagram_data_multiple_rows_in_order(test_db, model_id):
    await _persist_diagram_data(
        model_id,
        [
            DiagramData(
                format=DiagramFormat.MERMAID,
                source_path="first.mmd",
                mermaid_source="graph TD; A",
                name="first",
            ),
            DiagramData(
                format=DiagramFormat.PNG,
                source_path="second.png",
                base64_data="aGVsbG8=",
                media_type="image/png",
                size_bytes=8,
                name="second",
            ),
        ],
    )
    rows = await crud.list_model_diagrams(model_id)
    assert [r["name"] for r in rows] == ["first", "second"]
    assert [r["position"] for r in rows] == [0, 1]


@pytest.mark.asyncio
async def test_persist_diagram_data_replaces_existing_diagram(test_db, model_id):
    """A fresh upload replaces the model's previous diagram(s) — the only
    case model_diagrams rows are ever removed before the run completes."""
    await _persist_diagram_data(
        model_id,
        [
            DiagramData(
                format=DiagramFormat.MERMAID,
                source_path="old.mmd",
                mermaid_source="graph TD; A-->B",
            )
        ],
    )
    await _persist_diagram_data(
        model_id,
        [
            DiagramData(
                format=DiagramFormat.MERMAID,
                source_path="new.mmd",
                mermaid_source="graph TD; C-->D",
            )
        ],
    )
    rows = await crud.list_model_diagrams(model_id)
    assert len(rows) == 1
    assert rows[0]["name"] == "new"  # defaults to the source_path stem


# ---------------------------------------------------------------------------
# POST /api/models/{id}/run — the real upload path, not just _persist_diagram_data
# directly (mirrors test_routes_run_dependencies.py's pattern for manifests).
# ---------------------------------------------------------------------------


def _noop_runner_factory():
    async def _noop_runner(*args, **kwargs):
        return
        yield  # pragma: no cover - makes this an async generator

    return _noop_runner


def _capturing_runner_factory(captured: dict):
    """Like _noop_runner_factory, but records the kwargs it was called with
    (e.g. to assert on the `diagrams` the route passed through)."""

    async def _runner(*args, **kwargs):
        captured.update(kwargs)
        return
        yield  # pragma: no cover - makes this an async generator

    return _runner


def _parse_sse_events(text: str) -> list[dict]:
    events = []
    for raw_chunk in text.strip().split("\n\n"):
        chunk = raw_chunk.strip()
        if chunk.startswith("data: "):
            events.append(json.loads(chunk[len("data: ") :]))
    return events


def _png_bytes(size: tuple[int, int] = (10, 10)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size).save(buf, format="PNG")
    return buf.getvalue()


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


# ---------------------------------------------------------------------------
# POST /api/models/{id}/run - multi-file upload (5a-1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_with_multiple_diagrams_persists_rows_in_order(client, model_id):
    captured: dict = {}
    with (
        patch("backend.routes.models.build_provider_from_record", return_value=MagicMock()),
        patch("backend.routes.models.build_fast_provider", return_value=None),
        patch(
            "backend.routes.models.run_pipeline_for_model",
            _capturing_runner_factory(captured),
        ),
    ):
        resp = await client.post(
            f"/api/models/{model_id}/run",
            data={**_MINIMAL_FORM, "diagram_names": json.dumps(["First", "Second", "Third"])},
            files=[
                ("diagrams", ("a.mmd", "graph TD; A", "text/plain")),
                ("diagrams", ("b.mmd", "graph TD; B", "text/plain")),
                ("diagrams", ("c.mmd", "graph TD; C", "text/plain")),
            ],
        )
    assert resp.status_code == 200
    rows = await crud.list_model_diagrams(model_id)
    assert [r["name"] for r in rows] == ["First", "Second", "Third"]
    assert [r["position"] for r in rows] == [0, 1, 2]
    assert [d.name for d in captured["diagrams"]] == ["First", "Second", "Third"]


@pytest.mark.asyncio
async def test_run_shim_diagram_field_lands_at_position_zero(client, model_id):
    """The deprecated singular diagram field, when combined with diagrams,
    is merged in first (position 0)."""
    with (
        patch("backend.routes.models.build_provider_from_record", return_value=MagicMock()),
        patch("backend.routes.models.build_fast_provider", return_value=None),
        patch("backend.routes.models.run_pipeline_for_model", _noop_runner_factory()),
    ):
        resp = await client.post(
            f"/api/models/{model_id}/run",
            data=_MINIMAL_FORM,
            files=[
                ("diagram", ("shim.mmd", "graph TD; S", "text/plain")),
                ("diagrams", ("b.mmd", "graph TD; B", "text/plain")),
            ],
        )
    assert resp.status_code == 200
    rows = await crud.list_model_diagrams(model_id)
    assert rows[0]["name"] == "shim"
    assert rows[0]["position"] == 0
    assert rows[1]["name"] == "b"
    assert rows[1]["position"] == 1


@pytest.mark.asyncio
async def test_run_six_diagrams_rejected_422(client, model_id):
    files = [("diagrams", (f"{i}.mmd", f"graph TD; {i}", "text/plain")) for i in range(6)]
    resp = await client.post(f"/api/models/{model_id}/run", data=_MINIMAL_FORM, files=files)
    assert resp.status_code == 422
    assert "Too many diagrams" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_run_five_diagrams_plus_shim_rejected_with_deprecated_field_message(client, model_id):
    files = [("diagram", ("shim.mmd", "graph TD; S", "text/plain"))] + [
        ("diagrams", (f"{i}.mmd", f"graph TD; {i}", "text/plain")) for i in range(5)
    ]
    resp = await client.post(f"/api/models/{model_id}/run", data=_MINIMAL_FORM, files=files)
    assert resp.status_code == 422
    assert "deprecated" in resp.json()["detail"]
    assert "diagram" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_run_oversize_diagram_rejected_413(client, model_id):
    from backend.image.validation import MAX_MERMAID_SIZE_BYTES

    oversize = "x" * (MAX_MERMAID_SIZE_BYTES + 1)
    resp = await client.post(
        f"/api/models/{model_id}/run",
        data=_MINIMAL_FORM,
        files={"diagrams": ("huge.mmd", oversize, "text/plain")},
    )
    assert resp.status_code == 413


@pytest.mark.asyncio
async def test_run_corrupt_png_rejected_422(client, model_id):
    resp = await client.post(
        f"/api/models/{model_id}/run",
        data=_MINIMAL_FORM,
        files={"diagrams": ("broken.png", b"not a real png", "image/png")},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_run_png_content_with_jpg_extension_rejected_422(client, model_id):
    """A real PNG uploaded with a .jpg extension fails the format-match check."""
    resp = await client.post(
        f"/api/models/{model_id}/run",
        data=_MINIMAL_FORM,
        files={"diagrams": ("mislabeled.jpg", _png_bytes(), "image/jpeg")},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_run_diagram_names_wrong_length_422(client, model_id):
    resp = await client.post(
        f"/api/models/{model_id}/run",
        data={**_MINIMAL_FORM, "diagram_names": json.dumps(["only-one"])},
        files=[
            ("diagrams", ("a.mmd", "graph TD; A", "text/plain")),
            ("diagrams", ("b.mmd", "graph TD; B", "text/plain")),
        ],
    )
    assert resp.status_code == 422
    assert "diagram_names" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_run_diagram_names_not_json_422(client, model_id):
    resp = await client.post(
        f"/api/models/{model_id}/run",
        data={**_MINIMAL_FORM, "diagram_names": "not json"},
        files={"diagrams": ("a.mmd", "graph TD; A", "text/plain")},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_run_diagram_name_sanitized_before_storage(client, model_id):
    unsafe_name = "<script>a" + chr(10) + "b</script>"
    with (
        patch("backend.routes.models.build_provider_from_record", return_value=MagicMock()),
        patch("backend.routes.models.build_fast_provider", return_value=None),
        patch("backend.routes.models.run_pipeline_for_model", _noop_runner_factory()),
    ):
        resp = await client.post(
            f"/api/models/{model_id}/run",
            data={**_MINIMAL_FORM, "diagram_names": json.dumps([unsafe_name])},
            files={"diagrams": ("a.mmd", "graph TD; A", "text/plain")},
        )
    assert resp.status_code == 200
    rows = await crud.list_model_diagrams(model_id)
    assert "<" not in rows[0]["name"]
    assert chr(10) not in rows[0]["name"]


@pytest.mark.asyncio
async def test_run_without_upload_passes_stored_diagrams_to_pipeline(client, model_id):
    """A re-run with no upload must reuse the stored diagrams - Results
    previously showed a diagram the re-run silently ignored."""
    await crud.create_model_diagram(
        model_id=model_id, name="a.mmd", kind="mermaid", content="graph TD; A-->B", size_bytes=15
    )
    captured: dict = {}
    with (
        patch("backend.routes.models.build_provider_from_record", return_value=MagicMock()),
        patch("backend.routes.models.build_fast_provider", return_value=None),
        patch(
            "backend.routes.models.run_pipeline_for_model",
            _capturing_runner_factory(captured),
        ),
    ):
        resp = await client.post(f"/api/models/{model_id}/run", data=_MINIMAL_FORM)
    assert resp.status_code == 200
    assert captured["diagrams"] is not None
    assert len(captured["diagrams"]) == 1


@pytest.mark.asyncio
async def test_run_stored_diagram_over_current_cap_is_skipped(client, model_id):
    """A row stored under a looser historical cap must be skipped (not
    fatal) if it no longer fits today's limits, and the rest of the set
    still reaches the pipeline."""
    from backend.image.validation import MAX_IMAGE_SIZE_BYTES

    oversize_b64 = base64.b64encode(b"x" * (MAX_IMAGE_SIZE_BYTES + 1)).decode("ascii")
    await crud.create_model_diagram(
        model_id=model_id,
        name="too-big.png",
        kind="png",
        content=oversize_b64,
        size_bytes=MAX_IMAGE_SIZE_BYTES + 1,
        media_type="image/png",
    )
    await crud.create_model_diagram(
        model_id=model_id, name="fine.mmd", kind="mermaid", content="graph TD; A-->B", size_bytes=15
    )

    captured: dict = {}
    with (
        patch("backend.routes.models.build_provider_from_record", return_value=MagicMock()),
        patch("backend.routes.models.build_fast_provider", return_value=None),
        patch(
            "backend.routes.models.run_pipeline_for_model",
            _capturing_runner_factory(captured),
        ),
    ):
        resp = await client.post(f"/api/models/{model_id}/run", data=_MINIMAL_FORM)
    assert resp.status_code == 200

    events = _parse_sse_events(resp.text)
    skip_events = [
        e for e in events if e["data"] and e["data"].get("warning") == "stored_diagram_skipped"
    ]
    assert len(skip_events) == 1
    assert events[0]["data"].get("warning") == "stored_diagram_skipped"
    assert skip_events[0]["data"]["skipped"][0]["name"] == "too-big"  # stem, not raw filename
    assert len(captured["diagrams"]) == 1


@pytest.mark.asyncio
async def test_run_stored_diagram_with_invalid_content_is_skipped(client, model_id):
    """A stored row whose size is within budget but whose content isn't a
    real image (4b-1's upload route never content-checked at all) must be
    skipped on reuse rather than resent to a vision API, where it would
    get a 400 from the provider."""
    not_really_png = base64.b64encode(b"x" * 100).decode("ascii")
    await crud.create_model_diagram(
        model_id=model_id,
        name="fake.png",
        kind="png",
        content=not_really_png,
        size_bytes=100,
        media_type="image/png",
    )
    await crud.create_model_diagram(
        model_id=model_id, name="fine.mmd", kind="mermaid", content="graph TD; A-->B", size_bytes=15
    )

    captured: dict = {}
    with (
        patch("backend.routes.models.build_provider_from_record", return_value=MagicMock()),
        patch("backend.routes.models.build_fast_provider", return_value=None),
        patch(
            "backend.routes.models.run_pipeline_for_model",
            _capturing_runner_factory(captured),
        ),
    ):
        resp = await client.post(f"/api/models/{model_id}/run", data=_MINIMAL_FORM)
    assert resp.status_code == 200

    events = _parse_sse_events(resp.text)
    skip_events = [
        e for e in events if e["data"] and e["data"].get("warning") == "stored_diagram_skipped"
    ]
    assert len(skip_events) == 1
    assert skip_events[0]["data"]["skipped"][0]["name"] == "fake"
    assert len(captured["diagrams"]) == 1
    assert captured["diagrams"][0].name == "fine"


@pytest.mark.asyncio
async def test_extract_without_upload_also_reuses_stored_diagrams(client, model_id):
    await crud.create_model_diagram(
        model_id=model_id, name="a.mmd", kind="mermaid", content="graph TD; A-->B", size_bytes=15
    )
    captured: dict = {}
    with (
        patch("backend.routes.models.build_provider_from_record", return_value=MagicMock()),
        patch("backend.routes.models.build_fast_provider", return_value=None),
        patch(
            "backend.routes.models.run_pipeline_for_model",
            _capturing_runner_factory(captured),
        ),
    ):
        resp = await client.post(f"/api/models/{model_id}/extract")
    assert resp.status_code == 200
    assert captured["diagrams"] is not None
    assert len(captured["diagrams"]) == 1


@pytest.mark.asyncio
async def test_get_diagrams_list_response_unchanged_includes_content(client, model_id):
    """5a-1 keeps GET /diagrams returning inline content; the
    include_image_content=False switch is deferred to 5a-2."""
    await crud.create_model_diagram(
        model_id=model_id,
        name="a.png",
        kind="png",
        content="aGVsbG8=",
        size_bytes=8,
        media_type="image/png",
    )
    resp = await client.get(f"/api/models/{model_id}/diagrams")
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["content"] == "aGVsbG8="


@pytest.mark.asyncio
async def test_run_with_diagrams_rejects_viewer_role(client, model_id):
    """POST /run requires editor; a viewer uploading diagrams is blocked
    the same way as a viewer with no diagrams — the run route's RBAC
    doesn't special-case the diagrams field."""
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
                data=_MINIMAL_FORM,
                files={"diagrams": ("a.mmd", "graph TD; A-->B", "text/plain")},
            )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    rows = await crud.list_model_diagrams(model_id)
    assert rows == []
