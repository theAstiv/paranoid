"""CRUD tests for the code_sources table (Phase 15 Task 4)."""

import pytest

from backend.config import settings
from backend.db import crud
from backend.db.connection import db
from backend.security import source_key
from backend.sources.paths import clone_dir_for, data_dir


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "paranoid.db"))
    monkeypatch.setattr(settings, "config_secret", "")
    monkeypatch.delenv("CONFIG_SECRET", raising=False)
    source_key._reset_cache_for_tests()
    yield
    source_key._reset_cache_for_tests()


@pytest.mark.asyncio
async def test_roundtrip_without_pat(test_db):
    source_id = await crud.create_code_source(
        name="Public repo",
        git_url="https://github.com/example/public.git",
        ref=None,
        pat=None,
    )
    assert source_id
    assert len(source_id) == 32  # uuid4 hex

    fetched = await crud.get_code_source(source_id)
    assert fetched is not None
    assert fetched["name"] == "Public repo"
    assert fetched["git_url"] == "https://github.com/example/public.git"
    assert fetched["ref"] is None
    assert fetched["has_pat"] is False
    # pat_ciphertext must never leak into the public dict.
    assert "pat_ciphertext" not in fetched
    assert fetched["last_index_status"] == "queued"

    listed = await crud.list_code_sources()
    assert [s["id"] for s in listed] == [source_id]


@pytest.mark.asyncio
async def test_pat_roundtrip(test_db):
    source_id = await crud.create_code_source(
        name="Private repo",
        git_url="https://github.com/example/private.git",
        ref="main",
        pat="ghp_exampletoken123",
    )

    fetched = await crud.get_code_source(source_id)
    assert fetched is not None
    assert fetched["has_pat"] is True
    assert fetched["pat_last_used_at"] is None

    # Decrypt roundtrip
    plaintext = await crud.get_code_source_pat(source_id)
    assert plaintext == "ghp_exampletoken123"

    # Mark-used bumps pat_last_used_at
    await crud.mark_code_source_pat_used(source_id)
    fetched = await crud.get_code_source(source_id)
    assert fetched["pat_last_used_at"] is not None


@pytest.mark.asyncio
async def test_status_error_truncation(test_db):
    """``last_index_error`` over 4096 chars is truncated on write."""
    source_id = await crud.create_code_source(
        name="x", git_url="https://github.com/example/x.git", ref=None, pat=None
    )
    huge = "a" * 10_000
    await crud.update_code_source_status(source_id, status="failed", error=huge)

    fetched = await crud.get_code_source(source_id)
    assert fetched["last_index_status"] == "failed"
    assert fetched["last_index_error"].endswith("[truncated]")
    assert len(fetched["last_index_error"]) < len(huge)


@pytest.mark.asyncio
async def test_unique_git_url_ref_conflict(test_db):
    """Second insert with same (git_url, ref) tuple violates the UNIQUE constraint."""
    import aiosqlite

    url = "https://github.com/example/dup.git"
    await crud.create_code_source(name="first", git_url=url, ref="main", pat=None)
    with pytest.raises(aiosqlite.IntegrityError):
        await crud.create_code_source(name="second", git_url=url, ref="main", pat=None)


@pytest.mark.asyncio
async def test_unique_conflict_with_null_ref(test_db):
    """ref=None is normalised to '' so the UNIQUE constraint catches duplicates."""
    import aiosqlite

    url = "https://github.com/example/null-ref-dup.git"
    await crud.create_code_source(name="first", git_url=url, ref=None, pat=None)
    with pytest.raises(aiosqlite.IntegrityError):
        await crud.create_code_source(name="second", git_url=url, ref=None, pat=None)


@pytest.mark.asyncio
async def test_get_code_source_returns_none_for_missing(test_db):
    """get_code_source returns None for a non-existent id."""
    result = await crud.get_code_source("does-not-exist")
    assert result is None


@pytest.mark.asyncio
async def test_different_ref_same_url_is_allowed(test_db):
    url = "https://github.com/example/multi-branch.git"
    a = await crud.create_code_source(name="main", git_url=url, ref="main", pat=None)
    b = await crud.create_code_source(name="dev", git_url=url, ref="dev", pat=None)
    assert a != b


@pytest.mark.asyncio
async def test_delete_returns_true_on_hit_and_false_on_miss(test_db):
    source_id = await crud.create_code_source(
        name="tmp", git_url="https://github.com/example/tmp.git", ref=None, pat=None
    )
    assert await crud.delete_code_source(source_id) is True
    assert await crud.delete_code_source(source_id) is False


@pytest.mark.asyncio
async def test_threat_models_code_source_fk_enforced(test_db):
    """Inserting threat_models with a bogus code_source_id fails — verifies
    that PRAGMA foreign_keys = ON is set on the test connection and the FK
    is declared correctly on the column."""
    import aiosqlite

    conn = await db.get()
    insert_sql = """
        INSERT INTO threat_models (
            id, title, description, framework, provider, model, status,
            iteration_count, created_at, updated_at, code_source_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    params = (
        "tm-1",
        "t",
        "d",
        "STRIDE",
        "anthropic",
        "claude",
        "pending",
        1,
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:00:00Z",
        "does-not-exist",
    )
    with pytest.raises(aiosqlite.IntegrityError):
        await conn.execute(insert_sql, params)


@pytest.mark.asyncio
async def test_threat_models_code_source_set_null_on_delete(test_db):
    """Deleting a code source sets dependent threat_models.code_source_id
    to NULL (ON DELETE SET NULL), not CASCADE — past threat models survive."""
    source_id = await crud.create_code_source(
        name="linked", git_url="https://github.com/example/linked.git", ref=None, pat=None
    )
    model_id = await crud.create_threat_model(
        title="Model linked to source",
        description="d",
        provider="anthropic",
        model="claude",
    )
    conn = await db.get()
    await conn.execute(
        "UPDATE threat_models SET code_source_id = ? WHERE id = ?",
        (source_id, model_id),
    )
    await conn.commit()

    await crud.delete_code_source(source_id)

    async with conn.execute(
        "SELECT code_source_id FROM threat_models WHERE id = ?", (model_id,)
    ) as cur:
        row = await cur.fetchone()
    assert row[0] is None  # set NULL, model survives


def test_clone_dir_for_is_under_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "paranoid.db"))
    path = clone_dir_for("abc123")
    assert path == data_dir() / "sources" / "abc123"
    assert str(path).startswith(str(tmp_path))


@pytest.mark.asyncio
async def test_get_pat_raises_when_source_changed(test_db, monkeypatch):
    """get_code_source_pat raises KeySourceChangedError when Fernet source switched."""
    source_id = await crud.create_code_source(
        name="x",
        git_url="https://github.com/example/keysource.git",
        ref=None,
        pat="ghp_x",
    )
    # Simulate a restart with CONFIG_SECRET now set (file key was used above).
    monkeypatch.setenv("CONFIG_SECRET", "switched-secret")
    source_key._reset_cache_for_tests()
    with pytest.raises(source_key.KeySourceChangedError):
        await crud.get_code_source_pat(source_id)
