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

import aiosqlite
import pytest
from fastapi import HTTPException

from backend.config import settings
from backend.db import crud, crud_projects
from backend.main import app, lifespan
from backend.models.enums import AssetType, ModelStatus
from backend.models.state import Asset, AssetsList, DataFlow, FlowsList
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
        has_ai_components="false",
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
async def test_a_run_that_fails_to_start_marks_the_model_failed(model_id):
    """Review C7: clear_model_data / the status update ran outside the guard, so a
    DB error there left the model 'pending' with no run behind it."""
    p1, p2 = _providers()
    with (
        p1,
        p2,
        patch(
            "backend.routes.models.crud.clear_model_data",
            AsyncMock(side_effect=aiosqlite.OperationalError("database is locked")),
        ),
    ):
        resp = await _open_run(model_id)
        events = await asyncio.wait_for(_drain(resp), timeout=5)

    assert (await crud.get_threat_model(model_id))["status"] == ModelStatus.FAILED.value
    assert events[-1]["status"] == "failed"
    assert "Failed to start the run" in events[-1]["message"]
    assert live_runs.get_run(model_id) is None


# ---------------------------------------------------------------------------
# POST /{id}/extract is a live run too (review C3)
# ---------------------------------------------------------------------------


async def _open_extract(model_id: str):
    return await models_routes.extract_model_context(model_id, _rate=None, _authz=None)


def _gated_extractor(release: asyncio.Event, started: asyncio.Event, finished: asyncio.Event):
    async def runner(*args, **kwargs):
        assert kwargs["stop_after"] == "extraction"
        yield PipelineEvent(step=PipelineStep.SUMMARIZE, status="started", message="go")
        started.set()
        await release.wait()
        yield PipelineEvent(step=PipelineStep.EXTRACT_ASSETS, status="completed", message="ok")
        finished.set()

    return runner


@pytest.mark.asyncio
async def test_extract_keeps_going_after_the_tab_closes(model_id):
    """It clears the generated context first; stopping halfway lost it for good."""
    started, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
    p1, p2 = _providers()
    with (
        p1,
        p2,
        patch(
            "backend.routes.models.run_pipeline_for_model",
            _gated_extractor(release, started, finished),
        ),
    ):
        resp = await _open_extract(model_id)
        run = live_runs.get_run(model_id)

        async def consume() -> None:
            async for _ in resp.body_iterator:
                pass

        task = asyncio.create_task(consume())
        await asyncio.wait_for(started.wait(), timeout=5)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        release.set()
        await asyncio.wait_for(run.task, timeout=5)

    assert finished.is_set()
    assert live_runs.get_run(model_id) is None


@pytest.mark.asyncio
async def test_extract_and_run_refuse_each_other_while_one_is_live(model_id):
    started, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
    p1, p2 = _providers()
    with (
        p1,
        p2,
        patch(
            "backend.routes.models.run_pipeline_for_model",
            _gated_extractor(release, started, finished),
        ),
    ):
        extract = await _open_extract(model_id)
        await asyncio.wait_for(started.wait(), timeout=5)
        with pytest.raises(HTTPException) as run_refused:
            await _open_run(model_id)
        with pytest.raises(HTTPException) as extract_refused:
            await _open_extract(model_id)
        release.set()
        await asyncio.wait_for(_drain(extract), timeout=5)

    assert run_refused.value.status_code == 409
    assert extract_refused.value.status_code == 409

    release = asyncio.Event()
    p1, p2 = _providers()
    with p1, p2, patch("backend.routes.models.run_pipeline_for_model", _gated_runner(release)):
        run = await _open_run(model_id)
        with pytest.raises(HTTPException) as during_run:
            await _open_extract(model_id)
        release.set()
        await asyncio.wait_for(_drain(run), timeout=5)

    assert during_run.value.status_code == 409


@pytest.mark.asyncio
async def test_a_page_opened_mid_extract_follows_it_from_its_start(model_id):
    started, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
    p1, p2 = _providers()
    with (
        p1,
        p2,
        patch(
            "backend.routes.models.run_pipeline_for_model",
            _gated_extractor(release, started, finished),
        ),
    ):
        await _open_extract(model_id)
        await asyncio.wait_for(started.wait(), timeout=5)
        resp = await models_routes.follow_run(model_id, _authz=None)
        release.set()
        events = await asyncio.wait_for(_drain(resp), timeout=5)

    assert [(e["step"], e["status"]) for e in events] == [
        ("summarize", "started"),
        ("extract_assets", "completed"),
    ]


@pytest.mark.asyncio
async def test_an_extract_stopped_by_shutdown_says_so_and_leaves_the_status(model_id):
    started, finished = asyncio.Event(), asyncio.Event()
    await crud.update_threat_model_status(model_id, ModelStatus.COMPLETED.value)
    p1, p2 = _providers()
    with (
        p1,
        p2,
        patch(
            "backend.routes.models.run_pipeline_for_model",
            _gated_extractor(asyncio.Event(), started, finished),
        ),
    ):
        resp = await _open_extract(model_id)
        await asyncio.wait_for(started.wait(), timeout=5)
        await live_runs.cancel_all_runs()
        events = await asyncio.wait_for(_drain(resp), timeout=5)

    assert events[-1]["status"] == "failed"
    assert "Extraction interrupted" in events[-1]["message"]
    assert (await crud.get_threat_model(model_id))["status"] == ModelStatus.COMPLETED.value


def _extraction_events(*, flows_fail: bool = False):
    """A fake extractor: assets, then flows (or a provider failure), then COMPLETE."""

    async def runner(*args, **kwargs):
        yield PipelineEvent(
            step=PipelineStep.EXTRACT_ASSETS,
            status="completed",
            message="ok",
            data={
                "assets": AssetsList(
                    assets=[Asset(type=AssetType.ASSET, name="Fresh asset", description="")]
                )
            },
        )
        if flows_fail:
            yield PipelineEvent(
                step=PipelineStep.COMPLETE,
                status="failed",
                message="LLM provider unavailable — nothing was extracted",
            )
            return
        yield PipelineEvent(
            step=PipelineStep.EXTRACT_FLOWS,
            status="completed",
            message="ok",
            data={
                "flows": FlowsList(
                    data_flows=[
                        DataFlow(
                            flow_description="new", source_entity="Fresh asset", target_entity="X"
                        )
                    ],
                    trust_boundaries=[],
                    threat_sources=[],
                )
            },
        )
        yield PipelineEvent(step=PipelineStep.COMPLETE, status="completed", message="done")

    return runner


async def _seed_previous_run(model_id: str) -> None:
    await crud.create_asset(model_id, "Asset", "Old asset", "")
    await crud.create_flow(model_id, "data", "old", "Old asset", "Y")
    await crud.create_threat(
        model_id=model_id,
        name="Old threat",
        description="An earlier run's threat that a failed Re-extract must not delete.",
        target="Old asset",
        impact="High",
        likelihood="Medium",
        mitigations=["Fix it"],
        stride_category="Tampering",
    )


async def _context_names(model_id: str) -> tuple[list[str], list[str], list[str]]:
    return (
        [a["name"] for a in await crud.list_assets(model_id)],
        [f["flow_description"] for f in await crud.list_flows(model_id)],
        [t["name"] for t in await crud.list_threats(model_id)],
    )


@pytest.mark.asyncio
async def test_an_extract_that_cannot_clear_reports_failure(model_id):
    p1, p2 = _providers()
    with (
        p1,
        p2,
        patch("backend.routes.models.run_pipeline_for_model", _extraction_events()),
        patch(
            "backend.routes.models.crud.clear_model_data",
            AsyncMock(side_effect=aiosqlite.OperationalError("database is locked")),
        ),
    ):
        resp = await _open_extract(model_id)
        events = await asyncio.wait_for(_drain(resp), timeout=5)

    assert events[-1]["status"] == "failed"
    assert "Failed to save the extraction" in events[-1]["message"]
    assert live_runs.get_run(model_id) is None
    assert await crud.list_assets(model_id) == []


@pytest.mark.asyncio
async def test_an_extract_that_fails_part_way_leaves_the_previous_context(model_id):
    """It used to clear everything before the first LLM call (found in the PR #215 check)."""
    await _seed_previous_run(model_id)
    p1, p2 = _providers()
    with (
        p1,
        p2,
        patch("backend.routes.models.run_pipeline_for_model", _extraction_events(flows_fail=True)),
    ):
        events = await asyncio.wait_for(_drain(await _open_extract(model_id)), timeout=5)

    assert events[-1]["status"] == "failed"
    assert await _context_names(model_id) == (["Old asset"], ["old"], ["Old threat"])


@pytest.mark.asyncio
async def test_a_finished_extract_replaces_the_generated_context(model_id):
    await _seed_previous_run(model_id)
    p1, p2 = _providers()
    with p1, p2, patch("backend.routes.models.run_pipeline_for_model", _extraction_events()):
        events = await asyncio.wait_for(_drain(await _open_extract(model_id)), timeout=5)

    assert events[-1]["status"] == "completed"
    assert await _context_names(model_id) == (["Fresh asset"], ["new"], [])


@pytest.mark.asyncio
async def test_extract_uses_the_models_iterations_and_the_project_temperature(model_id):
    record = await crud.get_threat_model(model_id)
    await crud_projects.update_project(record["project_id"], default_temperature=0.7)
    seen: dict = {}

    async def runner(*args, **kwargs):
        seen.update(kwargs)
        yield PipelineEvent(step=PipelineStep.COMPLETE, status="completed", message="done")

    p1, p2 = _providers()
    with p1, p2, patch("backend.routes.models.run_pipeline_for_model", runner):
        await asyncio.wait_for(_drain(await _open_extract(model_id)), timeout=5)

    assert seen["max_iterations"] == 1
    assert seen["temperature"] == 0.7


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
