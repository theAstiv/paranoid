"""Tests for MAESTRO applicability (B2): migration 0014, tagging, backfill, persistence, API."""

import importlib
import json

import aiosqlite
import pytest
from httpx import ASGITransport, AsyncClient

from backend.db import crud, maestro_tags
from backend.db.maestro_tags import (
    backfill_maestro_tags,
    parse_categories,
    tag_model_assets,
    try_tag_model_assets,
)
from backend.db.migrations.runner import run_migrations
from backend.db.persist import persist_pipeline_result
from backend.main import app
from backend.models.enums import Framework
from backend.pipeline.nodes.maestro_tags import rules_version
from tests.fixtures.pipeline import make_assets, make_flows, make_stride_threats


migration = importlib.import_module("backend.db.migrations.0014_asset_maestro_categories")


async def _model() -> str:
    return await crud.create_threat_model(
        title="Tags",
        description="desc",
        provider="anthropic",
        model="claude-sonnet-4",
        framework="MAESTRO",
        iteration_count=1,
    )


async def _asset(model_id: str, name: str, description: str = "d") -> str:
    return await crud.create_asset(
        model_id=model_id, asset_type="Asset", name=name, description=description
    )


async def _tags(asset_id: str) -> list[str] | None:
    return parse_categories((await crud.get_asset(asset_id))["maestro_categories"])


# --- migration -------------------------------------------------------------


@pytest.fixture
async def raw_conn(tmp_path):
    c = await aiosqlite.connect(str(tmp_path / "migration.db"))
    c.row_factory = aiosqlite.Row
    await run_migrations(c)
    yield c
    await c.close()


@pytest.mark.asyncio
async def test_0014_adds_the_column(raw_conn):
    async with raw_conn.execute("PRAGMA table_info(assets)") as cur:
        assert "maestro_categories" in {row["name"] for row in await cur.fetchall()}


@pytest.mark.asyncio
async def test_0014_is_idempotent(raw_conn):
    await migration.up(raw_conn)
    await migration.up(raw_conn)


@pytest.mark.asyncio
async def test_0014_leaves_existing_assets_untagged(raw_conn):
    await raw_conn.execute(
        "INSERT INTO threat_models (id, title, description, provider, model, framework, status, "
        "created_at, updated_at) VALUES ('m', 't', 'd', 'p', 'm', 'STRIDE', 'draft', 'x', 'x')"
    )
    await raw_conn.execute(
        "INSERT INTO assets (id, model_id, type, name, description, created_at) "
        "VALUES ('a', 'm', 'Asset', 'LLM Gateway', 'd', 'x')"
    )
    await raw_conn.commit()
    async with raw_conn.execute("SELECT maestro_categories FROM assets") as cur:
        assert (await cur.fetchone())["maestro_categories"] is None


# --- tagging -----------------------------------------------------------------


def test_parse_categories_handles_bad_values():
    assert parse_categories(None) is None
    assert parse_categories("not json") is None
    assert parse_categories('{"a": 1}') is None
    assert parse_categories('["LLM Security"]') == ["LLM Security"]


@pytest.mark.asyncio
async def test_tag_model_assets_writes_json_lists(test_db):
    m = await _model()
    llm = await _asset(m, "Support Chatbot", "LLM assistant")
    plain = await _asset(m, "Postgres", "orders database")

    assert await tag_model_assets(m) == 2

    assert await _tags(llm) == ["LLM Security"]
    assert await _tags(plain) == []  # tagged, nothing applies: not NULL


@pytest.mark.asyncio
async def test_tag_model_assets_is_idempotent(test_db):
    m = await _model()
    await _asset(m, "Support Chatbot", "LLM assistant")
    assert await tag_model_assets(m) == 1
    assert await tag_model_assets(m) == 0


@pytest.mark.asyncio
async def test_asset_text_change_retags(test_db):
    m = await _model()
    a = await _asset(m, "Service", "plain service")
    await tag_model_assets(m)
    assert await _tags(a) == []

    await crud.update_asset(a, description="Federated learning coordinator")
    await tag_model_assets(m)

    assert await _tags(a) == ["Distributed ML"]


@pytest.mark.asyncio
async def test_tagger_failure_never_fails_the_caller(test_db, monkeypatch):
    m = await _model()
    await _asset(m, "Support Chatbot", "LLM")

    def boom(*_a, **_k):
        raise RuntimeError("tagger exploded")

    monkeypatch.setattr(maestro_tags, "tag_asset", boom)
    await try_tag_model_assets(m)  # must not raise


# --- backfill ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_backfill_tags_old_models_once(test_db, monkeypatch):
    m = await _model()
    a = await _asset(m, "Support Chatbot", "LLM")

    await backfill_maestro_tags()

    assert await _tags(a) == ["LLM Security"]
    assert await crud.get_config_value("maestro_tags_backfilled") == rules_version()

    async def boom(model_id):
        raise AssertionError("second startup must not rescan")

    monkeypatch.setattr(maestro_tags, "tag_model_assets", boom)
    await backfill_maestro_tags()


@pytest.mark.asyncio
async def test_failed_backfill_leaves_flag_unset_so_it_retries(test_db, monkeypatch):
    m = await _model()
    await _asset(m, "Support Chatbot", "LLM")

    async def boom(model_id):
        raise RuntimeError("db hiccup")

    monkeypatch.setattr(maestro_tags, "tag_model_assets", boom)
    await backfill_maestro_tags()  # swallowed

    assert await crud.get_config_value("maestro_tags_backfilled") is None


# --- persistence paths -------------------------------------------------------


@pytest.mark.asyncio
async def test_cli_persist_path_tags_assets(test_db):
    model_id = await persist_pipeline_result(
        title="t",
        description="Document sharing app",
        provider="anthropic",
        model_name="m",
        framework=Framework.STRIDE,
        iterations_completed=1,
        assets=make_assets(),
        flows=make_flows(),
        threats=make_stride_threats(),
    )
    rows = await crud.list_assets(model_id)
    assert rows
    assert all(parse_categories(r["maestro_categories"]) is not None for r in rows)


@pytest.mark.asyncio
async def test_web_persist_path_tags_right_after_assets(test_db):
    from backend.pipeline.runner import PipelineEvent, PipelineStep
    from backend.routes.models import _persist_pipeline_event

    model_id = await _model()
    await _persist_pipeline_event(
        model_id,
        PipelineEvent(
            step=PipelineStep.EXTRACT_ASSETS,
            status="completed",
            message="",
            data={"assets": make_assets()},
        ),
    )
    rows = await crud.list_assets(model_id)
    assert rows
    assert all(parse_categories(r["maestro_categories"]) is not None for r in rows)


# --- API ---------------------------------------------------------------------


@pytest.fixture
async def client(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_asset_routes_return_categories_as_lists(client):
    m = await _model()
    created = await client.post(
        f"/api/models/{m}/assets",
        json={"type": "Asset", "name": "Support Chatbot", "description": "LLM assistant"},
    )
    assert created.status_code == 201
    assert created.json()["maestro_categories"] == ["LLM Security"]

    listed = (await client.get(f"/api/models/{m}/assets")).json()
    assert listed[0]["maestro_categories"] == ["LLM Security"]


@pytest.mark.asyncio
async def test_asset_patch_retags(client):
    m = await _model()
    a = await _asset(m, "Service", "plain")
    await tag_model_assets(m)

    resp = await client.patch(
        f"/api/models/{m}/assets/{a}", json={"description": "Reinforcement learning trainer"}
    )

    assert resp.status_code == 200
    assert resp.json()["maestro_categories"] == ["Reinforcement Learning"]
    raw = (await crud.get_asset(a))["maestro_categories"]
    assert json.loads(raw) == ["Reinforcement Learning"]


@pytest.mark.asyncio
async def test_untagged_asset_reads_back_as_null(client):
    m = await _model()
    await _asset(m, "Support Chatbot", "LLM")  # never tagged
    listed = (await client.get(f"/api/models/{m}/assets")).json()
    assert listed[0]["maestro_categories"] is None


@pytest.mark.asyncio
async def test_coverage_route_reports_covered_not_covered_and_na(client):
    m = await _model()
    await _asset(m, "Support Chatbot", "LLM assistant with personal data")
    await tag_model_assets(m)
    await crud.create_threat(
        model_id=m,
        name="Prompt injection",
        description="An attacker injects instructions into the assistant prompt.",
        target="Support Chatbot",
        impact="High",
        likelihood="High",
        mitigations=["[P] filter"],
        stride_category="Tampering",
        maestro_category="LLM Security",
    )

    resp = await client.get(f"/api/models/{m}/maestro-coverage")

    assert resp.status_code == 200
    body = resp.json()
    by_name = {c["category"]: c for c in body["categories"]}
    assert body["assessed"] is True
    assert by_name["LLM Security"] == {
        "category": "LLM Security",
        "status": "covered",
        "threats": 1,
    }
    assert by_name["Privacy"]["status"] == "not_covered"
    assert by_name["Reinforcement Learning"]["status"] == "na"


@pytest.mark.asyncio
async def test_coverage_route_unknown_model_is_404(client):
    assert (await client.get("/api/models/nope/maestro-coverage")).status_code == 404


@pytest.mark.asyncio
async def test_coverage_route_untagged_model_is_not_assessed(client):
    m = await _model()
    await _asset(m, "Support Chatbot", "LLM")  # never tagged
    body = (await client.get(f"/api/models/{m}/maestro-coverage")).json()
    assert body["assessed"] is False
    assert {c["status"] for c in body["categories"]} == {"not_assessed"}


@pytest.mark.asyncio
async def test_web_persist_path_stores_maestro_category(test_db):
    from backend.pipeline.runner import PipelineEvent, PipelineStep
    from backend.routes.models import _persist_pipeline_event
    from tests.fixtures.pipeline import make_maestro_threats

    m = await _model()
    await _persist_pipeline_event(
        m,
        PipelineEvent(
            step=PipelineStep.COMPLETE,
            status="completed",
            message="",
            data={"threats": make_maestro_threats()},
        ),
    )

    stored = {t["maestro_category"] for t in await crud.list_threats(m)}
    assert {"LLM Security", "Model Security", "Data Security"} <= stored
    from backend.db.maestro_tags import get_model_coverage

    coverage = {c["category"]: c for c in (await get_model_coverage(m))["categories"]}
    assert coverage["LLM Security"]["status"] == "covered"


@pytest.mark.asyncio
async def test_rejected_threats_do_not_count_as_coverage(test_db):
    from backend.db.maestro_tags import get_model_coverage

    m = await _model()
    await _asset(m, "Support Chatbot", "LLM assistant")
    await tag_model_assets(m)
    threat_id = await crud.create_threat(
        model_id=m,
        name="Prompt injection",
        description="An attacker injects instructions into the assistant prompt.",
        target="Support Chatbot",
        impact="High",
        likelihood="High",
        mitigations=["[P] filter"],
        stride_category="Tampering",
        maestro_category="LLM Security",
    )

    def llm_status(cov):
        return next(c for c in cov["categories"] if c["category"] == "LLM Security")["status"]

    assert llm_status(await get_model_coverage(m)) == "covered"
    await crud.update_threat_status(threat_id, "rejected")
    assert llm_status(await get_model_coverage(m)) == "not_covered"


@pytest.mark.asyncio
async def test_backfill_reruns_when_the_rules_change(test_db, monkeypatch):
    m = await _model()
    a = await _asset(m, "Service", "Hosts the thing")
    await backfill_maestro_tags()
    assert await _tags(a) == []

    # Same rules, flag set: no rescan.
    async def boom(model_id):
        raise AssertionError("same rules must not rescan")

    real = maestro_tags.tag_model_assets
    monkeypatch.setattr(maestro_tags, "tag_model_assets", boom)
    await backfill_maestro_tags()
    monkeypatch.setattr(maestro_tags, "tag_model_assets", real)

    # A rules change re-tags the saved model.
    from backend.models.enums import MaestroCategory

    monkeypatch.setattr(maestro_tags, "rules_version", lambda: "new-rules")
    monkeypatch.setattr(maestro_tags, "tag_asset", lambda n, d="": [MaestroCategory.DISTRIBUTED_ML])
    await backfill_maestro_tags()
    assert await _tags(a) == ["Distributed ML"]
