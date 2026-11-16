"""Pipeline runs that outlive the request that started them (BB-71, BB-72, KL-10).

POST /api/models/{id}/run used to run the pipeline inside its own SSE response,
so closing that response — which the UI does whenever you leave the Results
page — cancelled the run. A run is now a background task whose state lives in
the database (``live_runs`` / ``live_run_events``, see crud_live_runs.py):

- claiming a run is one INSERT guarded by a partial unique index, so two
  simultaneous starts give exactly one winner;
- every SSE chunk is stored with a sequence number, so a follower — in this
  process or another — can attach at any time and resume from ``after_seq``;
- a heartbeat lets a crashed process's run be found and failed afterwards.

Only the asyncio task (needed to cancel at shutdown) and a wake-up Condition
stay in process memory. Everything else about the app is still one-worker
(see known-bugs KL-10).
"""

import asyncio
import contextlib
import logging
import sqlite3
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field

from backend.db import crud_live_runs


logger = logging.getLogger(__name__)

HEARTBEAT_SECONDS = 15.0
SWEEP_INTERVAL_SECONDS = 30.0
# Database writes for a run's bookkeeping are retried this many times (a busy
# database is the usual reason one fails).
_WRITE_ATTEMPTS = 3
_WRITE_RETRY_SECONDS = 0.5
# How often a follower re-reads the DB when nothing wakes it.
POLL_SECONDS = 1.0


class RunAlreadyActiveError(RuntimeError):
    """The subject already has a run in progress."""


@dataclass
class LiveRun:
    run_id: str
    changed: asyncio.Condition = field(default_factory=asyncio.Condition)
    # Bumped on every change; a follower that read the DB at version N waits
    # for a version other than N, so a change between its read and its wait
    # isn't missed.
    version: int = 0
    # Its row was deleted under it; the run carries on without storing events.
    orphaned: bool = False
    task: asyncio.Task | None = None


# Runs driven by this process, keyed by subject ID (kept for cancel at shutdown).
_runs: dict[str, LiveRun] = {}


def get_run(subject_id: str) -> LiveRun | None:
    """Return this process's live run for the subject, or None."""
    return _runs.get(subject_id)


async def start_run(
    subject_id: str,
    events: AsyncIterator[str],
    on_cancel: Callable[[], Awaitable[str]],
    *,
    kind: str = "run",
    subject_type: str = "model",
) -> LiveRun:
    """Claim the subject, drive ``events`` in a background task, return the run.

    ``on_cancel`` runs if the task is cancelled (server shutdown): it must
    leave the model in a final state and return the SSE chunk that says so.
    Raises ``RunAlreadyActiveError`` if the subject already has a run in
    progress — two runs of one model each clear its data and then add their
    own threats.
    """
    run_id = await crud_live_runs.claim_run(subject_type, subject_id, kind)
    if run_id is None:
        raise RunAlreadyActiveError(subject_id)
    run = LiveRun(run_id=run_id)
    _runs[subject_id] = run
    # Never swept as stale, whatever its heartbeat does (a stalled event loop).
    crud_live_runs.LOCAL_RUN_IDS.add(run_id)
    run.task = asyncio.create_task(
        _drive(subject_id, run, events, on_cancel, kind, subject_type),
        name=f"pipeline-run-{subject_id}",
    )
    return run


async def follow_run(run_id: str, after_seq: int = 0) -> AsyncIterator[str]:
    """Yield the run's events after ``after_seq``, then live ones until it ends.

    Each chunk is prefixed with an SSE ``id:`` line so a client can resume.
    Works for a run driven by another process (polls the DB) and for a run
    that has already finished (replays, then returns).
    """
    cursor = after_seq
    while True:
        local = next((r for r in _runs.values() if r.run_id == run_id), None)
        seen = local.version if local is not None else 0
        events = await crud_live_runs.list_events(run_id, cursor)
        for seq, payload in events:
            yield f"id: {seq}\n{payload}"
            cursor = seq
        if events:
            continue
        row = await crud_live_runs.get_run_row(run_id)
        if row is None:
            return
        if row["status"] != "running":
            # Events are written before the status flips; take one last look.
            tail = await crud_live_runs.list_events(run_id, cursor)
            for seq, payload in tail:
                yield f"id: {seq}\n{payload}"
            return
        if local is None:
            await asyncio.sleep(POLL_SECONDS)
            continue
        async with local.changed:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    local.changed.wait_for(lambda run=local, v=seen: run.version != v),
                    POLL_SECONDS,
                )


async def cancel_all_runs() -> None:
    """Cancel every live run and wait until each has marked its subject."""
    tasks = [run.task for run in _runs.values() if run.task is not None]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def sweep_loop() -> None:
    """Periodically fail runs whose owner stopped heart-beating (crashed process)."""
    while True:
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
        try:
            swept = await crud_live_runs.sweep_stale_runs()
            await crud_live_runs.prune_finished_runs()
        except Exception:
            logger.exception("Stale-run sweep failed")
            continue
        if swept:
            logger.warning("Marked %d run(s) interrupted: their owner stopped responding", swept)


async def _bump(run: LiveRun) -> None:
    async with run.changed:
        run.version += 1
        run.changed.notify_all()


async def _retry(what: str, call: Callable[[], Awaitable[object]]) -> bool:
    """Run a bookkeeping DB write, retrying a few times; False if it never succeeded."""
    for attempt in range(1, _WRITE_ATTEMPTS + 1):
        try:
            await call()
            return True
        except Exception:
            logger.exception("%s failed (attempt %d/%d)", what, attempt, _WRITE_ATTEMPTS)
            if attempt < _WRITE_ATTEMPTS:
                await asyncio.sleep(_WRITE_RETRY_SECONDS)
    return False


async def _store_event(run: LiveRun, chunk: str) -> None:
    try:
        await crud_live_runs.append_event(run.run_id, chunk)
    except sqlite3.IntegrityError:
        # The run row is gone (its model was deleted under it): retrying can't
        # help, and every later event would fail the same way. Say so once.
        run.orphaned = True
        logger.warning(
            "Run %s was deleted while it ran; its events are no longer stored", run.run_id
        )


async def _publish(run: LiveRun, chunk: str) -> None:
    # A lost event must not kill the run: the generator persists the model's
    # data itself, and followers fall back to polling the model.
    if run.orphaned:
        return
    await _retry("Storing a run event", lambda: _store_event(run, chunk))
    await _bump(run)


async def _heartbeat(run_id: str) -> None:
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        try:
            await crud_live_runs.heartbeat(run_id)
        except Exception:
            logger.exception("Heartbeat for run %s failed", run_id)


async def _drive(
    subject_id: str,
    run: LiveRun,
    events: AsyncIterator[str],
    on_cancel: Callable[[], Awaitable[str]],
    kind: str,
    subject_type: str,
) -> None:
    status = "completed"
    beat = asyncio.create_task(_heartbeat(run.run_id))
    try:
        async for chunk in events:
            await _publish(run, chunk)
    except asyncio.CancelledError:
        # Nothing but shutdown cancels a run; without this the model would
        # stay 'in_progress' with no task behind it.
        status = "interrupted"
        try:
            await _publish(run, await on_cancel())
        except Exception:
            logger.exception("Could not mark the interrupted run of %s", subject_id)
        raise
    except Exception:
        # The run's own generator has already marked the model failed and
        # sent the failure event; this only keeps the traceback.
        status = "failed"
        logger.exception("Run for %s failed", subject_id)
    finally:
        beat.cancel()
        # Unregister before waking followers, so one that sees the run end and
        # immediately re-runs the model isn't refused. If the end can't be
        # recorded the row stays 'running' with a dead heartbeat, which the
        # next claim or sweep interrupts.
        await _retry(
            "Recording the end of a run", lambda: crud_live_runs.finish_run(run.run_id, status)
        )
        if status != "completed" and subject_type == "model" and kind == "run":
            # The generator normally marks the model failed itself; this covers a
            # run that died without doing so (e.g. a database error mid-run).
            await _retry(
                "Failing the model of a dead run",
                lambda: crud_live_runs.fail_model_if_in_progress(subject_id),
            )
        if _runs.get(subject_id) is run:
            del _runs[subject_id]
        crud_live_runs.LOCAL_RUN_IDS.discard(run.run_id)
        await _bump(run)
