"""Shared test fixtures for the paranoid test suite."""

import tempfile
from pathlib import Path

import pytest

from backend.db import schema
from backend.models.enums import Framework
from tests.fixtures.pipeline import make_stride_threats
from tests.mock_provider import MockProvider


@pytest.fixture
async def test_db():
    """Create a fresh temporary database per test (function scope)."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    await schema.init_database(db_path)
    yield db_path

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
