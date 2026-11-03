"""Re-extract keeps the context rows a user edited or added, exactly once.

Nothing used to set user_edited, so clear_model_data(preserve_user_edits=True)
deleted edited rows too (found in the Phase 0.5 browser check: a renamed asset
was gone after Re-extract). And once edits are kept, the fresh extraction must
not save the extractor's own copy of them next to the user's.
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from backend.db import crud, kept_context
from backend.models.enums import AssetType
from backend.models.state import (
    Asset,
    AssetsList,
    DataFlow,
    FlowsList,
    TrustBoundary,
)
from backend.pipeline import live_runs
from backend.pipeline.runner import PipelineEvent, PipelineStep
from backend.routes import models as models_routes
from backend.routes.models import _persist_pipeline_event


async def _make_model() -> str:
    return await crud.create_threat_model(
        title="Kept context",
        description="An API in front of a database.",
        provider="ollama",
        model="llama3.1:8b",
        framework="STRIDE",
        iteration_count=1,
    )


def _assets_event(*names: str) -> PipelineEvent:
    return PipelineEvent(
        step=PipelineStep.EXTRACT_ASSETS,
        status="completed",
        message="ok",
        data={
            "assets": AssetsList(
                assets=[Asset(type=AssetType.ASSET, name=n, description="") for n in names]
            )
        },
    )


def _flows_event(
    flows: list[tuple[str, str]], boundaries: list[tuple[str, str]] = ()
) -> PipelineEvent:
    return PipelineEvent(
        step=PipelineStep.EXTRACT_FLOWS,
        status="completed",
        message="ok",
        data={
            "flows": FlowsList(
                data_flows=[
                    DataFlow(flow_description="generated", source_entity=s, target_entity=t)
                    for s, t in flows
                ],
                trust_boundaries=[
                    TrustBoundary(purpose="generated", source_entity=s, target_entity=t)
                    for s, t in boundaries
                ],
                threat_sources=[],
            )
        },
    )


async def _extract(model_id: str, assets: tuple[str, ...], flows, boundaries=()) -> None:
    """What Re-extract does to the DB: clear the pipeline's rows, persist a new extraction."""
    await crud.clear_model_data(model_id, preserve_user_edits=True)
    await _persist_pipeline_event(model_id, _assets_event(*assets))
    await _persist_pipeline_event(model_id, _flows_event(flows, boundaries))


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_normalize_key_ignores_case_and_whitespace() -> None:
    assert kept_context.normalize_key("  User   DB ") == kept_context.normalize_key("user db")


def test_only_user_edited_rows_count_as_kept() -> None:
    rows = [
        {"name": "Generated", "generated_key": "Generated", "user_edited": 0},
        {"name": "Postgres", "generated_key": "DB", "user_edited": 1},
        {"name": "Added", "generated_key": None, "user_edited": 1},
    ]
    assert kept_context.kept_asset_keys(rows) == {"postgres", "db", "added"}
    assert kept_context.asset_renames(rows) == {"db": "Postgres"}


def test_endpoint_rename_maps_the_generated_name_to_the_current_one() -> None:
    renames = {"db": "Postgres"}
    assert kept_context.rename_endpoint("DB", renames) == "Postgres"
    assert kept_context.rename_endpoint("API", renames) == "API"


# ---------------------------------------------------------------------------
# CRUD: edits and user-added rows are marked user_edited
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_rows_are_not_user_edited_and_record_their_generated_key(test_db) -> None:
    model_id = await _make_model()
    asset_id = await crud.create_asset(model_id, "Asset", "DB", "")
    flow_id = await crud.create_flow(model_id, "data", "q", "API", "DB")
    boundary_id = await crud.create_trust_boundary(model_id, "edge", "Internet", "API")

    asset = await crud.get_asset(asset_id)
    flow = await crud.get_flow(flow_id)
    boundary = await crud.get_trust_boundary(boundary_id)
    assert (asset["user_edited"], asset["generated_key"]) == (0, "DB")
    assert (flow["user_edited"], flow["generated_key"]) == (0, "API → DB")
    assert (boundary["user_edited"], boundary["generated_key"]) == (0, "Internet → API")


@pytest.mark.asyncio
async def test_updates_mark_rows_user_edited_and_keep_the_generated_key(test_db) -> None:
    model_id = await _make_model()
    asset_id = await crud.create_asset(model_id, "Asset", "DB", "")
    flow_id = await crud.create_flow(model_id, "data", "q", "API", "DB")
    boundary_id = await crud.create_trust_boundary(model_id, "edge", "Internet", "API")

    await crud.update_asset(asset_id, name="Postgres")
    await crud.update_flow(flow_id, flow_description="SQL over TLS")
    await crud.update_trust_boundary(boundary_id, purpose="WAF")

    asset = await crud.get_asset(asset_id)
    assert (asset["user_edited"], asset["generated_key"]) == (1, "DB")
    assert (await crud.get_flow(flow_id))["user_edited"] == 1
    assert (await crud.get_trust_boundary(boundary_id))["user_edited"] == 1


@pytest.mark.asyncio
async def test_an_empty_update_does_not_mark_the_row(test_db) -> None:
    model_id = await _make_model()
    asset_id = await crud.create_asset(model_id, "Asset", "DB", "")

    await crud.update_asset(asset_id)

    assert (await crud.get_asset(asset_id))["user_edited"] == 0


@pytest.mark.asyncio
async def test_clear_with_preserve_keeps_edited_and_added_rows_only(test_db) -> None:
    model_id = await _make_model()
    edited = await crud.create_asset(model_id, "Asset", "DB", "")
    await crud.create_asset(model_id, "Asset", "Cache", "")
    added = await crud.create_asset(model_id, "Asset", "Queue", "", user_edited=True)
    flow = await crud.create_flow(model_id, "data", "q", "API", "DB")
    await crud.create_flow(model_id, "data", "q", "API", "Cache")
    boundary = await crud.create_trust_boundary(model_id, "edge", "Internet", "API")
    await crud.create_trust_boundary(model_id, "edge", "API", "Cache")
    await crud.update_asset(edited, description="primary store")
    await crud.update_flow(flow, flow_description="SQL")
    await crud.update_trust_boundary(boundary, purpose="WAF")

    await crud.clear_model_data(model_id, preserve_user_edits=True)

    assert {a["id"] for a in await crud.list_assets(model_id)} == {edited, added}
    assert [f["id"] for f in await crud.list_flows(model_id)] == [flow]
    assert [b["id"] for b in await crud.list_trust_boundaries(model_id)] == [boundary]


# ---------------------------------------------------------------------------
# Persistence: a fresh extraction doesn't duplicate kept rows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reextract_keeps_a_renamed_asset_once_and_points_flows_at_it(test_db) -> None:
    model_id = await _make_model()
    await _extract(model_id, ("API", "DB"), [("API", "DB")], [("Internet", "API")])
    db_row = next(a for a in await crud.list_assets(model_id) if a["name"] == "DB")
    await crud.update_asset(db_row["id"], name="Postgres")

    await _extract(model_id, ("API", "DB", "Cache"), [("API", "DB")], [("Internet", "API")])

    assets = sorted(a["name"] for a in await crud.list_assets(model_id))
    assert assets == ["API", "Cache", "Postgres"]
    flows = [(f["source_entity"], f["target_entity"]) for f in await crud.list_flows(model_id)]
    assert flows == [("API", "Postgres")]
    renamed = next(a for a in await crud.list_assets(model_id) if a["name"] == "Postgres")
    assert renamed["id"] == db_row["id"]


@pytest.mark.asyncio
async def test_reextract_keeps_an_edited_flow_and_boundary_once(test_db) -> None:
    model_id = await _make_model()
    await _extract(model_id, ("API", "DB"), [("API", "DB")], [("Internet", "API")])
    flow = (await crud.list_flows(model_id))[0]
    boundary = (await crud.list_trust_boundaries(model_id))[0]
    await crud.update_flow(flow["id"], flow_description="SQL over TLS")
    await crud.update_trust_boundary(boundary["id"], purpose="WAF")

    await _extract(model_id, ("API", "DB"), [("api", "db")], [("Internet", "API")])

    flows = await crud.list_flows(model_id)
    boundaries = await crud.list_trust_boundaries(model_id)
    assert [(f["id"], f["flow_description"]) for f in flows] == [(flow["id"], "SQL over TLS")]
    assert [(b["id"], b["purpose"]) for b in boundaries] == [(boundary["id"], "WAF")]


@pytest.mark.asyncio
async def test_reextract_keeps_a_user_added_asset_once(test_db) -> None:
    model_id = await _make_model()
    await crud.create_asset(model_id, "Asset", "Queue", "", user_edited=True)

    await _extract(model_id, ("API", "Queue"), [])

    assert sorted(a["name"] for a in await crud.list_assets(model_id)) == ["API", "Queue"]


@pytest.mark.asyncio
async def test_a_first_extraction_saves_every_row_even_with_repeated_names(test_db) -> None:
    """Only rows the user kept suppress new ones; the pipeline's own output is saved as-is."""
    model_id = await _make_model()

    await _extract(model_id, ("API", "API"), [("API", "DB"), ("API", "DB")])

    assert len(await crud.list_assets(model_id)) == 2
    assert len(await crud.list_flows(model_id)) == 2


# ---------------------------------------------------------------------------
# Routes: the context endpoints mark what they write
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_routes_mark_rows_user_edited(test_db) -> None:
    from backend.models.api import (
        CreateAssetRequest,
        CreateFlowRequest,
        CreateTrustBoundaryRequest,
        UpdateAssetRequest,
    )

    model_id = await _make_model()
    generated = await crud.create_asset(model_id, "Asset", "DB", "")

    added = await models_routes.create_asset(
        model_id, CreateAssetRequest(type="Asset", name="Queue", description=""), _authz=None
    )
    await models_routes.update_asset(
        model_id, generated, UpdateAssetRequest(name="Postgres"), _authz=None
    )
    await models_routes.create_flow(
        model_id,
        CreateFlowRequest(
            flow_type="data", flow_description="q", source_entity="API", target_entity="Queue"
        ),
        _authz=None,
    )
    await models_routes.create_trust_boundary(
        model_id,
        CreateTrustBoundaryRequest(purpose="edge", source_entity="Internet", target_entity="API"),
        _authz=None,
    )

    assert added.status_code == 201
    assert all(a["user_edited"] == 1 for a in await crud.list_assets(model_id))
    assert (await crud.list_flows(model_id))[0]["user_edited"] == 1
    assert (await crud.list_trust_boundaries(model_id))[0]["user_edited"] == 1


@pytest.mark.asyncio
async def test_reextract_route_keeps_the_users_edit(test_db) -> None:
    """End to end through POST /{id}/extract with a fake extractor."""
    model_id = await _make_model()
    asset_id = await crud.create_asset(model_id, "Asset", "DB", "")
    await crud.update_asset(asset_id, name="Postgres")

    async def extractor(*args, **kwargs):
        yield _assets_event("API", "DB")

    with (
        patch("backend.routes.models.build_provider_from_record", return_value=MagicMock()),
        patch("backend.routes.models.build_fast_provider", return_value=None),
        patch("backend.routes.models.run_pipeline_for_model", extractor),
    ):
        resp = await models_routes.extract_model_context(model_id, _rate=None, _authz=None)
        await asyncio.wait_for(_consume(resp), timeout=5)
    await live_runs.cancel_all_runs()

    assets = {a["name"]: a["id"] for a in await crud.list_assets(model_id)}
    assert assets.keys() == {"API", "Postgres"}
    assert assets["Postgres"] == asset_id


async def _consume(resp) -> None:
    async for _ in resp.body_iterator:
        pass
