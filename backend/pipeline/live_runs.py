"""Pipeline runs that outlive the request that started them (BB-71).

POST /api/models/{id}/run used to run the pipeline inside its own SSE response,
so closing that response — which the UI does whenever you leave the Results
page — cancelled the run and left the model 'in_progress' for good. A run is
now a background task keyed by model ID. The POST response and
GET /api/models/{id}/run/events only *follow* its events: a follower that goes
away doesn't touch the run, and a page opened mid-run replays it from the
start.

Module-level state, single-process FastAPI (same as backend/sources/manager.py).
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field


logger = logging.getLogger(__name__)


class RunAlreadyActiveError(RuntimeError):
    """The model already has a run in progress."""


@dataclass
class LiveRun:
    # Every SSE chunk the run has produced, so a late follower gets them all.
    events: list[str] = field(default_factory=list)
    done: bool = False
    changed: asyncio.Condition = field(default_factory=asyncio.Condition)
    task: asyncio.Task | None = None


_runs: dict[str, LiveRun] = {}


def get_run(model_id: str) -> LiveRun | None:
    """Return the model's live run, or None when nothing is running."""
    return _runs.get(model_id)


def start_run(
    model_id: str,
    events: AsyncIterator[str],
    on_cancel: Callable[[], Awaitable[str]],
) -> LiveRun:
    """Drive ``events`` in a background task and return the run to follow.

    ``on_cancel`` runs if the task is cancelled (server shutdown): it must
    leave the model in a final state and return the SSE chunk that says so.
    Raises ``RunAlreadyActiveError`` if the model is already running — two
    runs of one model each clear its data and then add their own threats.
    """
    if model_id in _runs:
        raise RunAlreadyActiveError(model_id)
    run = LiveRun()
    _runs[model_id] = run
    run.task = asyncio.create_task(
        _drive(model_id, run, events, on_cancel), name=f"pipeline-run-{model_id}"
    )
    return run


async def follow_run(run: LiveRun) -> AsyncIterator[str]:
    """Yield every event of ``run`` from its first, then live ones until it ends."""
    sent = 0
    while True:
        async with run.changed:
            await run.changed.wait_for(lambda sent=sent: sent < len(run.events) or run.done)
            pending = run.events[sent:]
            done = run.done
        sent += len(pending)
        for chunk in pending:
            yield chunk
        if done:
            return


async def cancel_all_runs() -> None:
    """Cancel every live run and wait until each has marked its model."""
    tasks = [run.task for run in _runs.values() if run.task is not None]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def _publish(run: LiveRun, chunk: str) -> None:
    async with run.changed:
        run.events.append(chunk)
        run.changed.notify_all()


async def _drive(
    model_id: str,
    run: LiveRun,
    events: AsyncIterator[str],
    on_cancel: Callable[[], Awaitable[str]],
) -> None:
    try:
        async for chunk in events:
            await _publish(run, chunk)
    except asyncio.CancelledError:
        # Nothing but shutdown cancels a run now; without this the model would
        # stay 'in_progress' with no task behind it.
        try:
            await _publish(run, await on_cancel())
        except Exception:
            logger.exception("Could not mark the interrupted run of model %s", model_id)
        raise
    except Exception:
        # The run's own generator has already marked the model failed and
        # sent the failure event; this only keeps the traceback.
        logger.exception("Pipeline run for model %s failed", model_id)
    finally:
        # Unregister before waking followers, so one that sees the run end and
        # immediately re-runs the model isn't refused.
        if _runs.get(model_id) is run:
            del _runs[model_id]
        async with run.changed:
            run.done = True
            run.changed.notify_all()
