"""Tests for the schema migration ledger (backend/db/migrations/).

Three DB-state fixtures:
  (a) fresh DB    — all migrations run once, ledger populated
  (b) v1 DB       — simulated pre-v2 DB; both migrations run, ledger populated
  (c) current v2  — backfill marks every migration applied, nothing re-runs

Plus idempotency: run_migrations() twice on the same connection is a no-op.
"""

from unittest.mock import patch

import aiosqlite
import pytest

from backend.db.migrations.runner import _discover, run_migrations


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_conn(tmp_path, name="test.db") -> aiosqlite.Connection:
    """Open a real aiosqlite connection without sqlite-vec (not needed here)."""
    conn = await aiosqlite.connect(str(tmp_path / name))
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys = ON")
    await conn.commit()
    return conn


async def _ledger_names(conn: aiosqlite.Connection) -> set[str]:
    async with conn.execute("SELECT name FROM schema_migrations") as cur:
        return {row[0] for row in await cur.fetchall()}


async def _table_exists(conn: aiosqlite.Connection, table: str) -> bool:
    async with conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ) as cur:
        return await cur.fetchone() is not None


# ---------------------------------------------------------------------------
# (a) Fresh DB — all migrations run once
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fresh_db_runs_all_migrations(tmp_path):
    """A brand-new empty DB runs every migration file exactly once."""
    conn = await _make_conn(tmp_path)
    try:
        await run_migrations(conn)

        names = await _ledger_names(conn)
        expected = {f.stem for f in _discover()}
        assert expected == names, f"Expected {expected}, got {names}"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_fresh_db_creates_core_tables(tmp_path):
    """After migrations on a fresh DB, all core tables exist."""
    conn = await _make_conn(tmp_path)
    try:
        await run_migrations(conn)

        for table in (
            "threat_models",
            "threats",
            "projects",
            "users",
            "sessions",
            "schema_migrations",
        ):
            assert await _table_exists(conn, table), f"Table {table!r} not created"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_fresh_db_default_project_created(tmp_path):
    """0002_projects creates the Default Project row on a fresh DB."""
    conn = await _make_conn(tmp_path)
    try:
        await run_migrations(conn)

        async with conn.execute(
            "SELECT id FROM projects WHERE id = '00000000-0000-0000-0000-000000000000'"
        ) as cur:
            row = await cur.fetchone()
        assert row is not None, "Default Project should exist on a fresh DB"
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# (b) Simulated v1 DB — v2 migration runs, ledger recorded
# ---------------------------------------------------------------------------


async def _make_v1_db(tmp_path) -> aiosqlite.Connection:
    """Build a v1-era DB (tables present, no project_id cols added yet, user_version=1).

    Reflects the actual v1 schema: all original columns are present; the columns
    added by ADD COLUMN patches (code_source_id, created_by, gap_summaries,
    code_summary, assumptions, project_id, user_edited, vector_rowid) are absent.
    No auth or project tables.
    """
    conn = await _make_conn(tmp_path, "v1.db")
    # v1 threat_models: no code_source_id / created_by / gap_summaries / code_summary
    # / assumptions / project_id
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS threat_models (
            id              TEXT PRIMARY KEY,
            title           TEXT NOT NULL,
            description     TEXT,
            framework       TEXT DEFAULT 'STRIDE',
            provider        TEXT NOT NULL,
            model           TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'pending',
            iteration_count INTEGER DEFAULT 1,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        )
    """)
    # v1 threats: all standard columns present (stride_category etc. were always there)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS threats (
            id                      TEXT PRIMARY KEY,
            model_id                TEXT NOT NULL,
            stride_category         TEXT,
            maestro_category        TEXT,
            name                    TEXT NOT NULL,
            description             TEXT NOT NULL,
            target                  TEXT NOT NULL,
            impact                  TEXT NOT NULL,
            likelihood              TEXT NOT NULL,
            dread_damage            INTEGER,
            dread_reproducibility   INTEGER,
            dread_exploitability    INTEGER,
            dread_affected_users    INTEGER,
            dread_discoverability   INTEGER,
            dread_score             REAL,
            mitigations             TEXT NOT NULL,
            status                  TEXT NOT NULL DEFAULT 'pending',
            iteration_number        INTEGER DEFAULT 1,
            created_at              TEXT NOT NULL,
            updated_at              TEXT NOT NULL,
            FOREIGN KEY (model_id) REFERENCES threat_models(id) ON DELETE CASCADE
        )
    """)
    # v1 assets: no user_edited column
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS assets (
            id TEXT PRIMARY KEY, model_id TEXT NOT NULL, type TEXT NOT NULL,
            name TEXT NOT NULL, description TEXT NOT NULL, created_at TEXT NOT NULL,
            FOREIGN KEY (model_id) REFERENCES threat_models(id) ON DELETE CASCADE
        )
    """)
    # v1 threat_metadata: no vector_rowid / project_id
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS threat_metadata (
            id TEXT PRIMARY KEY, threat_id TEXT,
            source TEXT NOT NULL, embedding_model TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (threat_id) REFERENCES threats(id) ON DELETE CASCADE
        )
    """)
    # v1 code_sources: no project_id
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS code_sources (
            id TEXT PRIMARY KEY, name TEXT NOT NULL,
            git_url TEXT NOT NULL, ref TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE (git_url, ref)
        )
    """)
    await conn.execute("PRAGMA user_version = 1")
    await conn.commit()
    return conn


@pytest.mark.asyncio
async def test_v1_db_all_migrations_applied(tmp_path):
    """A v1 DB (user_version=1, empty ledger) runs all migrations."""
    conn = await _make_v1_db(tmp_path)
    try:
        await run_migrations(conn)

        names = await _ledger_names(conn)
        expected = {f.stem for f in _discover()}
        assert expected == names
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_v1_db_adds_missing_tables(tmp_path):
    """After running migrations on a v1 DB, new tables (projects, users) exist."""
    conn = await _make_v1_db(tmp_path)
    try:
        await run_migrations(conn)

        for table in ("projects", "users", "sessions", "project_members"):
            assert await _table_exists(conn, table), f"Table {table!r} not added by migration"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_v1_db_threat_models_backfilled(tmp_path):
    """Existing threat_models on a v1 DB get project_id backfilled by 0002."""
    conn = await _make_v1_db(tmp_path)
    try:
        # Insert a bare threat_model (no project_id column yet — migration adds it)
        await conn.execute(
            "INSERT INTO threat_models (id, title, provider, model, status, created_at, updated_at) "
            "VALUES ('tm-1', 'Test', 'anthropic', 'claude', 'pending', '2024-01-01', '2024-01-01')"
        )
        await conn.commit()

        await run_migrations(conn)

        async with conn.execute("SELECT project_id FROM threat_models WHERE id = 'tm-1'") as cur:
            row = await cur.fetchone()
        assert row is not None
        assert row[0] == "00000000-0000-0000-0000-000000000000"
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# (c) Current v2 DB — backfill marks applied, nothing re-runs
# ---------------------------------------------------------------------------


async def _make_v2_db(tmp_path) -> aiosqlite.Connection:
    """Build a DB that already has the full v2 schema (user_version=2)."""
    conn = await _make_conn(tmp_path, "v2.db")
    # Run migrations once to establish the full schema
    await run_migrations(conn)
    # Clear the ledger to simulate a DB that predates the ledger system
    await conn.execute("DELETE FROM schema_migrations")
    await conn.execute("PRAGMA user_version = 2")
    await conn.commit()
    return conn


@pytest.mark.asyncio
async def test_v2_db_backfill_marks_all_applied(tmp_path):
    """A v2 DB (user_version=2, empty ledger) is backfilled without re-running."""
    conn = await _make_v2_db(tmp_path)
    try:
        await run_migrations(conn)

        names = await _ledger_names(conn)
        expected = {f.stem for f in _discover()}
        assert expected == names
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_v2_db_backfill_does_not_duplicate_default_project(tmp_path):
    """Running migrations on a v2 DB does not create a second Default Project row."""
    conn = await _make_v2_db(tmp_path)
    try:
        await run_migrations(conn)

        async with conn.execute(
            "SELECT COUNT(*) FROM projects WHERE id = '00000000-0000-0000-0000-000000000000'"
        ) as cur:
            row = await cur.fetchone()
        assert row[0] == 1
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Idempotency — calling run_migrations() twice is a no-op the second time
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_migrations_idempotent_fresh_db(tmp_path):
    """Calling run_migrations() twice on a fresh DB is a no-op the second time."""
    conn = await _make_conn(tmp_path)
    try:
        await run_migrations(conn)
        names_after_first = await _ledger_names(conn)

        # Second call should not raise and should not change anything
        await run_migrations(conn)
        names_after_second = await _ledger_names(conn)

        assert names_after_first == names_after_second
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_run_migrations_idempotent_v2_db(tmp_path):
    """Calling run_migrations() twice on a v2 DB backfills once, then no-ops."""
    conn = await _make_v2_db(tmp_path)
    try:
        await run_migrations(conn)
        names_first = await _ledger_names(conn)

        await run_migrations(conn)
        names_second = await _ledger_names(conn)

        assert names_first == names_second
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Ledger integrity — checksum and applied_at are recorded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ledger_entries_have_checksum_and_timestamp(tmp_path):
    """Each ledger row has a non-empty checksum and ISO-8601 applied_at."""
    conn = await _make_conn(tmp_path)
    try:
        await run_migrations(conn)

        async with conn.execute("SELECT name, checksum, applied_at FROM schema_migrations") as cur:
            rows = await cur.fetchall()

        assert rows, "Ledger should have at least one entry"
        for row in rows:
            assert row["checksum"], f"Migration {row['name']} has empty checksum"
            assert row["applied_at"], f"Migration {row['name']} has empty applied_at"
            # Basic ISO-8601 format check
            assert "T" in row["applied_at"], (
                f"applied_at does not look like ISO-8601: {row['applied_at']}"
            )
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Failed migration rolls back — ledger not updated on error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failed_migration_not_recorded_in_ledger(tmp_path):
    """A migration that raises an exception is rolled back and not added to the ledger."""
    conn = await _make_conn(tmp_path)
    try:
        # Patch 0001_initial to raise so the first migration fails
        with patch(
            "backend.db.migrations.runner.importlib.import_module",
            side_effect=RuntimeError("intentional failure"),
        ):
            with pytest.raises(RuntimeError, match="intentional failure"):
                await run_migrations(conn)

        # Ledger table exists but has no entries (failed migration not recorded)
        names = await _ledger_names(conn)
        assert not names, f"Ledger should be empty after failed migration, got {names}"
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# _discover() returns files in sorted order
# ---------------------------------------------------------------------------


def test_discover_returns_sorted_files():
    """_discover() returns migration files in ascending filename order."""
    files = _discover()
    assert files == sorted(files), "Migration files must be in ascending order"
    assert len(files) >= 2, "At least 0001 and 0002 should exist"
    assert files[0].name.startswith("0001_")
    assert files[1].name.startswith("0002_")
