"""Migration 0020: a database that already applied 0019 gets the new events shape."""

import importlib

import aiosqlite
import pytest


migration_0019 = importlib.import_module("backend.db.migrations.0019_live_runs")
migration_0020 = importlib.import_module("backend.db.migrations.0020_live_runs_events_shape")


@pytest.fixture
async def conn(tmp_path):
    connection = await aiosqlite.connect(tmp_path / "m.db")
    connection.row_factory = aiosqlite.Row
    await connection.execute("PRAGMA foreign_keys = ON")
    await connection.execute("CREATE TABLE threat_models (id TEXT PRIMARY KEY)")
    yield connection
    await connection.close()


async def _columns(conn: aiosqlite.Connection) -> set[str]:
    async with conn.execute("PRAGMA table_info(live_run_events)") as cursor:
        return {row[1] for row in await cursor.fetchall()}


@pytest.mark.asyncio
async def test_a_database_that_applied_the_old_0019_is_rebuilt_keeping_its_events(conn):
    await migration_0019.up(conn)
    assert "id" not in await _columns(conn)  # the shape 0019 shipped with
    await conn.execute(
        "INSERT INTO live_runs VALUES ('r1', 'model', 'm1', 'run', 'completed', 'o', "
        "'t', 't', 't', 't', 't')"
    )
    await conn.execute("INSERT INTO live_run_events VALUES ('r1', 1, 'data: a', 't')")
    await conn.execute("INSERT INTO live_run_events VALUES ('r1', 2, 'data: b', 't')")

    await migration_0020.up(conn)

    assert {"id", "updated_at"} <= await _columns(conn)
    async with conn.execute("SELECT seq, payload, id FROM live_run_events ORDER BY seq") as cur:
        rows = [tuple(r) for r in await cur.fetchall()]
    assert [(s, p) for s, p, _ in rows] == [(1, "data: a"), (2, "data: b")]
    assert len({i for _, _, i in rows}) == 2


@pytest.mark.asyncio
async def test_the_trigger_removes_a_deleted_models_runs_and_events(conn):
    await migration_0019.up(conn)
    await migration_0020.up(conn)
    await conn.execute("INSERT INTO threat_models VALUES ('m1')")
    await conn.execute(
        "INSERT INTO live_runs VALUES ('r1', 'model', 'm1', 'run', 'completed', 'o', "
        "'t', 't', 't', 't', 't')"
    )
    await conn.execute(
        "INSERT INTO live_run_events (id, run_id, seq, payload, created_at, updated_at) "
        "VALUES ('e1', 'r1', 1, 'data: a', 't', 't')"
    )

    await conn.execute("DELETE FROM threat_models WHERE id = 'm1'")

    async with conn.execute("SELECT COUNT(*) FROM live_runs") as cur:
        assert (await cur.fetchone())[0] == 0
    async with conn.execute("SELECT COUNT(*) FROM live_run_events") as cur:
        assert (await cur.fetchone())[0] == 0


@pytest.mark.asyncio
async def test_running_it_twice_changes_nothing(conn):
    await migration_0019.up(conn)
    await migration_0020.up(conn)
    await conn.execute(
        "INSERT INTO live_runs VALUES ('r1', 'model', 'm1', 'run', 'completed', 'o', "
        "'t', 't', 't', 't', 't')"
    )
    await conn.execute(
        "INSERT INTO live_run_events (id, run_id, seq, payload, created_at, updated_at) "
        "VALUES ('e1', 'r1', 1, 'data: a', 't', 't')"
    )

    await migration_0020.up(conn)

    async with conn.execute("SELECT id FROM live_run_events") as cur:
        assert [r[0] for r in await cur.fetchall()] == ["e1"]
