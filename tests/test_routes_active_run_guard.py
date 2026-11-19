"""BB-129: threat and context edits are refused while the model has a run in progress.

A run clears and rewrites the model's threats and context, so an edit made
meanwhile was lost or hit a row about to go (Approve returned 404).
"""

import pytest
from httpx import ASGITransport, AsyncClient

from backend.db import crud, crud_live_runs
from backend.main import app


@pytest.fixture
async def client(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def seeded(test_db) -> dict[str, str]:
    model_id = await crud.create_threat_model(
        title="Guarded",
        description="An API in front of a Postgres database.",
        provider="anthropic",
        model="claude-sonnet-4",
    )
    threat_id = await crud.create_threat(
        model_id=model_id,
        name="SQL injection",
        description="Unsanitised input reaches the database.",
        target="API",
        impact="High",
        likelihood="Medium",
        mitigations=["Parameterised queries"],
        stride_category="Tampering",
    )
    asset_id = await crud.create_asset(model_id, "Asset", "Database", "Postgres")
    flow_id = await crud.create_flow(model_id, "data", "Queries", "API", "Database")
    boundary_id = await crud.create_trust_boundary(model_id, "Network edge", "Internet", "API")
    return {
        "model": model_id,
        "threat": threat_id,
        "asset": asset_id,
        "flow": flow_id,
        "boundary": boundary_id,
    }


# (method, path template, JSON body) for every route the guard covers.
_MUTATIONS = [
    ("PATCH", "/api/threats/{threat}", {"status": "approved"}),
    ("POST", "/api/threats/bulk-status", "bulk"),
    ("DELETE", "/api/threats/{threat}", None),
    ("POST", "/api/threats/{threat}/attack-tree", None),
    ("POST", "/api/threats/{threat}/test-cases", None),
    ("POST", "/api/models/{model}/assets", {"name": "Cache", "type": "Asset"}),
    ("PATCH", "/api/models/{model}/assets/{asset}", {"name": "Primary DB"}),
    ("DELETE", "/api/models/{model}/assets/{asset}", None),
    (
        "POST",
        "/api/models/{model}/flows",
        {"source_entity": "API", "target_entity": "Cache", "flow_type": "data"},
    ),
    ("PATCH", "/api/models/{model}/flows/{flow}", {"flow_description": "Reads"}),
    ("DELETE", "/api/models/{model}/flows/{flow}", None),
    (
        "POST",
        "/api/models/{model}/trust-boundaries",
        {"source_entity": "API", "target_entity": "Cache", "purpose": "Internal"},
    ),
    ("PATCH", "/api/models/{model}/trust-boundaries/{boundary}", {"purpose": "Edge"}),
    ("DELETE", "/api/models/{model}/trust-boundaries/{boundary}", None),
]


async def _send(client: AsyncClient, method: str, path: str, body, ids: dict[str, str]):
    if body == "bulk":
        body = {"threat_ids": [ids["threat"]], "status": "approved"}
    return await client.request(method, path.format(**ids), json=body)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "body"), _MUTATIONS, ids=[f"{m} {p}" for m, p, _ in _MUTATIONS]
)
async def test_a_mutation_during_a_run_is_refused_and_changes_nothing(
    client, seeded, method, path, body
):
    run_id = await crud_live_runs.claim_run("model", seeded["model"], "run")

    r = await _send(client, method, path, body, seeded)

    assert r.status_code == 409, r.text
    assert "re-run" in r.json()["detail"]
    assert (await crud.get_threat(seeded["threat"]))["status"] == "pending"
    assert (await crud.get_asset(seeded["asset"]))["name"] == "Database"
    assert len(await crud.list_assets(seeded["model"])) == 1
    assert await crud.get_flow(seeded["flow"]) is not None
    assert await crud.get_trust_boundary(seeded["boundary"]) is not None
    await crud_live_runs.finish_run(run_id, "completed")


@pytest.mark.asyncio
async def test_an_extraction_in_progress_says_so(client, seeded):
    run_id = await crud_live_runs.claim_run("model", seeded["model"], "extract")

    r = await client.patch(f"/api/models/{seeded['model']}/assets/{seeded['asset']}", json={})

    assert r.status_code == 409
    assert "extraction" in r.json()["detail"]
    await crud_live_runs.finish_run(run_id, "completed")


@pytest.mark.asyncio
async def test_edits_are_accepted_again_once_the_run_ends(client, seeded):
    run_id = await crud_live_runs.claim_run("model", seeded["model"], "run")
    await crud_live_runs.finish_run(run_id, "completed")

    r = await client.patch(f"/api/threats/{seeded['threat']}", json={"status": "approved"})
    asset = await client.patch(
        f"/api/models/{seeded['model']}/assets/{seeded['asset']}", json={"name": "Primary DB"}
    )

    assert r.status_code == 200
    assert asset.status_code == 200


@pytest.mark.asyncio
async def test_another_models_run_does_not_block_this_one(client, seeded):
    other = await crud.create_threat_model(
        title="Other", description="x", provider="anthropic", model="claude-sonnet-4"
    )
    run_id = await crud_live_runs.claim_run("model", other, "run")

    r = await client.patch(f"/api/threats/{seeded['threat']}", json={"status": "approved"})

    assert r.status_code == 200
    await crud_live_runs.finish_run(run_id, "completed")


@pytest.mark.asyncio
async def test_the_active_run_endpoint_reports_the_run_then_null(client, seeded):
    url = f"/api/models/{seeded['model']}/active-run"
    assert (await client.get(url)).json() == {"active_run": None}

    run_id = await crud_live_runs.claim_run("model", seeded["model"], "extract")
    during = (await client.get(url)).json()["active_run"]
    await crud_live_runs.finish_run(run_id, "completed")

    assert during["kind"] == "extract"
    assert during["started_at"]
    assert (await client.get(url)).json() == {"active_run": None}


@pytest.mark.asyncio
async def test_the_active_run_endpoint_404s_for_a_missing_model(client, test_db):
    r = await client.get("/api/models/00000000000000000000000000000000/active-run")
    assert r.status_code == 404
