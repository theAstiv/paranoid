"""Tests for entity-level comment CRUD operations."""

import pytest

from backend.db import crud_comments
from backend.db.connection import db


async def _seed_model(model_id: str = "model-1") -> None:
    conn = await db.get()
    await conn.execute(
        "INSERT INTO threat_models (id, title, provider, model, status, created_at, updated_at) "
        "VALUES (?, 'Test', 'anthropic', 'claude', 'pending', '2024-01-01', '2024-01-01')",
        (model_id,),
    )
    await conn.commit()


@pytest.mark.asyncio
async def test_create_comment_with_entity_fields(test_db):
    await _seed_model()
    comment = await crud_comments.create_comment(
        threat_model_id="model-1",
        user_id=None,
        body="Entity comment",
        entity_type="threat",
        entity_id="threat-1",
    )
    assert comment["entity_type"] == "threat"
    assert comment["entity_id"] == "threat-1"


@pytest.mark.asyncio
async def test_create_comment_without_entity_fields(test_db):
    await _seed_model()
    comment = await crud_comments.create_comment(
        threat_model_id="model-1",
        user_id=None,
        body="Model-level comment",
    )
    assert comment["entity_type"] is None
    assert comment["entity_id"] is None


@pytest.mark.asyncio
async def test_list_comments_entity_filter(test_db):
    await _seed_model()
    await crud_comments.create_comment(
        "model-1", None, "On threat", entity_type="threat", entity_id="t1"
    )
    await crud_comments.create_comment(
        "model-1", None, "On asset", entity_type="asset", entity_id="a1"
    )
    await crud_comments.create_comment("model-1", None, "Model-level")

    threat_comments = await crud_comments.list_comments(
        "model-1", entity_type="threat", entity_id="t1"
    )
    assert len(threat_comments) == 1
    assert threat_comments[0]["body"] == "On threat"


@pytest.mark.asyncio
async def test_list_comments_model_sentinel(test_db):
    await _seed_model()
    await crud_comments.create_comment(
        "model-1", None, "On threat", entity_type="threat", entity_id="t1"
    )
    await crud_comments.create_comment("model-1", None, "Model-level")

    model_comments = await crud_comments.list_comments("model-1", entity_type="model")
    assert len(model_comments) == 1
    assert model_comments[0]["body"] == "Model-level"


@pytest.mark.asyncio
async def test_list_comments_no_filter_returns_all(test_db):
    await _seed_model()
    await crud_comments.create_comment(
        "model-1", None, "On threat", entity_type="threat", entity_id="t1"
    )
    await crud_comments.create_comment("model-1", None, "Model-level")

    all_comments = await crud_comments.list_comments("model-1")
    assert len(all_comments) == 2


@pytest.mark.asyncio
async def test_count_comments_by_entity(test_db):
    await _seed_model()
    await crud_comments.create_comment("model-1", None, "C1", entity_type="threat", entity_id="t1")
    await crud_comments.create_comment("model-1", None, "C2", entity_type="threat", entity_id="t1")
    await crud_comments.create_comment("model-1", None, "C3", entity_type="asset", entity_id="a1")
    await crud_comments.create_comment("model-1", None, "C4")

    counts = await crud_comments.count_comments_by_entity("model-1")
    by_key = {(r["entity_type"], r["entity_id"]): r["count"] for r in counts}
    assert by_key[("threat", "t1")] == 2
    assert by_key[("asset", "a1")] == 1
    assert by_key[(None, None)] == 1


@pytest.mark.asyncio
async def test_delete_entity_comments(test_db):
    await _seed_model()
    await crud_comments.create_comment(
        "model-1", None, "On t1", entity_type="threat", entity_id="t1"
    )
    await crud_comments.create_comment(
        "model-1", None, "On t2", entity_type="threat", entity_id="t2"
    )
    await crud_comments.create_comment("model-1", None, "Model-level")

    await crud_comments.delete_entity_comments("threat", "t1")

    remaining = await crud_comments.list_comments("model-1")
    assert len(remaining) == 2
    bodies = {c["body"] for c in remaining}
    assert "On t1" not in bodies
    assert "On t2" in bodies
    assert "Model-level" in bodies
