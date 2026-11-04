"""PATCH /api/projects/{id} validates the pipeline defaults and can reset them (BB-132).

It accepted provider "bogus" and a temperature up to 2, and a null was
dropped (exclude_none), so an override could never be reset to "inherit".
"""

import pytest
from httpx import ASGITransport, AsyncClient

from backend.db import crud_projects
from backend.main import app


PROJECT = crud_projects.DEFAULT_PROJECT_ID


@pytest.fixture
async def client(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _patch(client, body: dict):
    return await client.patch(f"/api/projects/{PROJECT}", json=body)


@pytest.mark.asyncio
async def test_null_resets_an_override_to_inherit(client):
    await _patch(client, {"default_provider": "openai", "default_temperature": 0.5})

    res = await _patch(client, {"default_provider": None, "default_temperature": None})

    assert res.status_code == 200
    project = await crud_projects.get_project(PROJECT)
    assert project["default_provider"] is None
    assert project["default_temperature"] is None


@pytest.mark.asyncio
async def test_fields_not_sent_are_left_alone(client):
    await _patch(client, {"default_provider": "openai", "default_iterations": 4})

    await _patch(client, {"default_iterations": 6})

    project = await crud_projects.get_project(PROJECT)
    assert (project["default_provider"], project["default_iterations"]) == ("openai", 6)


@pytest.mark.asyncio
async def test_a_blank_model_means_inherit(client):
    await _patch(client, {"default_model": "gpt-4.1"})

    await _patch(client, {"default_model": "  "})

    assert (await crud_projects.get_project(PROJECT))["default_model"] is None


@pytest.mark.parametrize(
    "body",
    [
        {"default_provider": "bogus"},
        {"default_temperature": 1.5},
        {"default_iterations": 0},
        {"name": None},
        {"staleness_threshold_days": None},
    ],
)
@pytest.mark.asyncio
async def test_invalid_values_are_rejected(client, body):
    res = await _patch(client, body)

    assert res.status_code == 422


@pytest.mark.asyncio
async def test_the_provider_is_stored_as_its_name(client):
    await _patch(client, {"default_provider": "bedrock"})

    assert (await crud_projects.get_project(PROJECT))["default_provider"] == "bedrock"
