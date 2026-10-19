"""Instance settings reaching a web run (bug-bash plan §5.6, run order item 25).

POST /api/models/{id}/run with the pipeline replaced by a capturing no-op, to
check which configured values the route passes on.
"""

from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.config import settings
from backend.db import crud
from backend.main import app


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    reason=(
        "Bug-bash finding (item 25, carried from review): the web run route never passes "
        "similarity_threshold, so web runs always dedupe at the 0.85 default; "
        "SIMILARITY_THRESHOLD and the Settings PATCH only reach CLI runs."
    ),
)
async def test_web_run_uses_the_configured_similarity_threshold(test_db, monkeypatch):
    monkeypatch.setattr(settings, "similarity_threshold", 0.6)
    model_id = await crud.create_threat_model(
        title="t",
        description="A web API with a Postgres database.",
        provider="ollama",
        model="llama3.1:8b",
        framework="STRIDE",
        iteration_count=1,
    )
    captured: dict = {}

    async def capturing_runner(*args, **kwargs):
        captured.update(kwargs)
        return
        yield  # pragma: no cover - makes this an async generator

    with (
        patch("backend.routes.models.build_provider_from_record", return_value=MagicMock()),
        patch("backend.routes.models.build_fast_provider", return_value=None),
        patch("backend.routes.models.run_pipeline_for_model", capturing_runner),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(f"/api/models/{model_id}/run", data={"assumptions": "[]"})
    assert r.status_code == 200
    assert captured.get("similarity_threshold", 0.85) == 0.6
