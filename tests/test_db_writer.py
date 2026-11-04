"""db.writer() runs on its own connection (review C4) and batches saves (P1).

On the shared connection, any other coroutine's commit() inside a writer()
block committed half of it, and two writer() blocks at once failed with
"cannot start a transaction within a transaction".
"""

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import patch

import aiosqlite
import pytest

from backend.db import crud
from backend.db.connection import db
from backend.pipeline.runner import PipelineEvent, PipelineStep
from backend.routes.models import _persist_pipeline_event
from tests.fixtures.pipeline import make_stride_threats


@pytest.fixture
async def scratch(test_db):
    conn = await db.get()
    await conn.execute("CREATE TABLE scratch (v TEXT)")
    await conn.commit()


async def _values() -> list[str]:
    conn = await db.get()
    async with conn.execute("SELECT v FROM scratch ORDER BY v") as cur:
        return [r[0] for r in await cur.fetchall()]


@pytest.mark.asyncio
async def test_two_writer_blocks_at_once_both_commit(scratch):
    async def write(value: str) -> None:
        async with db.writer() as conn:
            await conn.execute("INSERT INTO scratch VALUES (?)", (value,))
            await asyncio.sleep(0.05)

    await asyncio.gather(write("a"), write("b"))

    assert await _values() == ["a", "b"]


@pytest.mark.asyncio
async def test_a_commit_elsewhere_doesnt_commit_half_a_writer_block(scratch):
    """The block fails after its first insert; another coroutine commits meanwhile."""
    started = asyncio.Event()

    async def failing_block() -> None:
        async with db.writer() as conn:
            await conn.execute("INSERT INTO scratch VALUES ('half')")
            started.set()
            await asyncio.sleep(0.2)
            raise RuntimeError("boom")

    async def other_write() -> None:
        await started.wait()
        conn = await db.get()
        await conn.execute("INSERT INTO scratch VALUES ('other')")
        await conn.commit()

    results = await asyncio.gather(failing_block(), other_write(), return_exceptions=True)

    assert isinstance(results[0], RuntimeError)
    assert await _values() == ["other"]


@pytest.mark.asyncio
async def test_db_get_inside_a_writer_block_is_refused(scratch):
    with pytest.raises(RuntimeError, match=r"inside db\.writer"):
        async with db.writer():
            await db.get()


@pytest.mark.asyncio
async def test_a_nested_writer_block_is_refused_not_deadlocked(scratch):
    with pytest.raises(RuntimeError, match=r"inside db\.writer"):
        async with db.writer(), db.writer():
            pass


@pytest.mark.asyncio
async def test_get_works_again_after_the_block(scratch):
    async with db.writer() as conn:
        await conn.execute("INSERT INTO scratch VALUES ('x')")

    assert await _values() == ["x"]


# ---------------------------------------------------------------------------
# _persist_pipeline_event saves a list in one transaction (P1)
# ---------------------------------------------------------------------------


@pytest.fixture
async def model_id(test_db):
    return await crud.create_threat_model(
        title="Batch",
        description="An API in front of a database.",
        provider="ollama",
        model="llama3.1:8b",
        framework="STRIDE",
    )


def _complete() -> PipelineEvent:
    return PipelineEvent(
        step=PipelineStep.COMPLETE,
        status="completed",
        message="done",
        data={"threats": make_stride_threats()},
    )


@pytest.mark.asyncio
async def test_threats_are_saved_on_one_writer_connection(model_id):
    real = crud.create_threat
    conns = []

    async def spy(*args, **kwargs):
        conns.append(kwargs.get("conn"))
        return await real(*args, **kwargs)

    with patch("backend.routes.models.crud.create_threat", side_effect=spy):
        await _persist_pipeline_event(model_id, _complete())

    assert len(conns) == len(make_stride_threats().threats)
    assert conns[0] is not None
    assert all(c is conns[0] for c in conns)
    assert len(await crud.list_threats(model_id)) == len(conns)


@pytest.mark.asyncio
async def test_one_bad_threat_is_skipped_and_the_rest_saved(model_id):
    real = crud.create_threat
    threats = make_stride_threats().threats
    bad = threats[1].name

    async def flaky(*args, **kwargs):
        if kwargs["name"] == bad:
            raise ValueError("bad row")
        return await real(*args, **kwargs)

    with patch("backend.routes.models.crud.create_threat", side_effect=flaky):
        await _persist_pipeline_event(model_id, _complete())

    saved = {t["name"] for t in await crud.list_threats(model_id)}
    assert saved == {t.name for t in threats} - {bad}


@pytest.mark.asyncio
async def test_without_a_transaction_rows_are_saved_one_by_one(model_id):
    @asynccontextmanager
    async def busy_writer():
        raise aiosqlite.OperationalError("database is locked")
        yield  # pragma: no cover

    with patch("backend.routes.models.db.writer", busy_writer):
        await _persist_pipeline_event(model_id, _complete())

    assert len(await crud.list_threats(model_id)) == len(make_stride_threats().threats)
