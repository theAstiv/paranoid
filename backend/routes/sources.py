"""Code source CRUD and SSE progress routes.

Mounted at /api/sources from backend.main.
"""

import asyncio
import contextlib
import logging
import shutil
from collections.abc import AsyncGenerator
from typing import Annotated

import aiosqlite
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse

from backend.auth.dependencies import (
    check_project_role,
    get_current_user,
    require_active_project,
    require_role,
    visible_project_ids,
)
from backend.config import settings
from backend.db import crud, crud_live_runs, crud_projects
from backend.models.extended import CodeSource, CreateCodeSourceRequest, MoveCodeSourceRequest
from backend.pipeline import live_runs
from backend.security.rate_limit import write_rate_limit
from backend.security.source_key import (
    KeySourceChangedError,
    SourceKeyUnavailableError,
)
from backend.sources import manager as mgr
from backend.sources.manager import SourceEvent
from backend.sources.paths import clone_dir_for, index_db_for


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sources", tags=["sources"])

_TERMINAL_STATUSES = frozenset({"ready", "failed"})
# Idle time after which the events stream sends a ping.
_KEEPALIVE_SECONDS = 30.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _source_response(row: dict, status_code: int = 200) -> JSONResponse:
    """Validate and serialise a code_sources dict into a JSON response."""
    model = CodeSource(**row)
    return JSONResponse(content=model.model_dump(), status_code=status_code)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("")
async def list_sources(
    user: Annotated[dict, Depends(get_current_user)],
    project_id: str | None = None,
) -> JSONResponse:
    """List code sources, optionally for one project.

    Non-admin callers only see sources from projects they belong to (the same
    rule as GET /models/). Auth off resolves to the instance admin.
    """
    project_ids = await visible_project_ids(user, project_id)
    rows = await crud.list_code_sources(project_id=project_id, project_ids=project_ids)
    items = [CodeSource(**r).model_dump() for r in rows]
    return JSONResponse(content=items)


@router.post("", status_code=202)
async def create_source(
    body: CreateCodeSourceRequest,
    user: Annotated[dict, Depends(get_current_user)],
    _rate: None = Depends(write_rate_limit),
) -> JSONResponse:
    """Create a code source row and kick off a background clone + index."""
    target_project_id = body.project_id or crud_projects.DEFAULT_PROJECT_ID
    if settings.paranoid_require_auth:
        await check_project_role(user, target_project_id, "editor")
    project = await crud_projects.get_project(target_project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    require_active_project(project)

    # Validate URL before touching the DB — cheap fail-fast.
    try:
        mgr.validate_git_url(body.git_url)
    except mgr.HostNotAllowedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if body.ref:
        try:
            mgr.validate_git_ref(body.ref)
        except mgr.InvalidRefError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    pat = body.pat.get_secret_value() if body.pat else None

    try:
        source_id = await crud.create_code_source(
            name=body.name,
            git_url=body.git_url,
            ref=body.ref,
            pat=pat,
            project_id=target_project_id,
            created_by=user["id"],
        )
    except aiosqlite.IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="A code source with this URL and ref already exists.",
        ) from exc
    except (SourceKeyUnavailableError, KeySourceChangedError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    # A new source has no run yet, so the claim can't be refused.
    await mgr.schedule_clone_and_index(source_id)

    row = await crud.get_code_source(source_id)
    if row is None:
        raise HTTPException(
            status_code=500, detail="Source was created but could not be read back."
        )
    return _source_response(row, status_code=202)


@router.get("/{source_id}")
async def get_source(
    source_id: str,
    _authz: None = Depends(require_role("viewer", "source_id", "source")),
) -> JSONResponse:
    """Get a single code source by ID."""
    row = await crud.get_code_source(source_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Source not found.")
    return _source_response(row)


@router.patch("/{source_id}")
async def move_source(
    source_id: str,
    body: MoveCodeSourceRequest,
    user: Annotated[dict, Depends(get_current_user)],
    _authz: None = Depends(require_role("owner", "source_id", "source")),
) -> JSONResponse:
    """Move a source to another project (owner of the current project, editor of the target).

    Sources that predate projects all sit in the Default Project; a model can only
    use a source from its own project, so this puts them where their models are.
    """
    if settings.paranoid_require_auth:
        await check_project_role(user, body.project_id, "editor")
    target = await crud_projects.get_project(body.project_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    # The source's own project is checked by require_role; the target too.
    require_active_project(target)

    await crud.update_code_source_project(source_id, body.project_id)
    row = await crud.get_code_source(source_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Source not found.")
    return _source_response(row)


@router.post("/{source_id}/reindex", status_code=202)
async def reindex_source(
    source_id: str,
    _rate: None = Depends(write_rate_limit),
    _authz: None = Depends(require_role("editor", "source_id", "source")),
) -> JSONResponse:
    """Trigger a manual re-clone + re-index for an existing source."""
    row = await crud.get_code_source(source_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Source not found.")

    if mgr.get_lock(source_id).locked() or mgr.is_task_active(source_id):
        raise HTTPException(status_code=409, detail="Indexing already in progress.")
    # The live-run claim is the real guard: two requests arriving together
    # both pass the check above, and exactly one claim succeeds (review C5).
    # The status goes back to 'queued' only once the claim is held.
    try:
        await mgr.schedule_clone_and_index(source_id, requeue=True)
    except live_runs.RunAlreadyActiveError:
        raise HTTPException(status_code=409, detail="Indexing already in progress.")

    row = await crud.get_code_source(source_id)
    if row is None:
        raise HTTPException(
            status_code=500, detail="Source was updated but could not be read back."
        )
    return _source_response(row, status_code=202)


@router.delete("/{source_id}", status_code=204)
async def delete_source(
    source_id: str,
    _authz: None = Depends(require_role("owner", "source_id", "source")),
) -> None:
    """Delete a code source row and remove its clone directory.

    If the source is currently being cloned or indexed, the background task
    is signalled to stop and waited up to 5 s. If it does not stop in time,
    409 is returned — the client should retry shortly.
    """
    row = await crud.get_code_source(source_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Source not found.")

    in_progress = row.get("last_index_status") not in _TERMINAL_STATUSES | {None, "queued"}
    if in_progress or mgr.is_task_active(source_id):
        stopped = await mgr.cancel_and_wait(source_id, timeout=5.0)
        if not stopped:
            raise HTTPException(
                status_code=409,
                detail="Source is busy; retry in a few seconds.",
            )

    # Remove the clone directory and index DB (best-effort), off the event
    # loop: a large clone takes seconds to delete (review A3).
    clone_dir = clone_dir_for(source_id)
    if clone_dir.exists():
        await asyncio.to_thread(shutil.rmtree, clone_dir, True)
    idx_db = index_db_for(source_id)
    if idx_db.exists():
        await asyncio.to_thread(idx_db.unlink, True)

    await crud.delete_code_source(source_id)
    # Purge all per-source module state so create→delete cycles don't accumulate
    # unbounded dict entries.
    mgr.forget(source_id)


@router.get("/{source_id}/events")
async def stream_source_events(
    source_id: str,
    after: Annotated[int, Query(ge=0)] = 0,
    last_event_id: Annotated[int | None, Header(alias="Last-Event-ID", ge=0)] = None,
    _authz: None = Depends(require_role("viewer", "source_id", "source")),
) -> StreamingResponse:
    """SSE stream of clone/index progress events for a source.

    Follows the source's stored index run (backend/pipeline/live_runs.py):
    every event after ``after`` is replayed, then live ones until the run
    ends. A source that is ready or failed replays its latest run. With no run
    to follow (indexed before runs were stored, or pruned) a single status
    event is sent and the stream closes.
    """
    row = await crud.get_code_source(source_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Source not found.")

    status = row.get("last_index_status")
    run = await crud_live_runs.get_latest_run("code_source", source_id)
    # A busy source only follows a running index: a finished one belongs to an
    # earlier index and its "ready" would end the page's wait early.
    if run is not None and (run["status"] == "running" or status in _TERMINAL_STATUSES):
        chunks = live_runs.follow_run(run["id"], max(after, last_event_id or 0))
    else:
        chunks = _status_only(row)
    return StreamingResponse(
        _with_keepalive(chunks),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _status_only(row: dict) -> AsyncGenerator[str, None]:
    status = row.get("last_index_status")
    event = SourceEvent(
        source_id=row["id"],
        status=status,
        phase="terminal" if status in _TERMINAL_STATUSES else "status",
        message="",
        error=(row.get("last_index_error") or None) if status == "failed" else None,
    )
    yield f"data: {event.to_sse_data()}\n\n"


async def _with_keepalive(chunks: AsyncGenerator[str, None]) -> AsyncGenerator[bytes, None]:
    """Forward ``chunks``, sending a ping whenever none arrives for a while.

    A large clone emits nothing for minutes, and proxies close idle streams.
    The pending read is never cancelled by a ping, only when the client goes.
    """
    pending = asyncio.ensure_future(anext(chunks))
    try:
        while True:
            done, _ = await asyncio.wait({pending}, timeout=_KEEPALIVE_SECONDS)
            if not done:
                yield b"event: ping\ndata: {}\n\n"
                continue
            try:
                chunk = pending.result()
            except StopAsyncIteration:
                return
            yield chunk.encode()
            pending = asyncio.ensure_future(anext(chunks))
    finally:
        if not pending.done():
            pending.cancel()
            with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
                await pending
        await chunks.aclose()
