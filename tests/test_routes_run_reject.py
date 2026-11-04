"""A wizard run the server rejects doesn't leave an empty model behind (BB-122).

The wizard creates the model, then posts its first run. A run rejected for its
uploads (bad diagram, bad manifest, ...) used to leave a pending, empty model.
With discard_model_on_reject=true the route deletes it again, but only a
model that never held data, and only when the caller asked.
"""

from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.db import crud
from backend.main import app
from backend.models.enums import ModelStatus


_DISCARD = {"assumptions": "[]", "has_ai_components": "false", "discard_model_on_reject": "true"}
_BAD_DIAGRAM = {"diagrams": ("broken.png", b"not a real png", "image/png")}


@pytest.fixture
async def client(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def model_id(test_db):
    return await crud.create_threat_model(
        title="Wizard",
        description="A freshly created model whose first run is rejected.",
        provider="anthropic",
        model="claude-sonnet-4",
        framework="STRIDE",
        iteration_count=1,
    )


def _providers():
    return (
        patch("backend.routes.models.build_provider_from_record", return_value=MagicMock()),
        patch("backend.routes.models.build_fast_provider", return_value=None),
    )


@pytest.mark.asyncio
async def test_a_rejected_first_run_discards_the_model(client, model_id):
    resp = await client.post(f"/api/models/{model_id}/run", data=_DISCARD, files=_BAD_DIAGRAM)

    assert resp.status_code == 422
    assert await crud.get_threat_model(model_id) is None


@pytest.mark.asyncio
async def test_bad_assumptions_and_a_lockfile_alone_discard_it_too(client, test_db):
    for data, files in (
        ({**_DISCARD, "assumptions": "not json"}, None),
        (_DISCARD, {"dependency_lockfile": ("package-lock.json", b"{}", "application/json")}),
    ):
        mid = await crud.create_threat_model(
            title="W", description="d" * 20, provider="anthropic", model="m", framework="STRIDE"
        )
        resp = await client.post(f"/api/models/{mid}/run", data=data, files=files)
        assert resp.status_code == 422
        assert await crud.get_threat_model(mid) is None


@pytest.mark.asyncio
async def test_without_the_flag_a_rejected_run_keeps_the_model(client, model_id):
    """An API or CLI caller that created the model itself keeps it."""
    form = {k: v for k, v in _DISCARD.items() if k != "discard_model_on_reject"}

    resp = await client.post(f"/api/models/{model_id}/run", data=form, files=_BAD_DIAGRAM)

    assert resp.status_code == 422
    assert await crud.get_threat_model(model_id) is not None


@pytest.mark.asyncio
async def test_a_model_that_holds_data_is_never_discarded(client, model_id):
    """E.g. a model extracted first (assets, still 'pending') or one that already ran."""
    await crud.create_asset(model_id, "Asset", "API", "")

    resp = await client.post(f"/api/models/{model_id}/run", data=_DISCARD, files=_BAD_DIAGRAM)

    assert resp.status_code == 422
    assert await crud.get_threat_model(model_id) is not None


@pytest.mark.asyncio
async def test_a_model_that_already_ran_is_never_discarded(client, model_id):
    await crud.update_threat_model_status(model_id, ModelStatus.FAILED.value)

    resp = await client.post(f"/api/models/{model_id}/run", data=_DISCARD, files=_BAD_DIAGRAM)

    assert resp.status_code == 422
    assert await crud.get_threat_model(model_id) is not None


@pytest.mark.asyncio
async def test_an_accepted_run_keeps_the_model(client, model_id):
    async def runner(*args, **kwargs):
        return
        yield  # pragma: no cover - makes this an async generator

    p1, p2 = _providers()
    with p1, p2, patch("backend.routes.models.run_pipeline_for_model", runner):
        resp = await client.post(f"/api/models/{model_id}/run", data=_DISCARD)

    assert resp.status_code == 200
    assert await crud.get_threat_model(model_id) is not None


@pytest.mark.asyncio
async def test_delete_unrun_threat_model_checks_every_condition(test_db):
    async def fresh() -> str:
        return await crud.create_threat_model(
            title="W", description="d" * 20, provider="anthropic", model="m", framework="STRIDE"
        )

    empty = await fresh()
    with_threat = await fresh()
    await crud.create_threat(
        model_id=with_threat,
        name="T",
        description="x" * 60,
        target="API",
        impact="High",
        likelihood="Medium",
        mitigations=["Fix"],
        stride_category="Tampering",
    )

    assert await crud.delete_unrun_threat_model(empty) is True
    assert await crud.delete_unrun_threat_model(with_threat) is False
    assert await crud.get_threat_model(with_threat) is not None
