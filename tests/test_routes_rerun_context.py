"""Re-run reuses the model's stored context and dependency scans.

Results' Re-run (and Edit Context → Re-run) used to clear the model and
extract it again, so context edits were lost and, with no manifest sent, the
dependency analysis was gone (BB-82). A Re-run now seeds the pipeline with the
stored assets/flows/boundaries and the stored scans; Re-extract is the way to
regenerate the context.
"""

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest

from backend.db import crud
from backend.deps import analyze
from backend.models.dependencies import (
    DependencyContext,
    PackageAnalysis,
    PackageRef,
    ResolvedPackage,
)
from backend.pipeline import live_runs
from backend.pipeline.runner import PipelineEvent, PipelineStep
from backend.routes import models as models_routes
from tests.fixtures.pipeline import make_stride_threats


@pytest.fixture
async def model_id(test_db):
    return await crud.create_threat_model(
        title="Re-run",
        description="An API in front of a Postgres database.",
        provider="ollama",
        model="llama3.1:8b",
        framework="STRIDE",
        iteration_count=1,
    )


@pytest.fixture(autouse=True)
async def _no_leftover_runs(test_db):
    yield
    await live_runs.cancel_all_runs()


async def _open_run(model_id: str):
    return await models_routes.run_pipeline(
        model_id,
        assumptions="[]",
        has_ai_components="false",
        diagram=None,
        diagrams=None,
        diagram_names=None,
        code_source_id="",
        dependency_manifest=None,
        dependency_lockfile=None,
        deps_source_mode="npm",
        use_code_source_manifest=False,
        _rate=None,
        _authz=None,
    )


def _recording_runner(seen: dict):
    """Records its kwargs and behaves like the real runner with seeded input."""

    async def runner(*args, **kwargs):
        seen.update(kwargs)
        if kwargs.get("seeded_assets") is not None:
            yield PipelineEvent(
                step=PipelineStep.EXTRACT_ASSETS,
                status="completed",
                message="seeded",
                data={"assets": kwargs["seeded_assets"], "seeded": True},
            )
        if kwargs.get("seeded_flows") is not None:
            yield PipelineEvent(
                step=PipelineStep.EXTRACT_FLOWS,
                status="completed",
                message="seeded",
                data={"flows": kwargs["seeded_flows"], "seeded": True},
            )
        yield PipelineEvent(
            step=PipelineStep.COMPLETE,
            status="completed",
            message="done",
            data={
                "threats": make_stride_threats(),
                "dependency_context": kwargs.get("dependency_context"),
            },
        )

    return runner


async def _rerun(model_id: str) -> dict:
    seen: dict = {}
    with (
        patch("backend.routes.models.build_provider_from_record", return_value=MagicMock()),
        patch("backend.routes.models.build_fast_provider", return_value=None),
        patch("backend.routes.models.run_pipeline_for_model", _recording_runner(seen)),
    ):
        resp = await _open_run(model_id)
        await asyncio.wait_for(_drain(resp), timeout=5)
    return seen


async def _drain(resp) -> list[dict]:
    return [json.loads(c.removeprefix("data: ").strip()) async for c in resp.body_iterator]


async def _seed_context(model_id: str) -> dict[str, str]:
    ids = {
        "api": await crud.create_asset(model_id, "Asset", "API", ""),
        "db": await crud.create_asset(model_id, "Asset", "DB", ""),
        "flow": await crud.create_flow(model_id, "data", "queries", "API", "DB"),
        "boundary": await crud.create_trust_boundary(model_id, "edge", "Internet", "API"),
    }
    await crud.update_asset(ids["db"], name="Postgres", description="primary store")
    return ids


def _scanned_context() -> DependencyContext:
    pa = PackageAnalysis(
        ref=PackageRef(name="lodash", version="4.17.21"),
        resolved=ResolvedPackage(
            name="lodash",
            version="4.17.21",
            tarball_url="https://registry.npmjs.org/lodash/-/lodash-4.17.21.tgz",
            integrity="sha512-AAAA",
        ),
    )
    return DependencyContext(packages=[pa], skipped={"weird": "unresolvable"}, source_mode="npm")


async def _store_scans(model_id: str, context: DependencyContext) -> None:
    for package, version, analysis in analyze.dependency_scan_rows(context):
        await crud.create_dependency_scan(model_id, package, version, context.source_mode, analysis)


@pytest.mark.asyncio
async def test_rerun_seeds_the_stored_context_including_edits(model_id):
    await _seed_context(model_id)

    seen = await _rerun(model_id)

    assert [a.name for a in seen["seeded_assets"].assets] == ["API", "Postgres"]
    assert seen["seeded_assets"].assets[1].description == "primary store"
    flows = seen["seeded_flows"]
    assert [(f.source_entity, f.target_entity) for f in flows.data_flows] == [("API", "DB")]
    assert [b.purpose for b in flows.trust_boundaries] == ["edge"]


@pytest.mark.asyncio
async def test_rerun_keeps_the_context_rows_and_replaces_only_the_threats(model_id):
    ids = await _seed_context(model_id)
    await _rerun(model_id)
    first_threats = {t["id"] for t in await crud.list_threats(model_id)}

    await _rerun(model_id)

    assets = await crud.list_assets(model_id)
    assert sorted(a["id"] for a in assets) == sorted([ids["api"], ids["db"]])
    assert [f["id"] for f in await crud.list_flows(model_id)] == [ids["flow"]]
    assert [b["id"] for b in await crud.list_trust_boundaries(model_id)] == [ids["boundary"]]
    threats = {t["id"] for t in await crud.list_threats(model_id)}
    assert len(threats) == len(make_stride_threats().threats)
    assert threats.isdisjoint(first_threats)


@pytest.mark.asyncio
async def test_a_first_run_extracts_as_usual(model_id):
    seen = await _rerun(model_id)

    assert seen["seeded_assets"] is None
    assert seen["seeded_flows"] is None


@pytest.mark.asyncio
async def test_assets_without_flows_seed_assets_only(model_id):
    await crud.create_asset(model_id, "Asset", "API", "")

    seen = await _rerun(model_id)

    assert [a.name for a in seen["seeded_assets"].assets] == ["API"]
    assert seen["seeded_flows"] is None


@pytest.mark.asyncio
async def test_rerun_without_a_manifest_reuses_the_stored_scans(model_id):
    """BB-82: the Dependencies section was empty after every Re-run."""
    context = _scanned_context()
    await _store_scans(model_id, context)
    before = sorted((s["package"], s["id"]) for s in await crud.list_dependency_scans(model_id))

    seen = await _rerun(model_id)

    reused = seen["dependency_context"]
    assert [pa.ref.name for pa in reused.packages] == ["lodash"]
    assert reused.skipped == {"weird": "unresolvable"}
    after = sorted((s["package"], s["id"]) for s in await crud.list_dependency_scans(model_id))
    assert after == before


@pytest.mark.asyncio
async def test_rerun_says_it_reused_the_dependency_analysis(model_id):
    await _store_scans(model_id, _scanned_context())
    with (
        patch("backend.routes.models.build_provider_from_record", return_value=MagicMock()),
        patch("backend.routes.models.build_fast_provider", return_value=None),
        patch("backend.routes.models.run_pipeline_for_model", _recording_runner({})),
    ):
        events = await asyncio.wait_for(_drain(await _open_run(model_id)), timeout=5)

    info = [e for e in events if e["step"] == "analyze_dependencies"]
    assert len(info) == 1
    assert "Reusing the last run's dependency analysis" in info[0]["message"]


@pytest.mark.asyncio
async def test_a_model_without_scans_gets_no_dependency_context(model_id):
    seen = await _rerun(model_id)

    assert seen["dependency_context"] is None


@pytest.mark.asyncio
async def test_unparseable_stored_scans_are_not_reused(model_id):
    await crud.create_dependency_scan(model_id, "broken", "1.0.0", "npm", {"ref": "not-an-object"})

    seen = await _rerun(model_id)

    assert seen["dependency_context"] is None
    assert await crud.list_dependency_scans(model_id) == []
