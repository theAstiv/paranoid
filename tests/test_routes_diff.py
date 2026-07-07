"""Tests for GET /api/models/{head_id}/diff.

Validates input guards (same-id, non-completed status, not-found) and the
happy-path structure of the diff response. The embedding path is bypassed
via mock so no fastembed dependency is required.
"""

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.db import crud
from backend.main import app


@pytest.fixture
async def client(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _completed_model(title: str) -> str:
    model_id = await crud.create_threat_model(
        title=title,
        description="test description for diff route",
        provider="anthropic",
        model="claude-sonnet-4",
    )
    await crud.update_threat_model_status(model_id, "completed")
    return model_id


async def _pending_model(title: str) -> str:
    return await crud.create_threat_model(
        title=title,
        description="test description for diff route",
        provider="anthropic",
        model="claude-sonnet-4",
    )


# ---------------------------------------------------------------------------
# Input validation guards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_diff_same_id_returns_400(client):
    model_id = await _completed_model("Same Model")
    resp = await client.get(f"/api/models/{model_id}/diff?base_id={model_id}")
    assert resp.status_code == 400
    assert "different" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_diff_head_not_found_returns_404(client):
    base_id = await _completed_model("Base")
    resp = await client.get(f"/api/models/nonexistent-head/diff?base_id={base_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_diff_base_not_found_returns_404(client):
    head_id = await _completed_model("Head")
    resp = await client.get(f"/api/models/{head_id}/diff?base_id=nonexistent-base")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_diff_head_not_completed_returns_400(client):
    head_id = await _pending_model("Pending Head")
    base_id = await _completed_model("Completed Base")
    resp = await client.get(f"/api/models/{head_id}/diff?base_id={base_id}")
    assert resp.status_code == 400
    assert "not completed" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_diff_base_not_completed_returns_400(client):
    head_id = await _completed_model("Completed Head")
    base_id = await _pending_model("Pending Base")
    resp = await client.get(f"/api/models/{head_id}/diff?base_id={base_id}")
    assert resp.status_code == 400
    assert "not completed" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_diff_happy_path_response_shape(client):
    head_id = await _completed_model("Head")
    base_id = await _completed_model("Base")

    def fake_embed(text: str) -> list[float]:
        vec = [0.0] * 16
        vec[hash(text) % 16] = 1.0
        return vec

    with patch("backend.db.crud_diff.embed_text", side_effect=fake_embed):
        resp = await client.get(f"/api/models/{head_id}/diff?base_id={base_id}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["head_model_id"] == head_id
    assert data["base_model_id"] == base_id
    assert "summary" in data
    assert "threats" in data
    s = data["summary"]
    assert all(
        k in s for k in ("base_count", "head_count", "added", "removed", "changed", "unchanged")
    )
