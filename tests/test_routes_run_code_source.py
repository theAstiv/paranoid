"""Route-level tests for code_source_id parameter in POST /api/models/{id}/run.

Covers four scenarios:
1. Non-existent code_source_id → 422 before SSE stream opens
2. Non-ready source (status != 'ready') → 422 before SSE stream opens
3. Ready source, MCPCodeExtractor succeeds → SSE contains summarize_code events
4. Ready source, MCPCodeExtractor raises → SSE contains failed event, pipeline continues
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.db import crud
from backend.main import app
from backend.mcp.errors import MCPBinaryNotFoundError
from backend.models.extended import CodeContext, CodeFile


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
    return sid


@pytest.fixture
async def cloning_source_id(test_db):
    sid = await crud.create_code_source(
        name="InProgressRepo",
        git_url="https://github.com/example/wip.git",
        ref=None,
        pat=None,
    )
    await crud.update_code_source_status(sid, status="cloning")
    return sid


def _parse_sse(content: bytes) -> list[dict]:
    """Extract data payloads from a raw SSE byte stream."""
    events = []
    for frame in content.decode().split("\n\n"):
        for line in frame.splitlines():
            if line.startswith("data:"):
                try:
                    events.append(json.loads(line[5:].strip()))
                except json.JSONDecodeError:
                    pass
    return events


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MINIMAL_FORM = {"assumptions": "[]", "has_ai_components": "false"}


def _with_source(source_id: str) -> dict:
    return {**_MINIMAL_FORM, "code_source_id": source_id}


# ---------------------------------------------------------------------------
# 1. Non-existent source → 422 (before stream)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_whitespace_code_source_is_ignored(client, model_id):
    """A code_source_id containing only whitespace is normalised to empty string
    and treated as no source requested — pipeline runs without code context."""

    async def _noop_runner(*args, **kwargs):
        return
        yield

    with (
        patch("backend.routes.models.build_provider_from_record", return_value=MagicMock()),
        patch("backend.routes.models.build_fast_provider", return_value=None),
        patch("backend.routes.models.run_pipeline_for_model", _noop_runner),
    ):
        resp = await client.post(
            f"/api/models/{model_id}/run",
            data={**_MINIMAL_FORM, "code_source_id": "   "},
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_run_unknown_code_source_returns_422(client, model_id):
    resp = await client.post(
        f"/api/models/{model_id}/run",
        data={**_MINIMAL_FORM, "code_source_id": "does-not-exist"},
    )
    assert resp.status_code == 422
    assert "not found" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 2. Non-ready source → 422 (before stream)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_cloning_source_returns_422(client, model_id, cloning_source_id):
    resp = await client.post(
        f"/api/models/{model_id}/run",
        data=_with_source(cloning_source_id),
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "cloning" in detail
    assert "ready" in detail


# ---------------------------------------------------------------------------
# 3. Ready source, MCPCodeExtractor succeeds → SSE progress events emitted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_with_ready_source_emits_code_context_events(client, model_id, ready_source_id):
    fake_context = CodeContext(
        repository="example/repo",
        files=[CodeFile(path="auth.py", content="def authenticate(): ...")],
        summary="Auth module",
    )

    mock_extractor = AsyncMock()
    mock_extractor.__aenter__ = AsyncMock(return_value=mock_extractor)
    mock_extractor.__aexit__ = AsyncMock(return_value=False)
    mock_extractor.extract_context = AsyncMock(return_value=fake_context)

    async def _noop_runner(*args, **kwargs):
        return
        yield  # make it an async generator

    with (
        patch("backend.routes.models.build_provider_from_record", return_value=MagicMock()),
        patch("backend.routes.models.build_fast_provider", return_value=None),
        patch("backend.routes.models.MCPCodeExtractor", return_value=mock_extractor),
        patch("backend.routes.models.run_pipeline_for_model", _noop_runner),
    ):
        resp = await client.post(
            f"/api/models/{model_id}/run",
            data=_with_source(ready_source_id),
        )

    assert resp.status_code == 200
    events = _parse_sse(resp.content)
    steps = [e.get("step") for e in events]
    assert "summarize_code" in steps

    started = next(
        e for e in events if e.get("step") == "summarize_code" and e.get("status") == "started"
    )
    assert "MyRepo" in started["message"]

    completed = next(
        (e for e in events if e.get("step") == "summarize_code" and e.get("status") == "completed"),
        None,
    )
    assert completed is not None
    assert "MyRepo" in completed["message"]


# ---------------------------------------------------------------------------
# 4. Ready source, MCPCodeExtractor raises → SSE failed event, pipeline continues
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_extractor_failure_emits_failed_event(client, model_id, ready_source_id):
    mock_extractor = AsyncMock()
    mock_extractor.__aenter__ = AsyncMock(return_value=mock_extractor)
    mock_extractor.__aexit__ = AsyncMock(return_value=False)
    mock_extractor.extract_context = AsyncMock(side_effect=RuntimeError("index corrupt"))

    async def _noop_runner(*args, **kwargs):
        return
        yield

    with (
        patch("backend.routes.models.build_provider_from_record", return_value=MagicMock()),
        patch("backend.routes.models.build_fast_provider", return_value=None),
        patch("backend.routes.models.MCPCodeExtractor", return_value=mock_extractor),
        patch("backend.routes.models.run_pipeline_for_model", _noop_runner),
    ):
        resp = await client.post(
            f"/api/models/{model_id}/run",
            data=_with_source(ready_source_id),
        )

    assert resp.status_code == 200
    events = _parse_sse(resp.content)

    failed = next(
        (e for e in events if e.get("step") == "summarize_code" and e.get("status") == "failed"),
        None,
    )
    assert failed is not None, "Expected a summarize_code/failed SSE event"
    assert "index corrupt" in failed["message"]


@pytest.mark.asyncio
async def test_run_binary_not_found_emits_clear_failed_message(client, model_id, ready_source_id):
    mock_extractor = AsyncMock()
    mock_extractor.__aenter__ = AsyncMock(return_value=mock_extractor)
    mock_extractor.__aexit__ = AsyncMock(return_value=False)
    mock_extractor.extract_context = AsyncMock(
        side_effect=MCPBinaryNotFoundError("context-link not found")
    )

    async def _noop_runner(*args, **kwargs):
        return
        yield

    with (
        patch("backend.routes.models.build_provider_from_record", return_value=MagicMock()),
        patch("backend.routes.models.build_fast_provider", return_value=None),
        patch("backend.routes.models.MCPCodeExtractor", return_value=mock_extractor),
        patch("backend.routes.models.run_pipeline_for_model", _noop_runner),
    ):
        resp = await client.post(
            f"/api/models/{model_id}/run",
            data=_with_source(ready_source_id),
        )

    assert resp.status_code == 200
    events = _parse_sse(resp.content)

    failed = next(
        (e for e in events if e.get("step") == "summarize_code" and e.get("status") == "failed"),
        None,
    )
    assert failed is not None
    assert "context-link" in failed["message"].lower() or "binary" in failed["message"].lower()
