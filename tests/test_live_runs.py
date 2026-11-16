"""Run state in the database (KL-10 narrowed, BB-72): claim, follow, resume, sweep."""

import asyncio
import json

import pytest

from backend.db import crud, crud_live_runs
from backend.models.enums import ModelStatus
from backend.pipeline import live_runs


@pytest.fixture
async def model_id(test_db):
    return await crud.create_threat_model(
        title="Live run",
        description="An API in front of a Postgres database.",
        provider="ollama",
        model="llama3.1:8b",
        framework="STRIDE",
        iteration_count=1,
    )


@pytest.fixture(autouse=True)
async def _no_leftover_runs(test_db):
    yield
    await live_runs.cancel_all_runs()


def _chunk(n: int) -> str:
    return f"data: {json.dumps({'step': 'summarize', 'n': n})}\n\n"


async def _gated(release: asyncio.Event, count: int = 2):
    for n in range(count):
        yield _chunk(n)
    await release.wait()
    yield _chunk(count)


async def _no_cancel() -> str:
    return _chunk(-1)


async def _collect(run_id: str, after: int = 0) -> list[str]:
    return [c async for c in live_runs.follow_run(run_id, after)]


def _ids(chunks: list[str]) -> list[int]:
    return [int(c.split("\n", 1)[0].removeprefix("id: ")) for c in chunks]


@pytest.mark.asyncio
async def test_two_simultaneous_starts_give_exactly_one_winner(model_id):
    release = asyncio.Event()
    results = await asyncio.gather(
        live_runs.start_run(model_id, _gated(release), _no_cancel),
        live_runs.start_run(model_id, _gated(release), _no_cancel),
        return_exceptions=True,
    )
    refused = [r for r in results if isinstance(r, live_runs.RunAlreadyActiveError)]
    started = [r for r in results if isinstance(r, live_runs.LiveRun)]
    assert len(refused) == 1
    assert len(started) == 1
    release.set()
    await asyncio.wait_for(started[0].task, timeout=5)


@pytest.mark.asyncio
async def test_a_follower_after_the_finish_replays_everything_and_the_final_status(model_id):
    release = asyncio.Event()
    release.set()
    run = await live_runs.start_run(model_id, _gated(release), _no_cancel)
    await asyncio.wait_for(run.task, timeout=5)

    chunks = await asyncio.wait_for(_collect(run.run_id), timeout=5)

    assert _ids(chunks) == [1, 2, 3]
    row = await crud_live_runs.get_latest_run("model", model_id)
    assert row["id"] == run.run_id
    assert row["status"] == "completed"


@pytest.mark.asyncio
async def test_after_resumes_without_duplicates(model_id):
    release = asyncio.Event()
    release.set()
    run = await live_runs.start_run(model_id, _gated(release), _no_cancel)
    await asyncio.wait_for(run.task, timeout=5)

    chunks = await asyncio.wait_for(_collect(run.run_id, after=2), timeout=5)

    assert _ids(chunks) == [3]


@pytest.mark.asyncio
async def test_a_live_follower_sees_events_written_after_it_attached(model_id):
    release = asyncio.Event()
    run = await live_runs.start_run(model_id, _gated(release), _no_cancel)
    follower = asyncio.create_task(_collect(run.run_id))
    await asyncio.sleep(0.1)
    assert not follower.done()
    release.set()
    chunks = await asyncio.wait_for(follower, timeout=5)
    assert _ids(chunks) == [1, 2, 3]


@pytest.mark.asyncio
async def test_a_failed_generator_records_status_failed(model_id):
    async def boom():
        yield _chunk(0)
        raise RuntimeError("provider exploded")

    run = await live_runs.start_run(model_id, boom(), _no_cancel)
    await asyncio.wait_for(run.task, timeout=5)

    row = await crud_live_runs.get_run_row(run.run_id)
    assert row["status"] == "failed"
    assert await crud_live_runs.get_active_run("model", model_id) is None


@pytest.mark.asyncio
async def test_a_finished_subject_can_be_claimed_again_and_keeps_only_the_latest_old_run(model_id):
    release = asyncio.Event()
    release.set()
    first = await live_runs.start_run(model_id, _gated(release), _no_cancel)
    await asyncio.wait_for(first.task, timeout=5)
    second = await live_runs.start_run(model_id, _gated(release), _no_cancel)
    await asyncio.wait_for(second.task, timeout=5)
    third = await live_runs.start_run(model_id, _gated(release), _no_cancel)
    await asyncio.wait_for(third.task, timeout=5)

    assert await crud_live_runs.get_run_row(first.run_id) is None
    assert await crud_live_runs.get_run_row(second.run_id) is not None
    assert await crud_live_runs.list_events(first.run_id) == []


async def _insert_foreign_run(model_id: str, heartbeat_at: str) -> str:
    run_id = "foreign-run"
    conn = await crud.db.get()
    await conn.execute(
        """
        INSERT INTO live_runs (id, subject_type, subject_id, kind, status, owner,
                               started_at, heartbeat_at, created_at, updated_at)
        VALUES (?, 'model', ?, 'run', 'running', 'other-host:1:abcd', ?, ?, ?, ?)
        """,
        (run_id, model_id, heartbeat_at, heartbeat_at, heartbeat_at, heartbeat_at),
    )
    await conn.commit()
    return run_id


@pytest.mark.asyncio
async def test_sweep_fails_a_stale_foreign_run_and_its_model(model_id):
    await crud.update_threat_model_status(model_id, ModelStatus.IN_PROGRESS.value)
    run_id = await _insert_foreign_run(model_id, "2020-01-01T00:00:00+00:00")

    swept = await crud_live_runs.sweep_stale_runs(60)

    assert swept == 1
    assert (await crud_live_runs.get_run_row(run_id))["status"] == "interrupted"
    assert (await crud.get_threat_model(model_id))["status"] == ModelStatus.FAILED.value
    # A follower is told why, not just handed a closed stream.
    events = await crud_live_runs.list_events(run_id)
    final = json.loads(events[-1][1].removeprefix("data: "))
    assert final["step"] == "complete"
    assert final["status"] == "failed"
    assert "server stopped" in final["message"]


@pytest.mark.asyncio
async def test_sweep_leaves_a_fresh_foreign_run_alone(model_id):
    run_id = await _insert_foreign_run(model_id, crud.now_iso())

    assert await crud_live_runs.sweep_stale_runs(60) == 0
    assert (await crud_live_runs.get_run_row(run_id))["status"] == "running"


@pytest.mark.asyncio
async def test_startup_leaves_a_live_run_of_another_server_and_its_model_alone(model_id):
    """A second server on the same database keeps its heartbeat fresh."""
    await crud.update_threat_model_status(model_id, ModelStatus.IN_PROGRESS.value)
    run_id = await _insert_foreign_run(model_id, crud.now_iso())

    assert await crud_live_runs.sweep_stale_runs() == 0
    assert await crud.fail_interrupted_runs() == 0

    assert (await crud_live_runs.get_run_row(run_id))["status"] == "running"
    assert (await crud.get_threat_model(model_id))["status"] == ModelStatus.IN_PROGRESS.value
    # ...and the unique index still refuses a second run of that model.
    with pytest.raises(live_runs.RunAlreadyActiveError):
        await live_runs.start_run(model_id, _gated(asyncio.Event()), _no_cancel)


@pytest.mark.asyncio
async def test_startup_still_fails_an_in_progress_model_that_has_no_run_row(model_id):
    await crud.update_threat_model_status(model_id, ModelStatus.IN_PROGRESS.value)

    assert await crud.fail_interrupted_runs() == 1
    assert (await crud.get_threat_model(model_id))["status"] == ModelStatus.FAILED.value


@pytest.mark.asyncio
async def test_a_dead_run_does_not_block_a_new_claim(model_id):
    """A crash then a quick Re-run must not wait for the next sweep."""
    await crud.update_threat_model_status(model_id, ModelStatus.IN_PROGRESS.value)
    dead = await _insert_foreign_run(model_id, "2020-01-01T00:00:00+00:00")
    release = asyncio.Event()
    release.set()

    run = await live_runs.start_run(model_id, _gated(release), _no_cancel)
    await asyncio.wait_for(run.task, timeout=5)

    assert (await crud_live_runs.get_run_row(dead)) is None or (
        await crud_live_runs.get_run_row(dead)
    )["status"] == "interrupted"


@pytest.mark.asyncio
async def test_a_failed_event_write_does_not_kill_the_run(model_id, monkeypatch):
    monkeypatch.setattr(live_runs, "_WRITE_RETRY_SECONDS", 0)
    real = crud_live_runs.append_event
    calls = {"n": 0}

    async def flaky(run_id: str, payload: str) -> int:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("database is locked")
        return await real(run_id, payload)

    monkeypatch.setattr(crud_live_runs, "append_event", flaky)
    release = asyncio.Event()
    release.set()

    run = await live_runs.start_run(model_id, _gated(release), _no_cancel)
    await asyncio.wait_for(run.task, timeout=5)

    assert (await crud_live_runs.get_run_row(run.run_id))["status"] == "completed"
    assert len(await crud_live_runs.list_events(run.run_id)) == 3


@pytest.mark.asyncio
async def test_a_run_that_dies_leaves_its_model_failed_not_in_progress(model_id):
    await crud.update_threat_model_status(model_id, ModelStatus.IN_PROGRESS.value)

    async def boom():
        yield _chunk(0)
        raise RuntimeError("generator crashed before marking the model")

    run = await live_runs.start_run(model_id, boom(), _no_cancel)
    await asyncio.wait_for(run.task, timeout=5)

    assert (await crud.get_threat_model(model_id))["status"] == ModelStatus.FAILED.value


@pytest.mark.asyncio
async def test_a_finish_that_cannot_be_recorded_does_not_block_the_model_forever(
    model_id, monkeypatch
):
    monkeypatch.setattr(live_runs, "_WRITE_RETRY_SECONDS", 0)

    async def broken(run_id: str, status: str) -> None:
        raise RuntimeError("database is locked")

    monkeypatch.setattr(crud_live_runs, "finish_run", broken)
    release = asyncio.Event()
    release.set()
    run = await live_runs.start_run(model_id, _gated(release), _no_cancel)
    await asyncio.wait_for(run.task, timeout=5)
    monkeypatch.undo()

    # The row is still 'running', but its heartbeat has stopped; age it.
    conn = await crud.db.get()
    await conn.execute(
        "UPDATE live_runs SET heartbeat_at = '2020-01-01T00:00:00+00:00' WHERE id = ?",
        (run.run_id,),
    )
    await conn.commit()

    again = await live_runs.start_run(model_id, _gated(release), _no_cancel)
    await asyncio.wait_for(again.task, timeout=5)


@pytest.mark.asyncio
async def test_deleting_a_model_removes_its_runs_and_events(model_id):
    release = asyncio.Event()
    release.set()
    run = await live_runs.start_run(model_id, _gated(release), _no_cancel)
    await asyncio.wait_for(run.task, timeout=5)
    assert await crud_live_runs.list_events(run.run_id)

    await crud.delete_threat_model(model_id)

    assert await crud_live_runs.get_run_row(run.run_id) is None
    assert await crud_live_runs.list_events(run.run_id) == []


@pytest.mark.asyncio
async def test_prune_deletes_old_finished_runs_but_not_recent_or_running_ones(model_id):
    release = asyncio.Event()
    release.set()
    run = await live_runs.start_run(model_id, _gated(release), _no_cancel)
    await asyncio.wait_for(run.task, timeout=5)

    assert await crud_live_runs.prune_finished_runs(7) == 0

    conn = await crud.db.get()
    await conn.execute(
        "UPDATE live_runs SET finished_at = '2020-01-01T00:00:00+00:00' WHERE id = ?",
        (run.run_id,),
    )
    await conn.commit()
    assert await crud_live_runs.prune_finished_runs(7) == 1
    assert await crud_live_runs.list_events(run.run_id) == []


@pytest.mark.asyncio
async def test_a_follower_is_woken_promptly_not_after_the_poll_interval(model_id, monkeypatch):
    monkeypatch.setattr(live_runs, "POLL_SECONDS", 5.0)
    release = asyncio.Event()
    run = await live_runs.start_run(model_id, _gated(release), _no_cancel)
    follower = asyncio.create_task(_collect(run.run_id))
    await asyncio.sleep(0.2)

    release.set()

    chunks = await asyncio.wait_for(follower, timeout=2)
    assert _ids(chunks) == [1, 2, 3]


@pytest.mark.asyncio
async def test_get_model_says_why_a_failed_model_failed(model_id):
    from backend.routes import models as models_routes

    await crud.update_threat_model_status(model_id, ModelStatus.IN_PROGRESS.value)
    await _insert_foreign_run(model_id, "2020-01-01T00:00:00+00:00")
    await crud_live_runs.sweep_stale_runs()

    resp = await models_routes.get_model(model_id, _authz=None)
    body = json.loads(resp.body)

    assert body["status"] == "failed"
    assert body["active_run"] is None
    assert "server stopped" in body["last_run_failure"]


@pytest.mark.asyncio
async def test_the_heartbeat_advances_while_a_run_is_going(model_id, monkeypatch):
    monkeypatch.setattr(live_runs, "HEARTBEAT_SECONDS", 0.05)
    release = asyncio.Event()
    run = await live_runs.start_run(model_id, _gated(release), _no_cancel)
    before = (await crud_live_runs.get_run_row(run.run_id))["heartbeat_at"]

    await asyncio.sleep(0.3)

    after = (await crud_live_runs.get_run_row(run.run_id))["heartbeat_at"]
    assert after > before
    release.set()
    await asyncio.wait_for(run.task, timeout=5)


@pytest.mark.asyncio
async def test_cancel_marks_the_run_interrupted_and_records_the_cancel_event(model_id):
    release = asyncio.Event()
    run = await live_runs.start_run(model_id, _gated(release), _no_cancel)
    await asyncio.sleep(0.1)

    await live_runs.cancel_all_runs()

    row = await crud_live_runs.get_run_row(run.run_id)
    assert row["status"] == "interrupted"
    events = await crud_live_runs.list_events(run.run_id)
    assert events[-1][1] == _chunk(-1)
