"""Database schema entry point: init_database_with_connection.

Schema changes: add a new file to backend/db/migrations/ (NNNN_description.py)
exposing  async def up(conn).  Do NOT add inline ALTER TABLE patches here.
The schema_migrations ledger table is the authoritative record of what ran.
"""

import logging

import aiosqlite


logger = logging.getLogger(__name__)


async def init_database_with_connection(conn: aiosqlite.Connection) -> None:
    """Initialize (or migrate) the database schema using an existing connection.

    Delegates entirely to the migration ledger runner.  To add a new schema
    change, drop a file in backend/db/migrations/ — do not add code here.

    Args:
        conn: Active aiosqlite connection (PRAGMA foreign_keys already ON).
    """
    from backend.db.migrations.runner import run_migrations

    logger.info("Initializing database schema via migration ledger")
    await run_migrations(conn)
    logger.info("Database schema initialized successfully")
