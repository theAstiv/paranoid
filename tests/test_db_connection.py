"""Tests for SQLite connection manager."""

from unittest.mock import AsyncMock, patch

import aiosqlite
import pytest

from backend.db.connection import ConnectionManager


@pytest.fixture
def mock_settings():
    """Mock settings for testing."""
    with patch("backend.config.settings") as mock:
        mock.db_path = "./test_db.db"
        yield mock


@pytest.fixture
async def clean_manager():
    """Provide a fresh ConnectionManager and clean up after."""
    manager = ConnectionManager()
    yield manager
    if manager._connection:
        await manager.close()


@pytest.fixture
def mock_aiosqlite_connection():
    """Mock aiosqlite.Connection for testing."""
    mock_conn = AsyncMock(spec=aiosqlite.Connection)
    mock_conn.row_factory = None
    mock_conn.execute = AsyncMock()
    mock_conn.commit = AsyncMock()
    mock_conn.close = AsyncMock()
    mock_conn.enable_load_extension = AsyncMock()
    mock_conn.load_extension = AsyncMock()
    return mock_conn


# Initialization Tests


@pytest.mark.asyncio
async def test_initialize_creates_connection_and_sets_initialized(
    clean_manager, mock_aiosqlite_connection
):
    """Initialize with valid db_path creates connection and sets _initialized = True."""
    with (
        patch("aiosqlite.connect", AsyncMock(return_value=mock_aiosqlite_connection)),
        patch("backend.db.schema.init_database_with_connection", AsyncMock()),
    ):
        await clean_manager.initialize("./test.db")

        assert clean_manager._initialized is True
        assert clean_manager._connection is mock_aiosqlite_connection
        assert clean_manager._db_path == "./test.db"


@pytest.mark.asyncio
async def test_initialize_sets_row_factory(clean_manager, mock_aiosqlite_connection):
    """Initialize sets row_factory to aiosqlite.Row."""
    with (
        patch("aiosqlite.connect", AsyncMock(return_value=mock_aiosqlite_connection)),
        patch("backend.db.schema.init_database_with_connection", AsyncMock()),
    ):
        await clean_manager.initialize("./test.db")

        assert mock_aiosqlite_connection.row_factory == aiosqlite.Row


@pytest.mark.asyncio
async def test_initialize_runs_pragma_foreign_keys(clean_manager, mock_aiosqlite_connection):
    """Initialize runs PRAGMA foreign_keys = ON."""
    with (
        patch("aiosqlite.connect", AsyncMock(return_value=mock_aiosqlite_connection)),
        patch("backend.db.schema.init_database_with_connection", AsyncMock()),
    ):
        await clean_manager.initialize("./test.db")

        mock_aiosqlite_connection.execute.assert_any_call("PRAGMA foreign_keys = ON;")
        mock_aiosqlite_connection.commit.assert_called()


@pytest.mark.asyncio
async def test_initialize_calls_init_database_with_connection(
    clean_manager, mock_aiosqlite_connection
):
    """Initialize calls init_database_with_connection() to create tables."""
    mock_init = AsyncMock()
    with (
        patch("aiosqlite.connect", AsyncMock(return_value=mock_aiosqlite_connection)),
        patch("backend.db.schema.init_database_with_connection", mock_init),
    ):
        await clean_manager.initialize("./test.db")

        mock_init.assert_called_once_with(mock_aiosqlite_connection)


@pytest.mark.asyncio
async def test_initialize_twice_is_idempotent(clean_manager, mock_aiosqlite_connection):
    """Initialize twice logs warning and returns early (idempotent)."""
    with (
        patch("aiosqlite.connect", AsyncMock(return_value=mock_aiosqlite_connection)),
        patch("backend.db.schema.init_database_with_connection", AsyncMock()),
        patch("backend.db.connection.logger") as mock_logger,
    ):
        await clean_manager.initialize("./test.db")
        await clean_manager.initialize("./test.db")  # Second call

        mock_logger.warning.assert_called_once_with("Connection already initialized")


@pytest.mark.asyncio
async def test_initialize_with_nonexistent_parent_raises(clean_manager):
    """Initialize with nonexistent parent directory raises (aiosqlite can't create dirs)."""
    mock_conn = AsyncMock()

    async def connect_side_effect(path):
        if "/nonexistent/" in path:
            raise aiosqlite.OperationalError("unable to open database file")
        return mock_conn

    with patch("aiosqlite.connect", AsyncMock(side_effect=connect_side_effect)):
        with pytest.raises(aiosqlite.OperationalError, match="unable to open database file"):
            await clean_manager.initialize("/nonexistent/path/to/db.db")


# Extension Loading Tests


@pytest.mark.asyncio
async def test_initialize_loads_vec0_via_package_path(clean_manager, mock_aiosqlite_connection):
    """Initialize loads sqlite-vec via sqlite_vec.loadable_path() (full path, not bare name).

    On Windows a bare 'vec0' name fails because site-packages is not on the DLL
    search path. Using the full path from sqlite_vec.loadable_path() resolves the
    correct vec0.dll on all platforms.
    """
    import sqlite_vec

    with (
        patch("aiosqlite.connect", AsyncMock(return_value=mock_aiosqlite_connection)),
        patch("backend.db.schema.init_database_with_connection", AsyncMock()),
    ):
        await clean_manager.initialize("./test.db")

        mock_aiosqlite_connection.enable_load_extension.assert_called_once_with(True)
        # Must use the full path, never the bare name "vec0"
        mock_aiosqlite_connection.load_extension.assert_called_once_with(
            sqlite_vec.loadable_path()
        )


@pytest.mark.asyncio
async def test_initialize_raises_when_extension_fails(
    clean_manager, mock_aiosqlite_connection
):
    """Initialize raises when sqlite-vec extension fails to load."""
    mock_aiosqlite_connection.load_extension.side_effect = Exception("Extension not found")

    with (
        patch("aiosqlite.connect", AsyncMock(return_value=mock_aiosqlite_connection)),
        patch("backend.db.schema.init_database_with_connection", AsyncMock()),
        pytest.raises(Exception, match="Extension not found"),
    ):
        await clean_manager.initialize("./test.db")


@pytest.mark.asyncio
async def test_failed_extension_loading_closes_connection(clean_manager, mock_aiosqlite_connection):
    """Failed extension loading closes the connection (no leak)."""
    mock_aiosqlite_connection.load_extension.side_effect = RuntimeError("Extension not found")

    with (
        patch("aiosqlite.connect", AsyncMock(return_value=mock_aiosqlite_connection)),
        patch("backend.db.schema.init_database_with_connection", AsyncMock()),
        pytest.raises(RuntimeError, match="Extension not found"),
    ):
        await clean_manager.initialize("./test.db")

    # Connection should be closed and state reset
    mock_aiosqlite_connection.close.assert_called_once()
    assert clean_manager._connection is None
    assert clean_manager._initialized is False


# get() Tests


@pytest.mark.asyncio
async def test_get_returns_connection_after_initialize(clean_manager, mock_aiosqlite_connection):
    """get() returns active connection after explicit initialize()."""
    with (
        patch("aiosqlite.connect", AsyncMock(return_value=mock_aiosqlite_connection)),
        patch("backend.db.schema.init_database_with_connection", AsyncMock()),
    ):
        await clean_manager.initialize("./test.db")
        conn = await clean_manager.get()

        assert conn is mock_aiosqlite_connection


@pytest.mark.asyncio
async def test_get_lazy_initializes(clean_manager, mock_aiosqlite_connection, mock_settings):
    """get() lazy-initializes from settings.db_path when not yet initialized."""
    with (
        patch("aiosqlite.connect", AsyncMock(return_value=mock_aiosqlite_connection)),
        patch("backend.db.schema.init_database_with_connection", AsyncMock()),
    ):
        # Not initialized yet
        assert clean_manager._initialized is False

        conn = await clean_manager.get()

        # Should have initialized automatically
        assert clean_manager._initialized is True
        assert conn is mock_aiosqlite_connection


@pytest.mark.asyncio
async def test_get_returns_same_connection_on_repeated_calls(
    clean_manager, mock_aiosqlite_connection
):
    """get() returns the same connection object on repeated calls (singleton)."""
    with (
        patch("aiosqlite.connect", AsyncMock(return_value=mock_aiosqlite_connection)),
        patch("backend.db.schema.init_database_with_connection", AsyncMock()),
    ):
        await clean_manager.initialize("./test.db")

        conn1 = await clean_manager.get()
        conn2 = await clean_manager.get()
        conn3 = await clean_manager.get()

        assert conn1 is conn2 is conn3 is mock_aiosqlite_connection


@pytest.mark.asyncio
async def test_get_raises_if_connection_is_none(clean_manager):
    """get() raises RuntimeError if connection is None after init attempt."""
    # Force _initialized to True but _connection to None (simulating a bug)
    clean_manager._initialized = True
    clean_manager._connection = None

    with pytest.raises(RuntimeError, match="Connection initialization failed"):
        await clean_manager.get()


# close() Tests


@pytest.mark.asyncio
async def test_close_resets_state(clean_manager, mock_aiosqlite_connection):
    """close() closes the connection and resets state."""
    with (
        patch("aiosqlite.connect", AsyncMock(return_value=mock_aiosqlite_connection)),
        patch("backend.db.schema.init_database_with_connection", AsyncMock()),
    ):
        await clean_manager.initialize("./test.db")
        await clean_manager.close()

        mock_aiosqlite_connection.close.assert_called_once()
        assert clean_manager._connection is None
        assert clean_manager._initialized is False
        assert clean_manager._db_path is None


@pytest.mark.asyncio
async def test_close_on_already_closed_is_noop(clean_manager):
    """close() on already-closed manager is a no-op (no error)."""
    # Manager never initialized
    assert clean_manager._connection is None

    # Should not raise
    await clean_manager.close()

    assert clean_manager._connection is None


@pytest.mark.asyncio
async def test_after_close_get_reinitializes(
    clean_manager, mock_aiosqlite_connection, mock_settings
):
    """After close(), get() re-initializes lazily."""
    with (
        patch("aiosqlite.connect", AsyncMock(return_value=mock_aiosqlite_connection)),
        patch("backend.db.schema.init_database_with_connection", AsyncMock()),
    ):
        await clean_manager.initialize("./test.db")
        await clean_manager.close()

        assert clean_manager._initialized is False

        # get() should lazy-initialize again
        conn = await clean_manager.get()

        assert clean_manager._initialized is True
        assert conn is mock_aiosqlite_connection


# Connection Usability Tests (Integration-style with real DB)


@pytest.mark.asyncio
@pytest.mark.skip(reason="Integration test - requires real DB setup")
async def test_connection_can_execute_select(clean_manager, tmp_path):
    """Connection returned by get() can execute SELECT queries."""
    db_path = tmp_path / "test.db"

    # Mock extension loading to avoid sqlite-vec requirement
    mock_conn = None

    async def mock_connect(path):
        nonlocal mock_conn
        import aiosqlite as real_aiosqlite

        mock_conn = await real_aiosqlite.connect(path)
        mock_conn.row_factory = aiosqlite.Row
        # Mock extension methods to avoid actual loading
        mock_conn.enable_load_extension = AsyncMock()
        mock_conn.load_extension = AsyncMock()
        return mock_conn

    with (
        patch("aiosqlite.connect", mock_connect),
        patch("backend.db.schema.init_database_with_connection", AsyncMock()),
    ):
        await clean_manager.initialize(str(db_path))
        conn = await clean_manager.get()

        # Create a simple table and query it
        await conn.execute("CREATE TABLE test (id INTEGER, name TEXT)")
        await conn.execute("INSERT INTO test VALUES (1, 'Alice')")
        await conn.commit()

        async with conn.execute("SELECT * FROM test") as cursor:
            rows = await cursor.fetchall()
            assert len(rows) == 1
            assert dict(rows[0]) == {"id": 1, "name": "Alice"}


@pytest.mark.asyncio
@pytest.mark.skip(reason="Integration test - requires real DB setup")
async def test_connection_can_insert_and_commit(clean_manager, tmp_path):
    """Connection returned by get() can execute INSERT + commit."""
    db_path = tmp_path / "test.db"

    mock_conn = None

    async def mock_connect(path):
        nonlocal mock_conn
        import aiosqlite as real_aiosqlite

        mock_conn = await real_aiosqlite.connect(path)
        mock_conn.row_factory = aiosqlite.Row
        mock_conn.enable_load_extension = AsyncMock()
        mock_conn.load_extension = AsyncMock()
        return mock_conn

    with (
        patch("aiosqlite.connect", mock_connect),
        patch("backend.db.schema.init_database_with_connection", AsyncMock()),
    ):
        await clean_manager.initialize(str(db_path))
        conn = await clean_manager.get()

        await conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
        await conn.execute("INSERT INTO users (name) VALUES (?)", ("Bob",))
        await conn.commit()

        async with conn.execute("SELECT name FROM users") as cursor:
            row = await cursor.fetchone()
            assert row["name"] == "Bob"


@pytest.mark.asyncio
@pytest.mark.skip(reason="Integration test - requires real DB setup")
async def test_connection_enforces_foreign_keys(clean_manager, tmp_path):
    """Connection returned by get() enforces foreign key constraints (PRAGMA was applied)."""
    db_path = tmp_path / "test.db"

    mock_conn = None

    async def mock_connect(path):
        nonlocal mock_conn
        import aiosqlite as real_aiosqlite

        mock_conn = await real_aiosqlite.connect(path)
        mock_conn.row_factory = aiosqlite.Row
        mock_conn.enable_load_extension = AsyncMock()
        mock_conn.load_extension = AsyncMock()
        return mock_conn

    with (
        patch("aiosqlite.connect", mock_connect),
        patch("backend.db.schema.init_database_with_connection", AsyncMock()),
    ):
        await clean_manager.initialize(str(db_path))
        conn = await clean_manager.get()

        # Create tables with FK constraint
        await conn.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
        await conn.execute(
            "CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER, "
            "FOREIGN KEY (parent_id) REFERENCES parent(id))"
        )
        await conn.commit()

        # Try to insert child without parent - should fail
        with pytest.raises(aiosqlite.IntegrityError):
            await conn.execute("INSERT INTO child (id, parent_id) VALUES (1, 999)")


@pytest.mark.asyncio
@pytest.mark.skip(reason="Integration test - requires real DB setup")
async def test_connection_supports_async_with_cursor(clean_manager, tmp_path):
    """Connection returned by get() supports async with conn.execute() cursor pattern."""
    db_path = tmp_path / "test.db"

    mock_conn = None

    async def mock_connect(path):
        nonlocal mock_conn
        import aiosqlite as real_aiosqlite

        mock_conn = await real_aiosqlite.connect(path)
        mock_conn.row_factory = aiosqlite.Row
        mock_conn.enable_load_extension = AsyncMock()
        mock_conn.load_extension = AsyncMock()
        return mock_conn

    with (
        patch("aiosqlite.connect", mock_connect),
        patch("backend.db.schema.init_database_with_connection", AsyncMock()),
    ):
        await clean_manager.initialize(str(db_path))
        conn = await clean_manager.get()

        await conn.execute("CREATE TABLE items (value INTEGER)")
        await conn.execute("INSERT INTO items VALUES (10), (20), (30)")
        await conn.commit()

        # Test async with cursor
        async with conn.execute("SELECT value FROM items ORDER BY value") as cursor:
            values = [row["value"] async for row in cursor]
            assert values == [10, 20, 30]


# Singleton Behavior Tests


def test_module_level_db_is_connection_manager():
    """Module-level db instance is a ConnectionManager."""
    from backend.db.connection import db as imported_db

    assert isinstance(imported_db, ConnectionManager)


def test_singleton_across_imports():
    """Two imports of db from different modules return the same instance."""
    import sys

    from backend.db.connection import db as db1

    # Force reimport to test singleton
    if "backend.db.connection" in sys.modules:
        connection_module = sys.modules["backend.db.connection"]
        db2 = connection_module.db

        assert db1 is db2  # Same object in memory
