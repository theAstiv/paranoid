"""CORS options — a wildcard origin never comes with credentials (review S5)."""

import logging

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from httpx import ASGITransport, AsyncClient

from backend.security.cors import parse_cors_origins


_EVIL = "https://evil.example"


def test_wildcard_drops_credentials():
    assert parse_cors_origins("*") == (["*"], False)


def test_concrete_origins_keep_credentials():
    assert parse_cors_origins(" https://a.example , https://b.example ") == (
        ["https://a.example", "https://b.example"],
        True,
    )


def test_wildcard_mixed_with_origins_is_a_wildcard_and_warns(caplog):
    with caplog.at_level(logging.WARNING, logger="backend.security.cors"):
        assert parse_cors_origins("https://a.example,*") == (["*"], False)
    assert "CORS_ORIGINS" in caplog.text


def test_empty_allows_no_cross_origin_requests():
    assert parse_cors_origins("") == ([], True)


@pytest.mark.asyncio
async def test_default_app_does_not_reflect_origin_with_credentials(test_db):
    """The shipped default (CORS_ORIGINS=*) used to echo any Origin back with
    Access-Control-Allow-Credentials: true."""
    from backend.config import settings
    from backend.main import app

    if parse_cors_origins(settings.cors_origins)[0] != ["*"]:
        pytest.skip("CORS_ORIGINS is overridden in this environment")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/health", headers={"Origin": _EVIL})
        preflight = await c.options(
            "/api/config/",
            headers={"Origin": _EVIL, "Access-Control-Request-Method": "PATCH"},
        )

    assert resp.headers.get("access-control-allow-origin") == "*"
    assert "access-control-allow-credentials" not in resp.headers
    assert preflight.headers.get("access-control-allow-origin") == "*"
    assert "access-control-allow-credentials" not in preflight.headers


@pytest.mark.asyncio
async def test_concrete_origin_list_allows_credentials_only_for_its_origins():
    origins, credentials = parse_cors_origins("https://app.example")
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/echo")
    async def echo():
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        ours = await c.get("/echo", headers={"Origin": "https://app.example"})
        theirs = await c.get("/echo", headers={"Origin": _EVIL})

    assert ours.headers["access-control-allow-origin"] == "https://app.example"
    assert ours.headers["access-control-allow-credentials"] == "true"
    # Starlette still sends Allow-Credentials here; without Allow-Origin the
    # browser withholds the response anyway.
    assert "access-control-allow-origin" not in theirs.headers
