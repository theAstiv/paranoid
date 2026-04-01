"""Tests for seed loader (backend/db/seed.py).

Tests load_seed_file with real JSON files and mock bulk_insert_seed_vectors
to avoid fastembed/sqlite-vec dependency.
"""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from backend.db.seed import (
    SEEDS_DIR,
    _count_expected_seeds,
    check_seeds_status,
    load_all_seeds,
    load_seed_file,
)


# ---------------------------------------------------------------------------
# load_seed_file — reads real JSON, no mocking needed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_seed_file_stride():
    """STRIDE seed file should load all patterns."""
    patterns = await load_seed_file(SEEDS_DIR / "stride_patterns.json")
    assert len(patterns) == 53
    # Spot-check structure
    assert "name" in patterns[0]
    assert "description" in patterns[0]
    assert "stride_category" in patterns[0]


@pytest.mark.asyncio
async def test_load_seed_file_maestro():
    """MAESTRO seed file should load all patterns."""
    patterns = await load_seed_file(SEEDS_DIR / "maestro_patterns.json")
    assert len(patterns) == 46
    assert "name" in patterns[0]
    assert "maestro_category" in patterns[0]


@pytest.mark.asyncio
async def test_load_seed_file_owasp():
    """OWASP LLM Top 10 seed file should load all patterns."""
    patterns = await load_seed_file(SEEDS_DIR / "owasp_llm_top10.json")
    assert len(patterns) == 10
    assert "name" in patterns[0]
    assert "description" in patterns[0]


@pytest.mark.asyncio
async def test_load_seed_file_missing():
    """Missing file should return empty list, not raise."""
    patterns = await load_seed_file(Path("/nonexistent/file.json"))
    assert patterns == []


def test_count_expected_seeds():
    """Expected count should match sum of all seed files."""
    assert _count_expected_seeds() == 109


# ---------------------------------------------------------------------------
# load_all_seeds — mock vector operations to avoid fastembed/sqlite-vec
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_all_seeds_first_run(test_db):
    """First run with empty DB should import all three seed types."""
    with patch(
        "backend.db.seed.bulk_insert_seed_vectors",
        new_callable=AsyncMock,
        return_value=0,
    ):
        results = await load_all_seeds(force=True)

    assert "stride" in results
    assert "maestro" in results
    assert "owasp" in results
    assert results["stride"] == 53
    assert results["maestro"] == 46
    assert results["owasp"] == 10
    assert results["total"] == 109


@pytest.mark.asyncio
async def test_load_all_seeds_skips_when_complete(test_db):
    """Should skip loading if seeds already present and count matches."""
    with (
        patch(
            "backend.db.seed.get_vector_stats",
            new_callable=AsyncMock,
            return_value={"seed": 109, "total": 109},
        ),
        patch(
            "backend.db.seed.import_stride_patterns",
            new_callable=AsyncMock,
        ) as mock_stride,
    ):
        results = await load_all_seeds()

    assert "skipped" in results
    assert results["skipped"] == 109
    mock_stride.assert_not_called()


@pytest.mark.asyncio
async def test_partial_load_triggers_cleanup(test_db):
    """Partial load (fewer vectors than expected) should cleanup and reload."""
    with (
        patch(
            "backend.db.seed.get_vector_stats",
            new_callable=AsyncMock,
            return_value={"seed": 50, "total": 50},
        ),
        patch(
            "backend.db.seed._cleanup_seed_data",
            new_callable=AsyncMock,
        ) as mock_cleanup,
        patch(
            "backend.db.seed.bulk_insert_seed_vectors",
            new_callable=AsyncMock,
            return_value=0,
        ),
    ):
        results = await load_all_seeds()

    mock_cleanup.assert_called_once_with()
    assert results["total"] == 109


@pytest.mark.asyncio
async def test_force_reload(test_db):
    """force=True should cleanup and reimport even if seeds are complete."""
    with (
        patch(
            "backend.db.seed._cleanup_seed_data",
            new_callable=AsyncMock,
        ) as mock_cleanup,
        patch(
            "backend.db.seed.bulk_insert_seed_vectors",
            new_callable=AsyncMock,
            return_value=0,
        ),
    ):
        results = await load_all_seeds(force=True)

    mock_cleanup.assert_called_once_with()
    assert results["total"] == 109


# ---------------------------------------------------------------------------
# check_seeds_status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_seeds_status_partial():
    """Partial seed load should report partial=True, loaded=False."""
    with patch(
        "backend.db.seed.get_vector_stats",
        new_callable=AsyncMock,
        return_value={"seed": 50, "total": 50},
    ):
        status = await check_seeds_status()

    assert status["partial"] is True
    assert status["loaded"] is False
    assert status["seed_count"] == 50
    assert status["expected_count"] == 109
    assert status["files_exist"]["stride"] is True
    assert status["files_exist"]["maestro"] is True
    assert status["files_exist"]["owasp"] is True


@pytest.mark.asyncio
async def test_check_seeds_status_complete():
    """Complete seed load should report loaded=True, partial=False."""
    with patch(
        "backend.db.seed.get_vector_stats",
        new_callable=AsyncMock,
        return_value={"seed": 109, "total": 109},
    ):
        status = await check_seeds_status()

    assert status["loaded"] is True
    assert status["partial"] is False
    assert status["seed_count"] == 109
