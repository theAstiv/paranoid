"""SQLite connection manager for persistent connection pooling."""

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import aiosqlite


logger = logging.getLogger(__name__)

# Number of pre-warmed read-only connections in the pool.
# WAL mode lets all readers run concurrently against the single writer,
# so a pool of 4 covers the typical multi-user concurrency burst without
# opening per-request connections (which would re-pay the sqlite-vec
# extension load cost on every request).
_READER_POOL_SIZE = 4


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

    async def initialize(self, db_path: str) -> None:
        """Initialize the writer connection, enable WAL + FK, create schema, warm reader pool.

        Args:
            db_path: Path to SQLite database file.
        """
        if self._initialized:
            logger.warning("Connection already initialized")
            return

        logger.info(f"Initializing connection to {db_path}")
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
