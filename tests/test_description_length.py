"""BB-126: a system description is capped at 50,000 characters everywhere.

2 MB used to be accepted, stored, and sent to the LLM on every pipeline step.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app
from backend.models.api import MAX_DESCRIPTION_CHARS
from cli.errors import InputFileError
from cli.input.file_loader import load_input_file


def _text(length: int) -> str:
    return ("An API stores records. " * (length // 23 + 1))[:length]


@pytest.fixture
async def client(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def _create_body(description: str) -> dict:
    return {"title": "Length", "description": description, "provider": "ollama"}


@pytest.mark.asyncio
async def test_create_accepts_the_limit_and_refuses_one_more(client):
    ok = await client.post("/api/models/", json=_create_body(_text(MAX_DESCRIPTION_CHARS)))
    too_long = await client.post(
        "/api/models/", json=_create_body(_text(MAX_DESCRIPTION_CHARS + 1))
    )

    assert ok.status_code == 201, ok.text
    assert too_long.status_code == 422
    assert "50000" in too_long.text


@pytest.mark.asyncio
async def test_update_refuses_an_over_long_description(client):
    created = (await client.post("/api/models/", json=_create_body(_text(100)))).json()

    too_long = await client.patch(
        f"/api/models/{created['id']}", json={"description": _text(MAX_DESCRIPTION_CHARS + 1)}
    )
    ok = await client.patch(
        f"/api/models/{created['id']}", json={"description": _text(MAX_DESCRIPTION_CHARS)}
    )

    assert too_long.status_code == 422
    assert ok.status_code == 200


def test_the_cli_refuses_an_over_long_input_file(tmp_path):
    path = tmp_path / "system.md"
    path.write_text(_text(MAX_DESCRIPTION_CHARS + 1), encoding="utf-8")

    with pytest.raises(InputFileError, match=r"50,001 characters \(max: 50,000\)"):
        load_input_file(path)


def test_the_cli_accepts_an_input_file_at_the_limit(tmp_path):
    path = tmp_path / "system.md"
    path.write_text(_text(MAX_DESCRIPTION_CHARS), encoding="utf-8")

    assert len(load_input_file(path)) == MAX_DESCRIPTION_CHARS


def test_the_cli_counts_characters_not_bytes(tmp_path):
    """A non-ASCII description of 50,000 characters is over 50,000 bytes and still fine."""
    path = tmp_path / "system.md"
    path.write_text("é" * MAX_DESCRIPTION_CHARS, encoding="utf-8")

    assert len(load_input_file(path)) == MAX_DESCRIPTION_CHARS
