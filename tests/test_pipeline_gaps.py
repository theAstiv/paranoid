"""Tests for per-iteration gap persistence and surfacing.

Covers:
- runner emits `gaps` in the COMPLETE event data
- _persist_pipeline_event writes JSON-encoded gaps to threat_models.gap_summaries
- get_model and list_models decode gap_summaries back to a list[str]
- CLI persist_pipeline_result stores the same column
"""

import json

import pytest
from httpx import ASGITransport, AsyncClient

from backend.db import crud
from backend.db.persist import persist_pipeline_result
from backend.main import app
from backend.models.enums import Framework
from backend.pipeline.runner import PipelineEvent, PipelineStep
from backend.routes.models import _persist_pipeline_event


@pytest.fixture
async def client(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def saved_model(test_db):
    model_id = await crud.create_threat_model(
        title="Auth Service",
        description="OAuth2 authentication service with JWT tokens and Redis sessions",
        provider="anthropic",
        model="claude-sonnet-4",
        framework="STRIDE",
        iteration_count=3,
    )
    return await crud.get_threat_model(model_id)


# ---------------------------------------------------------------------------
# _persist_pipeline_event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_pipeline_event_writes_gap_summaries(saved_model, test_db):
    """COMPLETE event with `gaps` writes JSON-encoded array to threat_models.gap_summaries."""
    model_id = saved_model["id"]
    gaps = [
        "Missing Information Disclosure coverage for the database tier.",
        "OAuth flow lacks spoofing analysis.",
    ]
    event = PipelineEvent(
        step=PipelineStep.COMPLETE,
        status="completed",
        message="Pipeline complete",
        data={
            "iterations_completed": 2,
            "total_threats": 0,
            "duration_seconds": 1.0,
            "stopped_reason": "max_iterations",
            "threats": None,
            "gaps": gaps,
        },
    )
    await _persist_pipeline_event(model_id, event)

    record = await crud.get_threat_model(model_id)
    assert record["gap_summaries"] is not None
    assert json.loads(record["gap_summaries"]) == gaps


@pytest.mark.asyncio
async def test_persist_pipeline_event_skips_empty_gaps(saved_model, test_db):
    """COMPLETE event without gaps leaves the column NULL."""
    model_id = saved_model["id"]
    event = PipelineEvent(
        step=PipelineStep.COMPLETE,
        status="completed",
        message="Pipeline complete",
        data={
            "iterations_completed": 1,
            "total_threats": 0,
            "duration_seconds": 1.0,
            "stopped_reason": "gap_satisfied",
            "threats": None,
            "gaps": [],
        },
    )
    await _persist_pipeline_event(model_id, event)

    record = await crud.get_threat_model(model_id)
    assert record.get("gap_summaries") in (None, "")


# ---------------------------------------------------------------------------
# get_model / list_models response decoding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_model_returns_gap_summaries_as_list(client, saved_model, test_db):
    """Stored JSON-encoded gaps are decoded into a list in the GET response."""
    model_id = saved_model["id"]
    gaps = ["Gap one.", "Gap two."]
    await crud.update_threat_model(model_id, gap_summaries=json.dumps(gaps))

    resp = await client.get(f"/api/models/{model_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["gap_summaries"] == gaps


@pytest.mark.asyncio
async def test_get_model_with_no_gaps_returns_empty_list(client, saved_model):
    """Models with no gaps stored return an empty list, never None or a string."""
    model_id = saved_model["id"]
    resp = await client.get(f"/api/models/{model_id}")
    assert resp.status_code == 200
    assert resp.json()["gap_summaries"] == []


@pytest.mark.asyncio
async def test_list_models_includes_gap_summaries(client, saved_model, test_db):
    """Each list row decodes its gap_summaries column to a list."""
    model_id = saved_model["id"]
    await crud.update_threat_model(model_id, gap_summaries=json.dumps(["g1"]))

    resp = await client.get("/api/models/")
    assert resp.status_code == 200
    rows = resp.json()
    matching = [r for r in rows if r["id"] == model_id]
    assert len(matching) == 1
    assert matching[0]["gap_summaries"] == ["g1"]


# ---------------------------------------------------------------------------
# CLI persist path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cli_persist_writes_gap_summaries(test_db):
    """persist_pipeline_result stores gap_summaries when passed."""
    gaps = ["CLI gap 1", "CLI gap 2"]
    model_id = await persist_pipeline_result(
        title="cli-test",
        description="A long enough description for the validators to accept it cleanly.",
        provider="anthropic",
        model_name="claude-sonnet-4",
        framework=Framework.STRIDE,
        iterations_completed=2,
        assets=None,
        flows=None,
        threats=None,
        gap_summaries=gaps,
    )
    assert model_id is not None

    record = await crud.get_threat_model(model_id)
    assert json.loads(record["gap_summaries"]) == gaps
