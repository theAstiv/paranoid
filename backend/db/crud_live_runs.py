"""CRUD for live_runs / live_run_events — run state shared through the DB (KL-10, BB-72).

A run is claimed with an INSERT: the partial unique index on
(subject_type, subject_id) WHERE status = 'running' makes a second claim fail
atomically, so there is no read-then-write race.
"""

import logging
import os
import socket
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from backend.db.connection import db
from backend.db.crud import generate_id, now_iso


logger = logging.getLogger(__name__)

# Identifies this process: rows from another owner at startup are leftovers.
OWNER = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


async def claim_run(subject_type: str, subject_id: str, kind: str) -> str | None:
    """Insert a 'running' row; return its id, or None if the subject already has one."""
    run_id = generate_id()
    now = now_iso()
    async with db.writer() as conn:
        try:
            await conn.execute(
                """
                INSERT INTO live_runs (id, subject_type, subject_id, kind, status, owner,
                                       started_at, heartbeat_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'running', ?, ?, ?, ?, ?)
                """,
                (run_id, subject_type, subject_id, kind, OWNER, now, now, now, now),
            )
        except sqlite3.IntegrityError:
            return None
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
        async with conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM live_run_events WHERE run_id = ?", (run_id,)
        ) as cursor:
            row = await cursor.fetchone()
        seq = int(row[0])
        await conn.execute(
            "INSERT INTO live_run_events (run_id, seq, payload, created_at) VALUES (?, ?, ?, ?)",
            (run_id, seq, payload, now_iso()),
        )
    return seq


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


async def sweep_stale_runs(older_than_seconds: float, *, foreign_only: bool = False) -> int:
    """Mark stale 'running' rows 'interrupted'; return how many.

    A row is stale when its heartbeat is older than ``older_than_seconds``.
    ``foreign_only`` (startup) instead sweeps every row owned by another
    process regardless of age. This process's own rows are never touched.
    Models of swept 'run' rows still 'in_progress' become 'failed'.
    """
    cutoff = (datetime.now(UTC) - timedelta(seconds=older_than_seconds)).isoformat()
    now = now_iso()
    async with db.writer() as conn:
        if foreign_only:
            query = (
                "SELECT id, subject_type, subject_id, kind FROM live_runs "
                "WHERE status = 'running' AND owner != ?"
            )
            params: tuple[str, ...] = (OWNER,)
        else:
            query = (
                "SELECT id, subject_type, subject_id, kind FROM live_runs "
                "WHERE status = 'running' AND heartbeat_at < ? AND owner != ?"
            )
            params = (cutoff, OWNER)
        async with conn.execute(query, params) as cursor:
            stale = [dict(r) for r in await cursor.fetchall()]
        for row in stale:
            await conn.execute(
                "UPDATE live_runs SET status = 'interrupted', finished_at = ?, updated_at = ? "
                "WHERE id = ?",
                (now, now, row["id"]),
            )
            if row["subject_type"] == "model" and row["kind"] == "run":
                await conn.execute(
                    "UPDATE threat_models SET status = 'failed', updated_at = ? "
                    "WHERE id = ? AND status = 'in_progress'",
                    (now, row["subject_id"]),
                )
    return len(stale)
