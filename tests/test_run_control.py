"""Run control for POST /api/models/{id}/run (bug-bash plan §6, run order item 21).

The pipeline runs as a background task (backend/pipeline/live_runs.py) that the
SSE response only follows. These tests drive the route with a fake pipeline
(no provider, no network) and check the status a model is left in when the
client goes away, when the server stops or restarts mid-run, and when two runs
of one model overlap. Each strict xfail is a bug-bash finding: fixing it turns
the test XPASS, and the marker must go.
"""

import asyncio
import contextlib
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.config import settings
from backend.db import crud
from backend.main import app, lifespan
from backend.models.enums import ModelStatus
from backend.pipeline import live_runs
from backend.pipeline.runner import PipelineEvent, PipelineStep
from backend.routes import models as models_routes
from tests.fixtures.pipeline import make_stride_threats


@pytest.fixture
async def model_id(test_db):
    return await crud.create_threat_model(
        title="Run control",
        description="A web API with a Postgres database and a Redis session store.",
        provider="ollama",
        model="llama3.1:8b",
        framework="STRIDE",
        iteration_count=1,
    )


def _providers():
    return (
        patch("backend.routes.models.build_provider_from_record", return_value=MagicMock()),
        patch("backend.routes.models.build_fast_provider", return_value=None),
    )


async def _open_run(model_id: str):
    """Call the route the way FastAPI does, minus the dependency layer."""
    return await models_routes.run_pipeline(
        model_id,
        assumptions="[]",
        has_ai_components=False,
        diagram=None,
        diagrams=None,
        diagram_names=None,
        code_source_id="",
        dependency_manifest=None,
        dependency_lockfile=None,
        deps_source_mode="npm",
        use_code_source_manifest=False,
        _rate=None,
        _authz=None,
    )


@pytest.fixture(autouse=True)
async def _no_leftover_runs(test_db):
    """A test that leaves a run going must not leak it into the next test."""
    yield
    await live_runs.cancel_all_runs()


def _gated_runner(release: asyncio.Event, started: asyncio.Event | None = None):
    """A fake pipeline that starts, waits for `release`, then completes with threats."""

    async def runner(*args, **kwargs):
        yield PipelineEvent(step=PipelineStep.SUMMARIZE, status="started", message="go")
        if started is not None:
            started.set()
        await release.wait()
        yield PipelineEvent(
            step=PipelineStep.COMPLETE,
            status="completed",
            message="done",
            data={"threats": make_stride_threats()},
        )

    return runner


def _sse_payloads(chunks: list[str]) -> list[dict]:
    return [json.loads(c.removeprefix("data: ").strip()) for c in chunks]


async def _drain(resp) -> list[dict]:
    return _sse_payloads([chunk async for chunk in resp.body_iterator])


@pytest.mark.asyncio
async def test_client_disconnect_mid_run_does_not_stop_the_run(model_id):
    """BB-71: Results.svelte closes the stream whenever you leave the page."""
    started, release = asyncio.Event(), asyncio.Event()

    p1, p2 = _providers()
    with (
        p1,
        p2,
        patch("backend.routes.models.run_pipeline_for_model", _gated_runner(release, started)),
    ):
        resp = await _open_run(model_id)
        run = live_runs.get_run(model_id)

        async def consume() -> None:
            async for _ in resp.body_iterator:
                pass

        # Starlette cancels the response task when the client disconnects.
        task = asyncio.create_task(consume())
        await asyncio.wait_for(started.wait(), timeout=5)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        assert (await crud.get_threat_model(model_id))["status"] == ModelStatus.IN_PROGRESS.value
        release.set()
        await asyncio.wait_for(run.task, timeout=5)

    record = await crud.get_threat_model(model_id)
    assert record["status"] == ModelStatus.COMPLETED.value
    assert len(await crud.list_threats(model_id)) == len(make_stride_threats().threats)
    assert live_runs.get_run(model_id) is None


@pytest.mark.asyncio
async def test_a_page_opened_mid_run_gets_the_run_from_its_start(model_id):
    started, release = asyncio.Event(), asyncio.Event()

    p1, p2 = _providers()
    with (
        p1,
        p2,
        patch("backend.routes.models.run_pipeline_for_model", _gated_runner(release, started)),
    ):
        await _open_run(model_id)  # the wizard's stream, never read: its page went away
        await asyncio.wait_for(started.wait(), timeout=5)

        resp = await models_routes.follow_run(model_id, _authz=None)
        release.set()
        events = await asyncio.wait_for(_drain(resp), timeout=5)

    assert [(e["step"], e["status"]) for e in events] == [
        ("summarize", "started"),
        ("complete", "completed"),
    ]


@pytest.mark.asyncio
async def test_following_a_model_with_no_run_in_progress_is_404(model_id):
    # Also what a model stuck 'in_progress' by a server restart gets, so the UI
    # can offer Re-run instead of polling forever.
    await crud.update_threat_model_status(model_id, ModelStatus.IN_PROGRESS.value)
    with pytest.raises(HTTPException) as exc_info:
        await models_routes.follow_run(model_id, _authz=None)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_a_run_stopped_by_server_shutdown_marks_the_model_failed(model_id):
    started = asyncio.Event()

    p1, p2 = _providers()
    with (
        p1,
        p2,
        patch(
            "backend.routes.models.run_pipeline_for_model",
            _gated_runner(asyncio.Event(), started),
        ),
    ):
        resp = await _open_run(model_id)
        await asyncio.wait_for(started.wait(), timeout=5)
        await live_runs.cancel_all_runs()
        events = await asyncio.wait_for(_drain(resp), timeout=5)

    record = await crud.get_threat_model(model_id)
    assert record["status"] == ModelStatus.FAILED.value
    assert events[-1]["step"] == "complete"
    assert events[-1]["status"] == "failed"
    assert "interrupted" in events[-1]["message"]


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    reason=(
        "Bug-bash finding (item 21): nothing at startup resets a run the previous process "
        "never finished, so a model interrupted by a stop or crash stays 'in_progress' "
        "(seen on the Bedrock machine's 10-13 model)."
    ),
)
async def test_startup_marks_a_run_left_in_progress_as_failed(model_id, test_db, monkeypatch):
    await crud.update_threat_model_status(model_id, ModelStatus.IN_PROGRESS.value)
    monkeypatch.setattr(settings, "db_path", test_db)

    # The test_db fixture already owns the connection (no sqlite-vec in CI), so
    # the lifespan reuses it rather than opening and closing its own.
    with (
        patch("backend.main.db.initialize", new=AsyncMock()),
        patch("backend.main.db.close", new=AsyncMock()),
    ):
        async with lifespan(app):
            record = await crud.get_threat_model(model_id)

    assert record["status"] == ModelStatus.FAILED.value


@pytest.mark.asyncio
async def test_a_second_run_of_a_model_already_running_is_refused(model_id):
    """BB-73: two runs of one model each cleared its data, then both added their threats."""
    release = asyncio.Event()

    p1, p2 = _providers()
    with p1, p2, patch("backend.routes.models.run_pipeline_for_model", _gated_runner(release)):
        first = await _open_run(model_id)
        with pytest.raises(HTTPException) as exc_info:
            await _open_run(model_id)
        release.set()
        await asyncio.wait_for(_drain(first), timeout=5)

        # Once the first run has finished, the model can be run again.
        second = await _open_run(model_id)
        await asyncio.wait_for(_drain(second), timeout=5)

    assert exc_info.value.status_code == 409
    assert len(await crud.list_threats(model_id)) == len(make_stride_threats().threats)


@pytest.mark.asyncio
async def test_a_failing_run_marks_the_model_failed(model_id):
    async def failing_runner(*args, **kwargs):
        yield PipelineEvent(step=PipelineStep.SUMMARIZE, status="started", message="go")
        raise RuntimeError("boom")

    p1, p2 = _providers()
    with p1, p2, patch("backend.routes.models.run_pipeline_for_model", failing_runner):
        resp = await _open_run(model_id)
        events = await asyncio.wait_for(_drain(resp), timeout=5)

    record = await crud.get_threat_model(model_id)
    assert record["status"] == ModelStatus.FAILED.value
    assert events[-1]["status"] == "failed"
    assert events[-1]["message"] == "boom"
