"""Migration 0012: strip credentials from code_sources.git_url, backfill project_id (BB-08, BB-19)."""

import importlib
import logging

import aiosqlite
import pytest

from backend.config import settings
from backend.db.migrations.runner import run_migrations
from backend.security import source_key


DEFAULT_PROJECT_ID = "00000000-0000-0000-0000-000000000000"
SECRET = "ghp_SuperSecretToken123"  # noqa: S105 - fake token the migration must strip

migration = importlib.import_module("backend.db.migrations.0012_strip_source_url_credentials")


@pytest.fixture(autouse=True)
def _key_env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "paranoid.db"))
    monkeypatch.setattr(settings, "config_secret", "")
    monkeypatch.delenv("CONFIG_SECRET", raising=False)
    source_key._reset_cache_for_tests()
    yield
    source_key._reset_cache_for_tests()


@pytest.fixture
async def conn(tmp_path):
    c = await aiosqlite.connect(str(tmp_path / "migration.db"))
    c.row_factory = aiosqlite.Row
    await c.execute("PRAGMA foreign_keys = ON")
    await run_migrations(c)
    yield c
    await c.close()


async def _insert(conn, sid, url, *, ref="", pat=None, project_id=DEFAULT_PROJECT_ID):
    await conn.execute(
        "INSERT INTO code_sources (id, name, git_url, ref, pat_ciphertext, project_id, "
        "last_index_status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'ready', '2024-01-01', '2024-01-01')",
        (sid, sid, url, ref, pat, project_id),
    )
    await conn.commit()


async def _row(conn, sid):
    async with conn.execute("SELECT * FROM code_sources WHERE id = ?", (sid,)) as cur:
        return await cur.fetchone()


@pytest.mark.asyncio
async def test_user_and_password_url_is_stripped_and_password_becomes_the_pat(conn):
    await _insert(conn, "a", f"https://alice:{SECRET}@github.com/o/r.git")

    await migration.up(conn)

    row = await _row(conn, "a")
    assert row["git_url"] == "https://github.com/o/r.git"
    assert source_key.decrypt_pat(bytes(row["pat_ciphertext"])) == SECRET


@pytest.mark.asyncio
async def test_token_only_url_uses_the_username_as_the_pat(conn):
    await _insert(conn, "a", f"https://{SECRET}@github.com/o/r.git")

    await migration.up(conn)

    row = await _row(conn, "a")
    assert row["git_url"] == "https://github.com/o/r.git"
    assert source_key.decrypt_pat(bytes(row["pat_ciphertext"])) == SECRET


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["alice", "x-access-token", "oauth2", "git"])
async def test_username_only_url_is_not_turned_into_a_pat(conn, name):
    # `https://alice@github.com/...` names a user, not a token. Storing "alice" as the
    # PAT would make every clone authenticate as x-access-token:alice and fail, even
    # on public repos.
    await _insert(conn, "a", f"https://{name}@github.com/o/r.git")

    await migration.up(conn)

    row = await _row(conn, "a")
    assert row["git_url"] == "https://github.com/o/r.git"
    assert row["pat_ciphertext"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "token", ["ghp_abc123", "github_pat_11ABC", "glpat-xyz789", "gho_abc", "ghs_abc"]
)
async def test_username_only_url_with_a_known_token_prefix_becomes_the_pat(conn, token):
    await _insert(conn, "a", f"https://{token}@github.com/o/r.git")

    await migration.up(conn)

    row = await _row(conn, "a")
    assert source_key.decrypt_pat(bytes(row["pat_ciphertext"])) == token


@pytest.mark.asyncio
async def test_existing_pat_is_kept_and_url_credentials_are_dropped(conn):
    existing = source_key.encrypt_pat("already-stored")
    await _insert(conn, "a", f"https://x:{SECRET}@github.com/o/r.git", pat=existing)

    await migration.up(conn)

    row = await _row(conn, "a")
    assert row["git_url"] == "https://github.com/o/r.git"
    assert bytes(row["pat_ciphertext"]) == existing


@pytest.mark.asyncio
async def test_clean_url_and_port_are_untouched(conn):
    await _insert(conn, "a", "https://github.com/o/r.git")
    await _insert(conn, "b", f"https://u:{SECRET}@git.example.com:8443/o/r.git", ref="dev")

    await migration.up(conn)

    assert (await _row(conn, "a"))["git_url"] == "https://github.com/o/r.git"
    assert (await _row(conn, "a"))["pat_ciphertext"] is None
    assert (await _row(conn, "b"))["git_url"] == "https://git.example.com:8443/o/r.git"


@pytest.mark.asyncio
async def test_clash_after_stripping_marks_the_duplicate_failed_without_credentials(conn):
    await _insert(conn, "keep", "https://github.com/o/r.git")
    await _insert(conn, "dupe", f"https://u:{SECRET}@github.com/o/r.git")

    await migration.up(conn)

    dupe = await _row(conn, "dupe")
    assert SECRET not in dupe["git_url"]
    assert "@" not in dupe["git_url"]
    assert dupe["git_url"] != "https://github.com/o/r.git"
    assert dupe["last_index_status"] == "failed"
    assert "re-add" in dupe["last_index_error"].lower()
    assert (await _row(conn, "keep"))["git_url"] == "https://github.com/o/r.git"


@pytest.mark.asyncio
async def test_pat_is_dropped_when_the_key_source_differs_from_the_recorded_one(conn):
    await conn.execute(
        "INSERT INTO config (key, value, encrypted, updated_at) "
        "VALUES ('pat_key_source', ?, 0, '2024-01-01')",
        (b"config_secret",),  # active source in this test is "file"
    )
    await conn.commit()
    await _insert(conn, "a", f"https://u:{SECRET}@github.com/o/r.git")

    await migration.up(conn)

    row = await _row(conn, "a")
    assert row["git_url"] == "https://github.com/o/r.git"
    assert row["pat_ciphertext"] is None


@pytest.mark.asyncio
async def test_key_source_is_recorded_when_a_pat_is_encrypted(conn):
    await _insert(conn, "a", f"https://u:{SECRET}@github.com/o/r.git")

    await migration.up(conn)

    async with conn.execute("SELECT value FROM config WHERE key = 'pat_key_source'") as cur:
        row = await cur.fetchone()
    assert bytes(row[0]) == b"file"


@pytest.mark.asyncio
async def test_secret_never_reaches_the_log_but_the_row_id_does(conn, caplog):
    await _insert(conn, "rowid-1", f"https://u:{SECRET}@github.com/o/r.git")

    with caplog.at_level(logging.INFO):
        await migration.up(conn)

    assert SECRET not in caplog.text
    assert "rowid-1" in caplog.text


@pytest.mark.asyncio
async def test_null_project_sources_get_the_default_project(conn):
    await _insert(conn, "a", "https://github.com/o/a.git", project_id=None)
    await _insert(conn, "b", "https://github.com/o/b.git", project_id=None)

    await migration.up(conn)

    assert (await _row(conn, "a"))["project_id"] == DEFAULT_PROJECT_ID
    assert (await _row(conn, "b"))["project_id"] == DEFAULT_PROJECT_ID


@pytest.mark.asyncio
async def test_migration_is_idempotent(conn):
    await _insert(conn, "a", f"https://u:{SECRET}@github.com/o/r.git")
    await migration.up(conn)
    first = dict(await _row(conn, "a"))

    await migration.up(conn)

    assert dict(await _row(conn, "a")) == first
