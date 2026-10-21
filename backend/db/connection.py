"""SQLite connection manager for persistent connection pooling."""

import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite


logger = logging.getLogger(__name__)

# Number of pre-warmed read-only connections in the pool.
# WAL mode lets all readers run concurrently against the single writer,
# so a pool of 4 covers the typical multi-user concurrency burst without
# opening per-request connections (which would re-pay the sqlite-vec
# extension load cost on every request).
_READER_POOL_SIZE = 4


class DatabaseDirectoryError(RuntimeError):
    """The database's directory can't be created or written to."""


def _ensure_db_directory(db_path: str) -> None:
    """Create the database's parent directory and check it is writable.

    Nothing else creates it: a CLI run from a wheel in an empty directory has
    no ./data, and Docker creates a missing bind-mount source as root:root 755,
    which the app user (uid 1000) can't write to. SQLite would then fail with a
    bare "unable to open database file", so say what's wrong instead.
    """
    if db_path == ":memory:" or db_path.startswith("file:"):
        return
    directory = Path(db_path).resolve().parent
    uid = os.getuid() if hasattr(os, "getuid") else None
    who = f"uid {uid}" if uid is not None else "the current user"
    hint = (
        f"{directory} is not writable by {who}; on Docker run "
        f"`sudo chown 1000:1000 ./data` (see docs/getting-started.md), "
        f"or set DB_PATH to a writable location"
    )
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.error("Cannot create the database directory: %s (%s)", hint, exc)
        raise DatabaseDirectoryError(hint) from None
    if not os.access(directory, os.W_OK):
        logger.error("Cannot open the database: %s", hint)
        raise DatabaseDirectoryError(hint)


class ConnectionManager:
    """Manages a persistent SQLite writer connection and a pre-warmed reader pool.

    Usage — writer (mutations):
        conn = await db.get()
        await conn.execute("UPDATE threats SET status = ? WHERE id = ?", ...)
        await conn.commit()

    Usage — reader (SELECT only):
        async with db.reader() as conn:
            async with conn.execute("SELECT * FROM threats WHERE model_id = ?", ...) as cur:
                rows = await cur.fetchall()

    Usage — BEGIN IMMEDIATE (read-then-write sequences only):
        async with db.writer() as conn:
            row = await (await conn.execute("SELECT status FROM threats WHERE id = ?", ...)).fetchone()
            if row["status"] == "pending":
                await conn.execute("UPDATE threats SET status = 'approved' WHERE id = ?", ...)
    """

    def __init__(self) -> None:
        self._connection: aiosqlite.Connection | None = None
        self._db_path: str | None = None
        self._initialized: bool = False
        self._reader_pool: asyncio.Queue[aiosqlite.Connection] | None = None

    @property
    def is_initialized(self) -> bool:
        """Whether the writer connection is already up.

        Callers that only want to persist *if* the application has already
        set up a database (the FastAPI lifespan, a test's own fixture) check
        this instead of calling `get()`/`reader()`, which lazily opens a
        connection to `settings.db_path` as a side effect — harmless in the
        app, but not something an incidental caller (e.g. optional audit
        logging from the pipeline runner) should trigger on its own in a
        context — a bare unit test — that never intended to touch a database
        at all.
        """
        return self._initialized

    async def initialize(self, db_path: str) -> None:
        """Initialize the writer connection, enable WAL + FK, create schema, warm reader pool.

        Args:
            db_path: Path to SQLite database file.
        """
        if self._initialized:
            logger.warning("Connection already initialized")
            return

        logger.info(f"Initializing connection to {db_path}")
        _ensure_db_directory(db_path)
        self._db_path = db_path
        self._connection = await aiosqlite.connect(db_path)
        self._connection.row_factory = aiosqlite.Row

        try:
            import sqlite_vec

            await self._connection.enable_load_extension(True)
            try:
                await self._connection.load_extension(sqlite_vec.loadable_path())
                logger.info("Loaded sqlite-vec extension via sqlite_vec.loadable_path()")
            except Exception as e:
                logger.error(f"Could not load sqlite-vec extension: {e}")
                raise

            # WAL: concurrent readers while a writer is active.
            # busy_timeout: writers retry for 5 s on SQLITE_BUSY instead of failing.
            await self._connection.execute("PRAGMA journal_mode = WAL;")
            await self._connection.execute("PRAGMA busy_timeout = 5000;")
            # FK enforcement on the writer; each reader enables it separately.
            await self._connection.execute("PRAGMA foreign_keys = ON;")
            await self._connection.commit()

            # Create tables if needed
            from backend.db.schema import init_database_with_connection

            await init_database_with_connection(self._connection)

            # Pre-warm reader pool — open read-only URI connections so the
            # sqlite-vec extension is loaded once per connection, not per request.
            self._reader_pool = asyncio.Queue()
            for _ in range(_READER_POOL_SIZE):
                r = await aiosqlite.connect(f"file:{db_path}?mode=ro", uri=True)
                r.row_factory = aiosqlite.Row
                await r.execute("PRAGMA busy_timeout = 5000;")
                await r.enable_load_extension(True)
                await r.load_extension(sqlite_vec.loadable_path())
                self._reader_pool.put_nowait(r)
            logger.info(f"Pre-warmed {_READER_POOL_SIZE} read-only connections")

            self._initialized = True
            logger.info("Connection initialized successfully")

        except Exception:
            await self._connection.close()
            self._connection = None
            raise

    async def get(self) -> aiosqlite.Connection:
        """Get the persistent writer connection with lazy initialization.

        Returns:
            Active aiosqlite Connection (writer — shared singleton).

        Raises:
            RuntimeError: If connection fails to initialize.
        """
        if not self._initialized:
            from backend.config import settings

            await self.initialize(settings.db_path)

        if self._connection is None:
            msg = "Connection initialization failed"
            raise RuntimeError(msg)

        return self._connection

    @asynccontextmanager
    async def reader(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        """Checkout a read-only connection from the pool for SELECT queries.

        Blocks if all pool connections are in use (queue.get() awaits an
        available slot). The connection is returned to the pool in the
        finally block even if the caller raises.

        Yields:
            A read-only aiosqlite Connection with sqlite-vec loaded.
        """
        if not self._initialized:
            from backend.config import settings

            await self.initialize(settings.db_path)

        if self._reader_pool is None:
            msg = "Reader pool not initialized"
            raise RuntimeError(msg)

        conn = await self._reader_pool.get()
        try:
            yield conn
        finally:
            self._reader_pool.put_nowait(conn)

    @asynccontextmanager
    async def writer(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        """BEGIN IMMEDIATE transaction for read-then-write sequences.

        Use only when you need to read a value and conditionally write based
        on it (e.g. check member count before removing last owner). Single-
        statement UPDATEs are already atomic — don't use this wrapper for them.

        Commits on clean exit, rolls back on exception.

        Yields:
            The writer connection inside a BEGIN IMMEDIATE transaction.
        """
        conn = await self.get()
        await conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise

    async def close(self) -> None:
        """Close all connections (writer + reader pool)."""
        if self._reader_pool is not None:
            while not self._reader_pool.empty():
                try:
                    conn = self._reader_pool.get_nowait()
                    await conn.close()
                except asyncio.QueueEmpty:
                    break
            self._reader_pool = None
            logger.info("Closed reader pool")

        if self._connection is not None:
            logger.info("Closing writer connection")
            await self._connection.close()
            self._connection = None
            self._initialized = False
            self._db_path = None


# Global singleton instance
db = ConnectionManager()
