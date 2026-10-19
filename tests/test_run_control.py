"""Run control for POST /api/models/{id}/run (bug-bash plan §6, run order item 21).

The pipeline runs inside the SSE response generator, so the model's status
depends on how that generator ends. These tests drive the route with a fake
pipeline (no provider, no network) and check the status a model is left in
when the client goes away, when the server restarts mid-run, and when two runs
of one model overlap. Each strict xfail is a bug-bash finding: fixing it turns
the test XPASS, and the marker must go.
"""

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.config import settings
from backend.db import crud
from backend.main import app, lifespan
from backend.models.enums import ModelStatus
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


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    reason=(
        "Bug-bash finding (item 21): a client disconnect cancels the run inside the SSE "
        "generator, and `except Exception` doesn't see CancelledError, so the model stays "
        "'in_progress' forever. Results.svelte aborts the stream on onDestroy, so leaving "
        "the page mid-run does this."
    ),
)
async def test_client_disconnect_mid_run_does_not_leave_the_model_in_progress(model_id):
    started = asyncio.Event()

    async def hanging_runner(*args, **kwargs):
        yield PipelineEvent(step=PipelineStep.SUMMARIZE, status="started", message="go")
        started.set()
        await asyncio.Event().wait()

    p1, p2 = _providers()
    with p1, p2, patch("backend.routes.models.run_pipeline_for_model", hanging_runner):
        resp = await _open_run(model_id)

        async def consume() -> None:
            async for _ in resp.body_iterator:
                pass

        # Starlette cancels the response task when the client disconnects.
        task = asyncio.create_task(consume())
        await asyncio.wait_for(started.wait(), timeout=5)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    record = await crud.get_threat_model(model_id)
    assert record["status"] != ModelStatus.IN_PROGRESS.value


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
@pytest.mark.xfail(
    strict=True,
    reason=(
        "Bug-bash finding (item 21): two runs of one model are both accepted; each clears "
        "the model's data first and then persists its own results, so the threats are "
        "duplicated (20 instead of 10 on a live rules-only run)."
    ),
)
async def test_two_overlapping_runs_of_one_model_do_not_duplicate_threats(model_id):
    both_started = asyncio.Barrier(2)

    async def runner(*args, **kwargs):
        yield PipelineEvent(step=PipelineStep.SUMMARIZE, status="started", message="go")
        await both_started.wait()
        yield PipelineEvent(
            step=PipelineStep.COMPLETE,
            status="completed",
            message="done",
            data={"threats": make_stride_threats()},
        )

    p1, p2 = _providers()
    with p1, p2, patch("backend.routes.models.run_pipeline_for_model", runner):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            first, second = await asyncio.wait_for(
                asyncio.gather(
                    c.post(f"/api/models/{model_id}/run", data={"assumptions": "[]"}),
                    c.post(f"/api/models/{model_id}/run", data={"assumptions": "[]"}),
                ),
                timeout=10,
            )

    statuses = sorted([first.status_code, second.status_code])
    threats = await crud.list_threats(model_id)
    one_run = len(make_stride_threats().threats)
    # Either the second run is refused, or the results aren't doubled.
    assert statuses == [200, 409] or len(threats) == one_run


@pytest.mark.asyncio
async def test_a_failing_run_marks_the_model_failed(model_id):
    """The path that does work today: an exception from the pipeline."""

    async def failing_runner(*args, **kwargs):
        yield PipelineEvent(step=PipelineStep.SUMMARIZE, status="started", message="go")
        raise RuntimeError("boom")

    p1, p2 = _providers()
    with p1, p2, patch("backend.routes.models.run_pipeline_for_model", failing_runner):
        resp = await _open_run(model_id)
        with pytest.raises(RuntimeError):
            async for _ in resp.body_iterator:
                pass

    record = await crud.get_threat_model(model_id)
    assert record["status"] == ModelStatus.FAILED.value
