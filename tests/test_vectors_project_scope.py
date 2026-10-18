"""Project-scoped RAG on a real sqlite-vec DB (bug-bash-plan.md §7.7, "Project-scoped RAG").

Threats approved through the real PATCH route in project 1 must come back for a
search as project 1 and never as project 2; seed rows (source='seed') come back for
both. tests/test_rules.py only checks with a mock that project_id is passed along.

The shared `test_db` fixture skips the sqlite-vec extension, so this file opens its
own temp DB with the extension loaded, and skips if the extension can't load.
Embeddings are a constant unit vector: every row is equally similar, so the project
filter is the only thing deciding what comes back. No LLM, no network.
"""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import patch

import aiosqlite
import pytest
from httpx import ASGITransport, AsyncClient

from backend.auth.tokens import create_access_token
from backend.config import settings
from backend.db import crud, crud_auth, crud_projects
from backend.db.connection import db
from backend.db.schema import init_database_with_connection
from backend.db.vectors import bulk_insert_seed_vectors, search_similar_threats
from backend.main import app
from backend.rules.engine import fetch_rag_context


_DIM = 384


def _constant_embedding(_text: str) -> list[float]:
    return [1.0 / _DIM**0.5] * _DIM


@pytest.fixture
async def vec_db():
    sqlite_vec = pytest.importorskip("sqlite_vec")
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    if db._connection is not None:
        await db._connection.close()
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    try:
        await conn.enable_load_extension(True)
        await conn.load_extension(sqlite_vec.loadable_path())
    except (AttributeError, aiosqlite.OperationalError) as exc:
        await conn.close()
        Path(db_path).unlink(missing_ok=True)
        pytest.skip(f"sqlite-vec extension can't load here: {exc}")
    await conn.execute("PRAGMA foreign_keys = ON;")
    await conn.commit()
    await init_database_with_connection(conn)

    db._connection = conn
    db._db_path = db_path
    db._initialized = True
    db._reader_pool = asyncio.Queue()
    db._reader_pool.put_nowait(conn)
    with patch("backend.db.vectors.embed_text", _constant_embedding):
        yield db_path

    await conn.close()
    db._connection = None
    db._initialized = False
    db._db_path = None
    db._reader_pool = None
    Path(db_path).unlink(missing_ok=True)


async def _threat(model_id: str, name: str) -> str:
    return await crud.create_threat(
        model_id=model_id,
        name=name,
        description=f"{name} description",
        target="db",
        impact="High",
        likelihood="Medium",
        mitigations=["m"],
        stride_category="Tampering",
    )


async def _setup() -> dict:
    owner = await crud_auth.create_user(
        username="owner",
        email="owner@test.local",
        password_hash="unusable",  # noqa: S106 - token minted directly
    )
    p1 = (await crud_projects.create_project("P1", owner["id"]))["id"]
    p2 = (await crud_projects.create_project("P2", owner["id"]))["id"]
    model_a = await crud.create_threat_model(
        title="A", description="d", provider="anthropic", model="m", project_id=p1
    )
    model_c = await crud.create_threat_model(
        title="C", description="d", provider="anthropic", model="m", project_id=p2
    )
    approved = [await _threat(model_a, f"P1 approved {i}") for i in range(3)]
    pending_p1 = await _threat(model_a, "P1 still pending")
    approved_p2 = await _threat(model_c, "P2 approved")

    seed_model = await crud.create_threat_model(
        title="Seeds", description="d", provider="seed", model="seed"
    )
    seed = await _threat(seed_model, "Seed pattern")
    await bulk_insert_seed_vectors([{"id": seed, "text": "Seed pattern"}])

    token = create_access_token(owner["id"], "owner", False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for threat_id in [*approved, approved_p2]:
            r = await client.patch(
                f"/api/threats/{threat_id}",
                json={"status": "approved"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 200, r.text
    return {
        "p1": p1,
        "p2": p2,
        "approved_p1": set(approved),
        "pending_p1": pending_p1,
        "approved_p2": approved_p2,
        "seed": seed,
    }


@pytest.mark.asyncio
async def test_approved_threats_are_rag_context_only_in_their_own_project(vec_db, monkeypatch):
    monkeypatch.setattr(settings, "paranoid_require_auth", True)
    s = await _setup()

    as_p1 = {
        r["threat_id"] for r in await search_similar_threats("q", limit=50, project_id=s["p1"])
    }
    as_p2 = {
        r["threat_id"] for r in await search_similar_threats("q", limit=50, project_id=s["p2"])
    }

    assert as_p1 == s["approved_p1"] | {s["seed"]}
    assert as_p2 == {s["approved_p2"], s["seed"]}
    assert s["pending_p1"] not in as_p1  # only approved threats are embedded

    # A project with no approvals of its own still gets the seed corpus.
    owner = await crud_auth.get_user_by_username("owner")
    p3 = (await crud_projects.create_project("P3", owner["id"]))["id"]
    as_p3 = await search_similar_threats("q", limit=50, project_id=p3)
    assert [(r["threat_id"], r["source"]) for r in as_p3] == [(s["seed"], "seed")]


@pytest.mark.asyncio
async def test_rag_context_for_the_pipeline_is_scoped_too(vec_db, monkeypatch):
    """fetch_rag_context is what the runner calls (runner.py, project_id from the model)."""
    monkeypatch.setattr(settings, "paranoid_require_auth", True)
    await _setup()

    p1_context = "\n".join(
        await fetch_rag_context("q", limit=50, project_id=(await _project("P1")))
    )
    p2_context = "\n".join(
        await fetch_rag_context("q", limit=50, project_id=(await _project("P2")))
    )
    assert "P1 approved" in p1_context
    assert "P1 approved" not in p2_context
    assert "P2 approved" not in p1_context
    assert "Seed pattern" in p1_context
    assert "Seed pattern" in p2_context


@pytest.mark.asyncio
async def test_unapproving_removes_the_threat_from_rag(vec_db, monkeypatch):
    monkeypatch.setattr(settings, "paranoid_require_auth", True)
    s = await _setup()
    owner = await crud_auth.get_user_by_username("owner")
    token = create_access_token(owner["id"], "owner", False)
    gone = next(iter(s["approved_p1"]))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.patch(
            f"/api/threats/{gone}",
            json={"status": "rejected"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200
    as_p1 = {
        r["threat_id"] for r in await search_similar_threats("q", limit=50, project_id=s["p1"])
    }
    assert gone not in as_p1
    assert s["seed"] in as_p1


async def _project(name: str) -> str:
    conn = await db.get()
    async with conn.execute("SELECT id FROM projects WHERE name = ?", (name,)) as cur:
        return (await cur.fetchone())[0]
