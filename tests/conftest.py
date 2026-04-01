"""Shared test fixtures for the paranoid test suite."""

import tempfile
from pathlib import Path

import aiosqlite
import pytest

from backend.db.connection import db
from backend.db.schema import init_database_with_connection
from backend.models.enums import Framework
from tests.fixtures.pipeline import make_stride_threats
from tests.mock_provider import MockProvider


@pytest.fixture
async def test_db():
    """Create a fresh temporary database per test via connection manager.

    Opens a real aiosqlite connection with foreign keys enabled and tables
    created, but skips sqlite-vec extension loading (not available in CI).
    Sets the singleton ConnectionManager state directly.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    # Reset manager state in case a previous test left it initialized
    if db._connection is not None:
        await db._connection.close()
    db._connection = None
    db._initialized = False
    db._db_path = None

    # Open real connection, skip extension loading
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys = ON;")
    await conn.commit()
    await init_database_with_connection(conn)

    # Set manager state manually
    db._connection = conn
    db._db_path = db_path
    db._initialized = True

    yield db_path

    # Cleanup
    if db._connection is not None:
        await db._connection.close()
    db._connection = None
    db._initialized = False
    db._db_path = None
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def mock_provider() -> MockProvider:
    """MockProvider configured for STRIDE framework."""
    return MockProvider(framework=Framework.STRIDE)


@pytest.fixture
def mock_provider_maestro() -> MockProvider:
    """MockProvider configured for MAESTRO framework."""
    return MockProvider(framework=Framework.MAESTRO)


@pytest.fixture
def stride_threats():
    """Pre-built STRIDE threats fixture."""
    return make_stride_threats()
