"""Tests for component IDs (B1): migration 0013, linking, relinking, backfill, persistence."""

import importlib

import aiosqlite
import pytest

from backend.db import component_links, crud
from backend.db.component_links import (
    backfill_component_links,
    link_model_components,
    relink_boundary,
    relink_flow,
    relink_threat,
    try_link_model_components,
)
from backend.db.connection import db
from backend.db.migrations.runner import run_migrations
from backend.db.persist import persist_pipeline_result
from backend.models.enums import Framework
from tests.fixtures.pipeline import make_assets, make_flows, make_stride_threats


migration = importlib.import_module("backend.db.migrations.0013_component_ids")


async def _model() -> str:
    return await crud.create_threat_model(
        title="Links",
        description="desc",
        provider="anthropic",
        model="claude-sonnet-4",
        framework="STRIDE",
        iteration_count=1,
    )


async def _asset(model_id: str, name: str) -> str:
    return await crud.create_asset(
        model_id=model_id, asset_type="Asset", name=name, description="d"
    )


async def _flow(model_id: str, source: str, target: str) -> str:
    return await crud.create_flow(
        model_id=model_id,
        flow_type="data",
        flow_description="d",
        source_entity=source,
        target_entity=target,
    )


async def _boundary(model_id: str, source: str, target: str) -> str:
    return await crud.create_trust_boundary(
        model_id=model_id, purpose="p", source_entity=source, target_entity=target
    )


async def _threat(model_id: str, target: str) -> str:
    return await crud.create_threat(
        model_id=model_id,
        name="T",
        description="An attacker does something to the target component.",
        target=target,
        impact="High",
        likelihood="High",
        mitigations=["[P] fix"],
        stride_category="Tampering",
    )


# --- migration -------------------------------------------------------------


@pytest.fixture
async def raw_conn(tmp_path):
    c = await aiosqlite.connect(str(tmp_path / "migration.db"))
    c.row_factory = aiosqlite.Row
    await c.execute("PRAGMA foreign_keys = ON")
    await run_migrations(c)
    yield c
    await c.close()


async def _columns(conn, table):
    async with conn.execute(f"PRAGMA table_info({table})") as cur:
        return {row["name"] for row in await cur.fetchall()}


@pytest.mark.asyncio
async def test_0013_adds_asset_link_columns(raw_conn):
    assert {"source_asset_id", "target_asset_id"} <= await _columns(raw_conn, "flows")
    assert {"source_asset_id", "target_asset_id"} <= await _columns(raw_conn, "trust_boundaries")
    assert "target_asset_id" in await _columns(raw_conn, "threats")


@pytest.mark.asyncio
async def test_0013_is_idempotent(raw_conn):
    await migration.up(raw_conn)
    await migration.up(raw_conn)
    assert "target_asset_id" in await _columns(raw_conn, "threats")


@pytest.mark.asyncio
async def test_0013_creates_indexes(raw_conn):
    async with raw_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%asset_id'"
    ) as cur:
        names = {row["name"] for row in await cur.fetchall()}
    assert {"idx_flows_source_asset_id", "idx_threats_target_asset_id"} <= names


@pytest.mark.asyncio
async def test_0013_leaves_existing_rows_unlinked(raw_conn):
    await raw_conn.execute(
        "INSERT INTO threat_models (id, title, description, provider, model, framework, status, "
        "created_at, updated_at) VALUES ('m', 't', 'd', 'p', 'm', 'STRIDE', 'draft', 'x', 'x')"
    )
    await raw_conn.execute(
        "INSERT INTO flows (id, model_id, flow_type, flow_description, source_entity, "
        "target_entity, created_at) VALUES ('f', 'm', 'data', 'd', 'A', 'B', 'x')"
    )
    await raw_conn.commit()
    async with raw_conn.execute("SELECT source_asset_id, target_asset_id FROM flows") as cur:
        row = await cur.fetchone()
    assert row["source_asset_id"] is None
    assert row["target_asset_id"] is None


# --- linking ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_link_fills_flows_boundaries_and_threats(test_db):
    m = await _model()
    api = await _asset(m, "API Gateway")
    pg = await _asset(m, "PostgreSQL Database")
    f = await _flow(m, "api gateway", "PostgreSQL Database (primary)")
    b = await _boundary(m, "API Gateway", "PostgreSQL Database")
    t = await _threat(m, "PostgreSQL Database")

    stats = await link_model_components(m)

    flow = await crud.get_flow(f)
    assert (flow["source_asset_id"], flow["target_asset_id"]) == (api, pg)
    boundary = await crud.get_trust_boundary(b)
    assert (boundary["source_asset_id"], boundary["target_asset_id"]) == (api, pg)
    assert (await crud.get_threat(t))["target_asset_id"] == pg
    assert stats == {"linked": 5, "unresolved": 0}


@pytest.mark.asyncio
async def test_unresolved_text_stays_null_and_is_counted(test_db):
    m = await _model()
    await _asset(m, "API Gateway")
    f = await _flow(m, "API Gateway", "Kubernetes cluster")

    stats = await link_model_components(m)

    flow = await crud.get_flow(f)
    assert flow["source_asset_id"] is not None
    assert flow["target_asset_id"] is None
    assert stats == {"linked": 1, "unresolved": 1}


@pytest.mark.asyncio
async def test_link_is_idempotent_and_keeps_existing_links(test_db):
    m = await _model()
    api = await _asset(m, "API Gateway")
    f = await _flow(m, "API Gateway", "API Gateway")
    await link_model_components(m)

    second = await link_model_components(m)

    assert second == {"linked": 0, "unresolved": 0}
    assert (await crud.get_flow(f))["source_asset_id"] == api


@pytest.mark.asyncio
async def test_no_assets_means_nothing_to_link(test_db):
    m = await _model()
    await _flow(m, "A", "B")
    assert await link_model_components(m) == {"linked": 0, "unresolved": 0}


@pytest.mark.asyncio
async def test_asset_rename_keeps_links(test_db):
    m = await _model()
    api = await _asset(m, "API Gateway")
    f = await _flow(m, "API Gateway", "API Gateway")
    await link_model_components(m)

    await crud.update_asset(api, name="Edge Proxy")
    await link_model_components(m)

    assert (await crud.get_flow(f))["source_asset_id"] == api


@pytest.mark.asyncio
async def test_asset_delete_nulls_links_but_keeps_rows(test_db):
    m = await _model()
    api = await _asset(m, "API Gateway")
    f = await _flow(m, "API Gateway", "API Gateway")
    t = await _threat(m, "API Gateway")
    await link_model_components(m)

    await crud.delete_asset(api)

    flow = await crud.get_flow(f)
    assert flow is not None
    assert flow["source_asset_id"] is None
    assert flow["source_entity"] == "API Gateway"
    assert (await crud.get_threat(t))["target_asset_id"] is None


@pytest.mark.asyncio
async def test_new_asset_resolves_previously_unresolved_rows(test_db):
    m = await _model()
    await _asset(m, "API Gateway")
    f = await _flow(m, "API Gateway", "Redis cache")
    await link_model_components(m)
    assert (await crud.get_flow(f))["target_asset_id"] is None

    redis = await _asset(m, "Redis cache")
    await link_model_components(m)

    assert (await crud.get_flow(f))["target_asset_id"] == redis


@pytest.mark.asyncio
async def test_clear_and_relink_after_rerun_points_at_new_assets(test_db):
    m = await _model()
    old = await _asset(m, "API Gateway")
    f = await _flow(m, "API Gateway", "API Gateway")
    await link_model_components(m)

    await crud.clear_model_data(m, preserve_user_edits=True)
    # Simulate a user-edited flow surviving while its asset is re-extracted.
    f2 = await _flow(m, "API Gateway", "API Gateway")
    new = await _asset(m, "API Gateway")
    await link_model_components(m)

    assert new != old
    assert await crud.get_flow(f) is None
    assert (await crud.get_flow(f2))["source_asset_id"] == new


# --- relink on edit --------------------------------------------------------


@pytest.mark.asyncio
async def test_relink_flow_reresolves_only_the_edited_side(test_db):
    m = await _model()
    api = await _asset(m, "API Gateway")
    pg = await _asset(m, "PostgreSQL Database")
    f = await _flow(m, "API Gateway", "API Gateway")
    await link_model_components(m)

    await crud.update_flow(f, target_entity="PostgreSQL Database")
    await relink_flow(f, target="PostgreSQL Database")

    flow = await crud.get_flow(f)
    assert (flow["source_asset_id"], flow["target_asset_id"]) == (api, pg)


@pytest.mark.asyncio
async def test_relink_flow_clears_link_when_new_text_matches_nothing(test_db):
    m = await _model()
    await _asset(m, "API Gateway")
    f = await _flow(m, "API Gateway", "API Gateway")
    await link_model_components(m)

    await crud.update_flow(f, source_entity="Something else")
    await relink_flow(f, source="Something else")

    assert (await crud.get_flow(f))["source_asset_id"] is None


@pytest.mark.asyncio
async def test_relink_boundary_and_threat(test_db):
    m = await _model()
    api = await _asset(m, "API Gateway")
    pg = await _asset(m, "PostgreSQL Database")
    b = await _boundary(m, "API Gateway", "nothing")
    t = await _threat(m, "nothing")
    await link_model_components(m)

    await crud.update_trust_boundary(b, target_entity="PostgreSQL Database")
    await relink_boundary(b, target="PostgreSQL Database")
    await crud.update_threat(t, target="API Gateway")
    await relink_threat(t, "API Gateway")

    boundary = await crud.get_trust_boundary(b)
    assert (boundary["source_asset_id"], boundary["target_asset_id"]) == (api, pg)
    assert (await crud.get_threat(t))["target_asset_id"] == api


@pytest.mark.asyncio
async def test_relink_with_no_changed_side_is_a_noop(test_db):
    m = await _model()
    await _asset(m, "API Gateway")
    f = await _flow(m, "API Gateway", "API Gateway")
    await relink_flow(f)
    assert (await crud.get_flow(f))["source_asset_id"] is None


# --- backfill and failure isolation ---------------------------------------


@pytest.mark.asyncio
async def test_backfill_links_old_models_once(test_db):
    m1 = await _model()
    m2 = await _model()
    api1 = await _asset(m1, "API Gateway")
    f1 = await _flow(m1, "API Gateway", "unknown")
    await _asset(m2, "Worker Process")
    f2 = await _flow(m2, "Worker Process", "Worker Process")

    await backfill_component_links()

    one, two = await crud.get_flow(f1), await crud.get_flow(f2)
    assert one["source_asset_id"] == api1
    assert one["target_asset_id"] is None
    assert two["source_asset_id"] is not None
    assert await crud.get_config_value("component_links_backfilled") == "1"


@pytest.mark.asyncio
async def test_backfill_does_not_rescan_after_the_first_run(test_db, monkeypatch):
    m = await _model()
    await _asset(m, "API Gateway")
    await _flow(m, "API Gateway", "API Gateway")
    await backfill_component_links()

    async def boom(model_id):
        raise AssertionError("second startup must not rescan")

    monkeypatch.setattr(component_links, "link_model_components", boom)
    await backfill_component_links()  # flag set: returns before touching any model


@pytest.mark.asyncio
async def test_failed_backfill_leaves_flag_unset_so_it_retries(test_db, monkeypatch):
    m = await _model()
    await _asset(m, "API Gateway")

    async def boom(model_id):
        raise RuntimeError("nope")

    monkeypatch.setattr(component_links, "link_model_components", boom)
    await backfill_component_links()

    assert await crud.get_config_value("component_links_backfilled") is None


@pytest.mark.asyncio
async def test_threat_target_with_a_generic_short_asset_links_the_specific_one(test_db):
    m = await _model()
    await _asset(m, "User")
    db_id = await _asset(m, "Database")
    t = await _threat(m, "Attacker impersonating user to reach Database")

    await link_model_components(m)

    assert (await crud.get_threat(t))["target_asset_id"] == db_id


@pytest.mark.asyncio
async def test_backfill_never_raises(test_db, monkeypatch):
    async def boom(model_id):
        raise RuntimeError("resolver exploded")

    monkeypatch.setattr(component_links, "link_model_components", boom)
    m = await _model()
    await _asset(m, "A Thing")
    await _flow(m, "A Thing", "x")

    await backfill_component_links()  # must not raise


@pytest.mark.asyncio
async def test_try_link_swallows_errors(test_db, monkeypatch):
    async def boom(model_id):
        raise RuntimeError("nope")

    monkeypatch.setattr(component_links, "link_model_components", boom)
    await try_link_model_components("anything")


# --- persistence paths -----------------------------------------------------


@pytest.mark.asyncio
async def test_cli_persist_path_links_flows_boundaries_and_threats(test_db):
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
    assert model_id

    asset_ids = {a["id"] for a in await crud.list_assets(model_id)}
    flows = await crud.list_flows(model_id)
    boundaries = await crud.list_trust_boundaries(model_id)
    assert flows
    assert boundaries
    for row in [*flows, *boundaries]:
        assert row["source_asset_id"] in asset_ids
        assert row["target_asset_id"] in asset_ids
    for threat in await crud.list_threats(model_id):
        assert threat["target_asset_id"] is None or threat["target_asset_id"] in asset_ids


@pytest.mark.asyncio
async def test_web_persist_path_links_after_each_event(test_db):
    from backend.pipeline.runner import PipelineEvent, PipelineStep
    from backend.routes.models import _persist_pipeline_event

    model_id = await _model()
    assets, flows, threats = make_assets(), make_flows(), make_stride_threats()
    threats.threats[0].target = "API Gateway"
    await _persist_pipeline_event(
        model_id,
        PipelineEvent(
            step=PipelineStep.EXTRACT_ASSETS,
            status="completed",
            message="",
            data={"assets": assets},
        ),
    )
    await _persist_pipeline_event(
        model_id,
        PipelineEvent(
            step=PipelineStep.EXTRACT_FLOWS, status="completed", message="", data={"flows": flows}
        ),
    )
    after_flows = await crud.list_flows(model_id)
    assert all(f["source_asset_id"] and f["target_asset_id"] for f in after_flows)

    await _persist_pipeline_event(
        model_id,
        PipelineEvent(
            step=PipelineStep.COMPLETE,
            status="completed",
            message="",
            data={"threats": threats},
        ),
    )
    asset_ids = {a["id"] for a in await crud.list_assets(model_id)}
    saved = await crud.list_threats(model_id)
    assert any(t["target_asset_id"] in asset_ids for t in saved)
    assert all(t["target_asset_id"] is None or t["target_asset_id"] in asset_ids for t in saved)


@pytest.mark.asyncio
async def test_link_uses_the_shared_connection(test_db):
    """Sanity: link functions write through the same connection the CRUD layer uses."""
    m = await _model()
    api = await _asset(m, "API Gateway")
    f = await _flow(m, "API Gateway", "x")
    await link_model_components(m)
    conn = await db.get()
    async with conn.execute("SELECT source_asset_id FROM flows WHERE id = ?", (f,)) as cur:
        assert (await cur.fetchone())["source_asset_id"] == api
