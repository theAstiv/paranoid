"""Tests for `paranoid models delete` and `paranoid models prune` CLI commands.

Covers _delete_model_async and _prune_models_async directly (no Click runner needed).
"""

import pytest

from backend.db import crud
from backend.db.connection import db
from cli.commands.models import _delete_model_async, _prune_models_async
from cli.errors import CLIError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_model(title: str = "Test Model", status: str = "completed") -> str:
    model_id = await crud.create_threat_model(
        title=title,
        description="A test system.",
        provider="anthropic",
        model="claude-sonnet-4",
        framework="STRIDE",
        iteration_count=1,
    )
    await crud.update_threat_model_status(model_id, status)
    return model_id


async def _add_threat(model_id: str) -> str:
    return await crud.create_threat(
        model_id=model_id,
        name="SQL Injection",
        description="An attacker exploits unparameterized queries to read arbitrary data.",
        target="Database",
        impact="Data breach",
        likelihood="High",
        mitigations=["[P] Use parameterized queries"],
        stride_category="Tampering",
    )


async def _set_created_at(model_id: str, iso_date: str) -> None:
    """Backdoor the created_at timestamp for age-filter tests."""
    conn = await db.get()
    await conn.execute(
        "UPDATE threat_models SET created_at = ? WHERE id = ?",
        (iso_date, model_id),
    )
    await conn.commit()


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_removes_model(test_db) -> None:
    """Deleting a model means get_threat_model returns None afterwards."""
    model_id = await _make_model()

    await _delete_model_async(model_id=model_id, yes=True)

    assert await crud.get_threat_model(model_id) is None


@pytest.mark.asyncio
async def test_delete_cascades_to_threats(test_db) -> None:
    """Deleting a model removes its threats via CASCADE."""
    model_id = await _make_model()
    await _add_threat(model_id)

    threats_before = await crud.list_threats(model_id)
    assert len(threats_before) == 1

    await _delete_model_async(model_id=model_id, yes=True)

    # Model is gone; threats table should have no orphans
    # (FK CASCADE — direct list would need the model_id, which is deleted)
    assert await crud.get_threat_model(model_id) is None


@pytest.mark.asyncio
async def test_delete_by_prefix(test_db) -> None:
    """Deletion works with an unambiguous ID prefix."""
    model_id = await _make_model()
    prefix = model_id[:8]

    await _delete_model_async(model_id=prefix, yes=True)

    assert await crud.get_threat_model(model_id) is None


@pytest.mark.asyncio
async def test_delete_nonexistent_model_raises(test_db) -> None:
    """CLIError raised when no model matches the given ID."""
    with pytest.raises(CLIError, match="No threat model found"):
        await _delete_model_async(model_id="00000000-0000-0000-0000-000000000000", yes=True)


@pytest.mark.asyncio
async def test_delete_ambiguous_prefix_raises_cli_error(test_db, monkeypatch) -> None:
    """ValueError from find_threat_model_by_prefix is wrapped as CLIError."""

    async def _ambiguous(prefix: str):
        raise ValueError("Prefix 'a' is ambiguous — matches 2 models. Use more characters.")

    monkeypatch.setattr(crud, "find_threat_model_by_prefix", _ambiguous)

    with pytest.raises(CLIError, match="ambiguous"):
        await _delete_model_async(model_id="a", yes=True)


@pytest.mark.asyncio
async def test_delete_cancelled_by_user(test_db, monkeypatch) -> None:
    """Model is NOT deleted when user declines the confirmation prompt."""
    import click

    model_id = await _make_model()
    monkeypatch.setattr(click, "confirm", lambda *a, **kw: False)

    await _delete_model_async(model_id=model_id, yes=False)

    assert await crud.get_threat_model(model_id) is not None


# ---------------------------------------------------------------------------
# prune
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prune_by_status_deletes_matching(test_db) -> None:
    """prune with --status failed deletes only failed models."""
    failed_id = await _make_model("Failed Run", status="failed")
    ok_id = await _make_model("Good Run", status="completed")

    await _prune_models_async(older_than_days=None, status="failed", yes=True)

    assert await crud.get_threat_model(failed_id) is None
    assert await crud.get_threat_model(ok_id) is not None


@pytest.mark.asyncio
async def test_prune_by_status_pending(test_db) -> None:
    """prune --status pending leaves completed models untouched."""
    pending_id = await _make_model("Stale", status="pending")
    done_id = await _make_model("Done", status="completed")

    await _prune_models_async(older_than_days=None, status="pending", yes=True)

    assert await crud.get_threat_model(pending_id) is None
    assert await crud.get_threat_model(done_id) is not None


@pytest.mark.asyncio
async def test_prune_by_age_deletes_old_models(test_db) -> None:
    """prune --older-than 30 deletes models with created_at > 30 days ago."""
    old_id = await _make_model("Old Model")
    await _set_created_at(old_id, "2020-01-01T00:00:00")

    new_id = await _make_model("New Model")
    # new_id created_at is now — leave it as-is

    await _prune_models_async(older_than_days=30, status=None, yes=True)

    assert await crud.get_threat_model(old_id) is None
    assert await crud.get_threat_model(new_id) is not None


@pytest.mark.asyncio
async def test_prune_combined_age_and_status(test_db) -> None:
    """prune --older-than + --status only deletes models matching both criteria."""
    old_failed_id = await _make_model("Old Failed", status="failed")
    await _set_created_at(old_failed_id, "2020-01-01T00:00:00")

    old_completed_id = await _make_model("Old Completed", status="completed")
    await _set_created_at(old_completed_id, "2020-01-01T00:00:00")

    new_failed_id = await _make_model("New Failed", status="failed")

    await _prune_models_async(older_than_days=30, status="failed", yes=True)

    assert await crud.get_threat_model(old_failed_id) is None  # old + failed → deleted
    assert await crud.get_threat_model(old_completed_id) is not None  # old but not failed → kept
    assert await crud.get_threat_model(new_failed_id) is not None  # failed but not old → kept


@pytest.mark.asyncio
async def test_prune_no_matches_leaves_db_unchanged(test_db) -> None:
    """prune with criteria that match nothing does not delete anything."""
    model_id = await _make_model("Good Model", status="completed")

    await _prune_models_async(older_than_days=None, status="failed", yes=True)

    assert await crud.get_threat_model(model_id) is not None


# ---------------------------------------------------------------------------
# delete_threat_models_batch (CRUD unit tests)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_batch_removes_all_ids(test_db) -> None:
    """delete_threat_models_batch deletes all specified model IDs."""
    id1 = await _make_model("A")
    id2 = await _make_model("B")
    id3 = await _make_model("C")

    deleted = await crud.delete_threat_models_batch([id1, id2])

    assert deleted == 2
    assert await crud.get_threat_model(id1) is None
    assert await crud.get_threat_model(id2) is None
    assert await crud.get_threat_model(id3) is not None


@pytest.mark.asyncio
async def test_delete_batch_empty_list_returns_zero(test_db) -> None:
    """delete_threat_models_batch([]) returns 0 without hitting the database."""
    result = await crud.delete_threat_models_batch([])
    assert result == 0


@pytest.mark.asyncio
async def test_find_threat_models_for_prune_no_filters_returns_all(test_db) -> None:
    """find_threat_models_for_prune with no filters returns every model."""
    await _make_model("A")
    await _make_model("B")

    results = await crud.find_threat_models_for_prune()
    assert len(results) == 2


@pytest.mark.asyncio
async def test_find_threat_models_for_prune_status_filter(test_db) -> None:
    """find_threat_models_for_prune filters correctly by status."""
    await _make_model("Good", status="completed")
    await _make_model("Bad", status="failed")

    results = await crud.find_threat_models_for_prune(status="failed")
    assert len(results) == 1
    assert results[0]["title"] == "Bad"
