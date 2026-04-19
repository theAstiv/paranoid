"""Code source CRUD and SSE progress routes.

Mounted at /api/sources from backend.main.
"""

import asyncio
import logging
import shutil
from collections.abc import AsyncGenerator

import aiosqlite
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from backend.db import crud
from backend.models.extended import CodeSource, CreateCodeSourceRequest
from backend.security.source_key import (
    KeySourceChangedError,
    SourceKeyUnavailableError,
)
from backend.sources import manager as mgr
from backend.sources.manager import SourceEvent
from backend.sources.paths import clone_dir_for


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sources", tags=["sources"])

_TERMINAL_STATUSES = frozenset({"ready", "failed"})


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
async def list_sources() -> JSONResponse:
    """List all code sources."""
    rows = await crud.list_code_sources()
    items = [CodeSource(**r).model_dump() for r in rows]
    return JSONResponse(content=items)


@router.post("", status_code=202)
async def create_source(body: CreateCodeSourceRequest) -> JSONResponse:
    """Create a code source row and kick off a background clone + index."""
    # Validate URL before touching the DB — cheap fail-fast.
    try:
        mgr.validate_git_url(body.git_url)
    except mgr.HostNotAllowedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    pat = body.pat.get_secret_value() if body.pat else None

    try:
        source_id = await crud.create_code_source(
            name=body.name,
            git_url=body.git_url,
            ref=body.ref,
            pat=pat,
        )
    except aiosqlite.IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="A code source with this URL and ref already exists.",
        ) from exc
    except (SourceKeyUnavailableError, KeySourceChangedError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    mgr.schedule_clone_and_index(source_id)

    row = await crud.get_code_source(source_id)
    if row is None:
        raise HTTPException(
            status_code=500, detail="Source was created but could not be read back."
        )
    return _source_response(row, status_code=202)


@router.get("/{source_id}")
async def get_source(source_id: str) -> JSONResponse:
    """Get a single code source by ID."""
    row = await crud.get_code_source(source_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Source not found.")
    return _source_response(row)


@router.post("/{source_id}/reindex", status_code=202)
async def reindex_source(source_id: str) -> JSONResponse:
    """Trigger a manual re-clone + re-index for an existing source."""
    row = await crud.get_code_source(source_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Source not found.")

    lock = mgr.get_lock(source_id)
    if lock.locked():
        raise HTTPException(status_code=409, detail="Indexing already in progress.")

    # Reset to queued before scheduling so polling clients see the transition.
    await crud.update_code_source_status(source_id, status="queued")
    mgr.schedule_clone_and_index(source_id)

    row = await crud.get_code_source(source_id)
    if row is None:
        raise HTTPException(
            status_code=500, detail="Source was updated but could not be read back."
        )
    return _source_response(row, status_code=202)


@router.delete("/{source_id}", status_code=204)
async def delete_source(source_id: str) -> None:
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

    # Remove the clone directory (best-effort).
    clone_dir = clone_dir_for(source_id)
    if clone_dir.exists():
        shutil.rmtree(clone_dir, ignore_errors=True)

    await crud.delete_code_source(source_id)
    # Purge all per-source module state so create→delete cycles don't accumulate
    # unbounded dict entries.
    mgr.forget(source_id)


@router.get("/{source_id}/events")
async def stream_source_events(source_id: str, request: Request) -> StreamingResponse:
    """SSE stream of clone/index progress events for a source.

    On connect the last ~20 events are replayed from the ring buffer, then
    live events are streamed. If the source is already in a terminal state
    (ready/failed) and the ring buffer has expired (>60 s since completion),
    a single status event is emitted and the stream closes.
    """
    row = await crud.get_code_source(source_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Source not found.")

    already_terminal = row.get("last_index_status") in _TERMINAL_STATUSES

    # Snapshot ring buffer for the terminal path only (no live events possible).
    # For non-terminal, the snapshot happens inside the generator after
    # subscribing to eliminate the replay↔subscribe gap.
    ring = mgr.get_ring_buffer(source_id) if already_terminal else []

    # Fast-path subscriber cap check. The context manager inside event_stream
    # is the authoritative cap guard; this early check returns a clean 503
    # before opening the SSE response.
    if not already_terminal and mgr.subscriber_count(source_id) >= mgr.MAX_SUBSCRIBERS:
        raise HTTPException(
            status_code=503,
            detail=f"Max {mgr.MAX_SUBSCRIBERS} simultaneous SSE subscribers reached.",
        )

    async def event_stream() -> AsyncGenerator[bytes, None]:
        if already_terminal:
            # Replay buffered events; emit a synthetic one if the buffer expired.
            for event in ring:
                if await request.is_disconnected():
                    return
                yield f"data: {event.to_sse_data()}\n\n".encode()
            if not ring:
                is_failed = row["last_index_status"] == "failed"
                synthetic = SourceEvent(
                    source_id=source_id,
                    status=row["last_index_status"],
                    phase="terminal",
                    message="",
                    error=(row.get("last_index_error") or None) if is_failed else None,
                )
                yield f"data: {synthetic.to_sse_data()}\n\n".encode()
            return

        # Subscribe BEFORE snapshotting the ring buffer so no events published
        # between snapshot and subscribe are silently dropped.
        try:
            async with mgr.subscribe_to_source(source_id) as q:
                live_ring = mgr.get_ring_buffer(source_id)
                max_seq = live_ring[-1].seq if live_ring else 0

                for event in live_ring:
                    if await request.is_disconnected():
                        return
                    yield f"data: {event.to_sse_data()}\n\n".encode()

                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        event = await asyncio.wait_for(q.get(), timeout=30.0)
                    except TimeoutError:
                        # Keepalive ping.
                        yield b"event: ping\ndata: {}\n\n"
                        continue
                    if event is None:
                        break  # done sentinel
                    if event.seq <= max_seq:
                        continue  # already sent via ring replay
                    yield f"data: {event.to_sse_data()}\n\n".encode()
        except mgr.TooManySubscribersError as exc:
            logger.warning("SSE subscriber cap hit for %s: %s", source_id, exc)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
