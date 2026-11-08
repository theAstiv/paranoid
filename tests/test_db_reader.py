"""Read-only CRUD functions run on db.reader()'s read-only pool (review A1).

A reader sees committed rows only, so these tests leave a write uncommitted on
the main connection: a function still reading through db.get() would return it.
"""

import aiosqlite
import pytest

from backend.db import crud, crud_auth, crud_comments, crud_projects
from backend.db.connection import db


async def _uncommitted(sql: str, params: tuple) -> aiosqlite.Connection:
    conn = await db.get()
    await conn.execute(sql, params)
    return conn


@pytest.fixture
async def model_id(test_db):
    return await crud.create_threat_model(
        title="Committed",
        description="An API in front of a database.",
        provider="ollama",
        model="llama3.1:8b",
        framework="STRIDE",
    )


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_reader_inside_a_writer_block_is_refused(test_db):
    with pytest.raises(RuntimeError, match=r"db\.reader\(\) inside db\.writer"):
        async with db.writer(), db.reader():
            pass


@pytest.mark.asyncio
async def test_a_nested_reader_is_refused_not_deadlocked(test_db):
    with pytest.raises(RuntimeError, match=r"db\.reader\(\) inside db\.reader"):
        async with db.reader(), db.reader():
            pass


@pytest.mark.asyncio
async def test_a_reader_works_again_after_a_block_that_raised(model_id):
    with pytest.raises(ValueError, match="boom"):
        async with db.reader():
            raise ValueError("boom")

    assert (await crud.get_threat_model(model_id))["title"] == "Committed"


@pytest.mark.asyncio
async def test_reader_connections_are_read_only(test_db):
    async with db.reader() as conn:
        with pytest.raises(aiosqlite.OperationalError, match="readonly"):
            await conn.execute("INSERT INTO config (key, value) VALUES ('k', 'v')")


# ---------------------------------------------------------------------------
# Converted functions read committed rows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_threat_model_reads_committed_rows_only(model_id):
    conn = await _uncommitted(
        "UPDATE threat_models SET title = 'Pending' WHERE id = ?", (model_id,)
    )

    assert (await crud.get_threat_model(model_id))["title"] == "Committed"
    await conn.commit()
    assert (await crud.get_threat_model(model_id))["title"] == "Pending"


@pytest.mark.asyncio
async def test_list_threats_reads_committed_rows_only(model_id):
    threat_id = await crud.create_threat(
        model_id=model_id,
        name="Committed",
        description="d",
        target="db",
        impact="High",
        likelihood="Medium",
        mitigations=["m"],
        stride_category="Tampering",
    )
    conn = await _uncommitted("UPDATE threats SET name = 'Pending' WHERE id = ?", (threat_id,))

    assert [t["name"] for t in await crud.list_threats(model_id)] == ["Committed"]
    await conn.commit()
    assert [t["name"] for t in await crud.list_threats(model_id)] == ["Pending"]


@pytest.mark.asyncio
async def test_get_project_reads_committed_rows_only(test_db):
    owner = await crud_auth.create_user(
        username="owner",
        email="owner@test.local",
        password_hash="unusable",  # noqa: S106 - never used to sign in
    )
    project_id = (await crud_projects.create_project("Committed", owner["id"]))["id"]
    conn = await _uncommitted("UPDATE projects SET name = 'Pending' WHERE id = ?", (project_id,))

    assert (await crud_projects.get_project(project_id))["name"] == "Committed"
    await conn.commit()
    assert (await crud_projects.get_project(project_id))["name"] == "Pending"


@pytest.mark.asyncio
async def test_list_comments_reads_committed_rows_only(model_id):
    comment = await crud_comments.create_comment(model_id, None, "Committed")
    conn = await _uncommitted("UPDATE comments SET body = 'Pending' WHERE id = ?", (comment["id"],))

    assert [c["body"] for c in await crud_comments.list_comments(model_id)] == ["Committed"]
    await conn.commit()
    assert [c["body"] for c in await crud_comments.list_comments(model_id)] == ["Pending"]
