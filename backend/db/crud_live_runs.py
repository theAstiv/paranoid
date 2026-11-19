"""CRUD for live_runs / live_run_events — run state shared through the DB (KL-10, BB-72).

A run is claimed with an INSERT: the partial unique index on
(subject_type, subject_id) WHERE status = 'running' makes a second claim fail
atomically, so there is no read-then-write race.

Liveness is the heartbeat: a 'running' row whose owner hasn't updated it for
STALE_AFTER_SECONDS is presumed dead, whichever process owns it. Startup does
not assume a foreign row is dead — another server may share the database.
"""

import json
import logging
import os
import socket
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import aiosqlite

from backend.db.connection import db
from backend.db.crud import generate_id, now_iso


logger = logging.getLogger(__name__)

# Identifies this process in the row (diagnostics only; liveness is the heartbeat).
OWNER = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"

# Runs this process is driving (live_runs.py keeps it): never swept as stale,
# even if their heartbeat writes fail or the event loop stalls.
LOCAL_RUN_IDS: set[str] = set()

# Three missed 15 s heartbeats.
STALE_AFTER_SECONDS = 45.0
# Finished runs (and their stored events, which include the full threat list) are
# only for late followers; keep the latest per subject for this long.
FINISHED_RETENTION_DAYS = 7


# Recorded on a source whose indexing died with its server.
SOURCE_INTERRUPTED_MESSAGE = "Indexing interrupted: the server stopped before it finished."
_SOURCE_BUSY_STATUSES = ("queued", "cloning", "indexing")


def source_event_chunk(source_id: str, status: str, phase: str, message: str, **extra: Any) -> str:
    """An SSE chunk in the shape the source indexer emits (manager.SourceEvent)."""
    event = {
        "source_id": source_id,
        "status": status,
        "phase": phase,
        "message": message,
        "timestamp": datetime.now(UTC).isoformat(),
        **{k: v for k, v in extra.items() if v is not None},
    }
    return f"data: {json.dumps(event)}\n\n"


def _interrupted_event(kind: str, subject_id: str) -> str:
    if kind == "index":
        # The sources page reads status/message/error, not step.
        return source_event_chunk(
            subject_id,
            "failed",
            "interrupted",
            SOURCE_INTERRUPTED_MESSAGE,
            error=SOURCE_INTERRUPTED_MESSAGE,
        )
    what = "Extraction" if kind == "extract" else "Run"
    event = {
        "step": "complete",
        "status": "failed",
        "message": f"{what} interrupted: the server stopped before it finished.",
        "iteration": None,
        "data": None,
        "timestamp": datetime.now(UTC).timestamp(),
    }
    return f"data: {json.dumps(event)}\n\n"


async def _next_seq(conn: aiosqlite.Connection, run_id: str) -> int:
    async with conn.execute(
        "SELECT COALESCE(MAX(seq), 0) + 1 FROM live_run_events WHERE run_id = ?", (run_id,)
    ) as cursor:
        row = await cursor.fetchone()
    return int(row[0])


async def _insert_event(conn: aiosqlite.Connection, run_id: str, payload: str) -> int:
    seq = await _next_seq(conn, run_id)
    now = now_iso()
    await conn.execute(
        "INSERT INTO live_run_events (id, run_id, seq, payload, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (generate_id(), run_id, seq, payload, now, now),
    )
    return seq


async def _interrupt_stale(
    conn: aiosqlite.Connection, older_than_seconds: float, subject: tuple[str, str] | None = None
) -> int:
    """Inside a writer transaction: interrupt 'running' rows with a stale heartbeat.

    Runs this process is driving are skipped whatever their heartbeat says.
    Models of swept 'run' rows still 'in_progress', and sources of swept
    'index' rows still queued/cloning/indexing, become 'failed'; each swept
    row gets a final event giving the reason.
    """
    cutoff = (datetime.now(UTC) - timedelta(seconds=older_than_seconds)).isoformat()
    query = (
        "SELECT id, subject_type, subject_id, kind FROM live_runs "
        "WHERE status = 'running' AND heartbeat_at < ?"
    )
    params: tuple[str, ...] = (cutoff,)
    if subject is not None:
        query += " AND subject_type = ? AND subject_id = ?"
        params += subject
    async with conn.execute(query, params) as cursor:
        stale = [dict(r) for r in await cursor.fetchall() if r["id"] not in LOCAL_RUN_IDS]
    now = now_iso()
    for row in stale:
        await conn.execute(
            "UPDATE live_runs SET status = 'interrupted', finished_at = ?, updated_at = ? "
            "WHERE id = ?",
            (now, now, row["id"]),
        )
        await _insert_event(conn, row["id"], _interrupted_event(row["kind"], row["subject_id"]))
        if row["subject_type"] == "model" and row["kind"] == "run":
            await conn.execute(
                "UPDATE threat_models SET status = 'failed', updated_at = ? "
                "WHERE id = ? AND status = 'in_progress'",
                (now, row["subject_id"]),
            )
        elif row["subject_type"] == "code_source":
            await _fail_busy_sources(conn, now, "AND id = ?", (row["subject_id"],))
    return len(stale)


async def _fail_busy_sources(
    conn: aiosqlite.Connection, now: str, where: str, params: tuple[str, ...]
) -> int:
    cursor = await conn.execute(
        "UPDATE code_sources SET last_index_status = 'failed', last_index_error = ?, "
        "updated_at = ? WHERE last_index_status IN (?, ?, ?) " + where,
        (SOURCE_INTERRUPTED_MESSAGE, now, *_SOURCE_BUSY_STATUSES, *params),
    )
    return cursor.rowcount


async def fail_interrupted_sources() -> int:
    """Fail sources stuck queued/cloning/indexing with no running index row.

    Called once at startup, after the stale-run sweep. Before source indexing
    was recorded in live_runs nothing reset these, so a restart mid-clone left
    the source "Cloning…" forever (review A5). A source with a 'running' row is
    left alone: another server on this database may be indexing it.
    """
    async with db.writer() as conn:
        return await _fail_busy_sources(
            conn,
            now_iso(),
            "AND id NOT IN (SELECT subject_id FROM live_runs "
            "WHERE subject_type = 'code_source' AND status = 'running')",
            (),
        )


async def claim_run(subject_type: str, subject_id: str, kind: str) -> str | None:
    """Insert a 'running' row; return its id, or None if the subject already has one.

    A 'running' row with a dead heartbeat doesn't count: it is interrupted
    first, so a crashed run never blocks the subject until the next sweep.
    """
    run_id = generate_id()
    now = now_iso()
    async with db.writer() as conn:
        await _interrupt_stale(conn, STALE_AFTER_SECONDS, (subject_type, subject_id))
        try:
            await conn.execute(
                """
                INSERT INTO live_runs (id, subject_type, subject_id, kind, status, owner,
                                       started_at, heartbeat_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'running', ?, ?, ?, ?, ?)
                """,
                (run_id, subject_type, subject_id, kind, OWNER, now, now, now, now),
            )
        except sqlite3.IntegrityError as exc:
            # Only the one-running-per-subject index means "already running";
            # a CHECK or any other constraint is a bug and must surface.
            if "UNIQUE" in str(exc) and "live_runs" in str(exc):
                return None
            raise
        # Keep only the latest finished run per subject so events don't pile up.
        await conn.execute(
            """
            DELETE FROM live_runs
            WHERE subject_type = ? AND subject_id = ? AND status != 'running' AND id NOT IN (
                SELECT id FROM live_runs
                WHERE subject_type = ? AND subject_id = ? AND status != 'running'
                ORDER BY started_at DESC, rowid DESC LIMIT 1
            )
            """,
            (subject_type, subject_id, subject_type, subject_id),
        )
    return run_id


async def append_event(run_id: str, payload: str) -> int:
    """Append an event and return its sequence number (starting at 1)."""
    async with db.writer() as conn:
        return await _insert_event(conn, run_id, payload)


async def list_events(run_id: str, after_seq: int = 0) -> list[tuple[int, str]]:
    """Events with seq > after_seq, in order."""
    async with db.reader() as conn:
        async with conn.execute(
            "SELECT seq, payload FROM live_run_events WHERE run_id = ? AND seq > ? ORDER BY seq",
            (run_id, after_seq),
        ) as cursor:
            return [(r["seq"], r["payload"]) for r in await cursor.fetchall()]


async def finish_run(run_id: str, status: str) -> None:
    now = now_iso()
    conn = await db.get()
    await conn.execute(
        "UPDATE live_runs SET status = ?, finished_at = ?, updated_at = ? WHERE id = ?",
        (status, now, now, run_id),
    )
    await conn.commit()


async def fail_model_if_in_progress(model_id: str) -> None:
    """Last resort when a run dies without its generator marking the model failed."""
    conn = await db.get()
    await conn.execute(
        "UPDATE threat_models SET status = 'failed', updated_at = ? "
        "WHERE id = ? AND status = 'in_progress'",
        (now_iso(), model_id),
    )
    await conn.commit()


async def heartbeat(run_id: str) -> None:
    now = now_iso()
    conn = await db.get()
    await conn.execute(
        "UPDATE live_runs SET heartbeat_at = ?, updated_at = ? WHERE id = ? AND status = 'running'",
        (now, now, run_id),
    )
    await conn.commit()


async def get_run_row(run_id: str) -> dict[str, Any] | None:
    async with db.reader() as conn:
        async with conn.execute("SELECT * FROM live_runs WHERE id = ?", (run_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def get_active_run(subject_type: str, subject_id: str) -> dict[str, Any] | None:
    async with db.reader() as conn:
        async with conn.execute(
            "SELECT * FROM live_runs WHERE subject_type = ? AND subject_id = ? "
            "AND status = 'running'",
            (subject_type, subject_id),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def get_latest_run(subject_type: str, subject_id: str) -> dict[str, Any] | None:
    """The running row if there is one, else the most recent finished row."""
    async with db.reader() as conn:
        async with conn.execute(
            "SELECT * FROM live_runs WHERE subject_type = ? AND subject_id = ? "
            "ORDER BY (status = 'running') DESC, started_at DESC, rowid DESC LIMIT 1",
            (subject_type, subject_id),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def get_last_failure_message(run_id: str) -> str | None:
    """The message of the run's final 'complete' event when it reports a failure."""
    async with db.reader() as conn:
        async with conn.execute(
            "SELECT payload FROM live_run_events WHERE run_id = ? ORDER BY seq DESC LIMIT 1",
            (run_id,),
        ) as cursor:
            row = await cursor.fetchone()
    if row is None:
        return None
    try:
        event = json.loads(row["payload"].split("data: ", 1)[1])
    except (IndexError, ValueError):
        return None
    if event.get("step") == "complete" and event.get("status") == "failed":
        message = event.get("message")
        return message if isinstance(message, str) else None
    return None


async def sweep_stale_runs(older_than_seconds: float = STALE_AFTER_SECONDS) -> int:
    """Mark 'running' rows whose heartbeat is older than the limit 'interrupted'.

    Returns how many. Safe at startup and on a timer: a live run, in this
    process or another, keeps its heartbeat fresh and is left alone.
    """
    async with db.writer() as conn:
        return await _interrupt_stale(conn, older_than_seconds)


async def prune_finished_runs(older_than_days: int = FINISHED_RETENTION_DAYS) -> int:
    """Delete finished runs (and, by cascade, their events) older than the limit."""
    cutoff = (datetime.now(UTC) - timedelta(days=older_than_days)).isoformat()
    conn = await db.get()
    cursor = await conn.execute(
        "DELETE FROM live_runs WHERE status != 'running' AND finished_at < ?", (cutoff,)
    )
    await conn.commit()
    return cursor.rowcount
