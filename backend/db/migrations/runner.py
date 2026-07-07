"""Migration ledger runner — applies pending migrations in filename order.

Adding a new migration:
  1. Create backend/db/migrations/NNNN_description.py
  2. Implement:  async def up(conn: aiosqlite.Connection) -> None
  3. Do NOT call BEGIN / COMMIT inside up() — the runner owns the transaction.
  4. On the next startup the migration is applied automatically.

Backfill rule: if the ledger table is empty and PRAGMA user_version >= 2, the
database pre-dates the ledger.  All migration files are recorded as applied
WITHOUT re-running them.
"""

import hashlib
import importlib
import logging
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite


logger = logging.getLogger(__name__)

_CREATE_LEDGER = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    name       TEXT PRIMARY KEY,
    checksum   TEXT NOT NULL,
    applied_at TEXT NOT NULL
)
"""


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _discover() -> list[Path]:
    """Return migration files in filename-sort order (0001_ first)."""
    return sorted(Path(__file__).parent.glob("[0-9][0-9][0-9][0-9]_*.py"))


async def run_migrations(conn: aiosqlite.Connection) -> None:
    """Create the ledger table, detect legacy DBs, and apply pending migrations.

    Each migration runs inside its own BEGIN IMMEDIATE transaction.  The ledger
    entry is written inside the same transaction, so a half-applied migration
    can never appear as recorded.

    Args:
        conn: Active aiosqlite writer connection (PRAGMA foreign_keys already ON).
    """
    await conn.execute(_CREATE_LEDGER)
    await conn.commit()

    async with conn.execute("SELECT name FROM schema_migrations") as cur:
        applied: set[str] = {row[0] for row in await cur.fetchall()}

    files = _discover()

    # Backfill path: ledger was just created on a DB that predates the ledger system.
    if not applied:
        async with conn.execute("PRAGMA user_version") as cur:
            row = await cur.fetchone()
        user_version = row[0] if row else 0

        if user_version >= 2:
            now = datetime.now(UTC).isoformat()
            for f in files:
                await conn.execute(
                    "INSERT OR IGNORE INTO schema_migrations (name, checksum, applied_at) "
                    "VALUES (?, ?, ?)",
                    (f.stem, _checksum(f), now),
                )
            await conn.commit()
            logger.info(
                "Legacy v%d DB: seeded migration ledger (%d entries)", user_version, len(files)
            )
            return

    # Normal path: run any pending migrations in order.
    for f in files:
        if f.stem in applied:
            continue

        module = importlib.import_module(f"backend.db.migrations.{f.stem}")
        checksum = _checksum(f)
        now = datetime.now(UTC).isoformat()

        await conn.execute("BEGIN IMMEDIATE")
        try:
            await module.up(conn)
            await conn.execute(
                "INSERT INTO schema_migrations (name, checksum, applied_at) VALUES (?, ?, ?)",
                (f.stem, checksum, now),
            )
            await conn.commit()
            logger.info("Applied migration: %s", f.stem)
        except Exception:
            await conn.rollback()
            logger.exception("Migration %s failed — rolled back", f.stem)
            raise
