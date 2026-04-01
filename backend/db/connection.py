"""SQLite connection manager for persistent connection pooling."""

import logging

import aiosqlite


logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages a persistent SQLite connection with proper initialization.

    Usage:
        from backend.db.connection import db

        # Initialize once at startup (or lazy on first use)
        await db.initialize(db_path)

        # Use in functions
        conn = await db.get()
        async with conn.execute("SELECT * FROM table") as cursor:
            rows = await cursor.fetchall()
        await conn.commit()

        # Cleanup at shutdown
        await db.close()
    """

    def __init__(self) -> None:
        self._connection: aiosqlite.Connection | None = None
        self._db_path: str | None = None
        self._initialized: bool = False

    async def initialize(self, db_path: str) -> None:
        """Initialize the connection manager with database setup.

        This method:
        1. Opens a persistent connection
        2. Loads sqlite-vec extension (vec0 → sqlite-vec fallback)
        3. Sets PRAGMA foreign_keys = ON
        4. Creates tables via schema.init_database_with_connection()

        Args:
            db_path: Path to SQLite database file
        """
        if self._initialized:
            logger.warning("Connection already initialized")
            return

        logger.info(f"Initializing connection to {db_path}")
        self._db_path = db_path
        self._connection = await aiosqlite.connect(db_path)
        self._connection.row_factory = aiosqlite.Row

        try:
            # Load sqlite-vec extension (cascading fallback: vec0 → sqlite-vec)
            await self._connection.enable_load_extension(True)
            try:
                await self._connection.load_extension("vec0")
                logger.info("Loaded sqlite-vec extension as 'vec0'")
            except Exception as e:
                logger.warning(f"Could not load vec0 extension: {e}")
                try:
                    await self._connection.load_extension("sqlite-vec")
                    logger.info("Loaded sqlite-vec extension as 'sqlite-vec'")
                except Exception as e2:
                    logger.error(f"Could not load sqlite-vec extension: {e2}")
                    raise

            # Enable foreign keys for all operations
            await self._connection.execute("PRAGMA foreign_keys = ON;")
            await self._connection.commit()

            # Create tables if needed
            from backend.db.schema import init_database_with_connection

            await init_database_with_connection(self._connection)

            self._initialized = True
            logger.info("Connection initialized successfully")

        except Exception:
            # Close connection on initialization failure to avoid leaks
            await self._connection.close()
            self._connection = None
            raise

    async def get(self) -> aiosqlite.Connection:
        """Get the persistent database connection with lazy initialization.

        Returns:
            Active aiosqlite Connection

        Raises:
            RuntimeError: If connection fails to initialize
        """
        if not self._initialized:
            # Lazy initialization for CLI usage
            from backend.config import settings

            await self.initialize(settings.db_path)

        if self._connection is None:
            msg = "Connection initialization failed"
            raise RuntimeError(msg)

        return self._connection

    async def close(self) -> None:
        """Close the database connection."""
        if self._connection is not None:
            logger.info("Closing database connection")
            await self._connection.close()
            self._connection = None
            self._initialized = False
            self._db_path = None


# Global singleton instance
db = ConnectionManager()
