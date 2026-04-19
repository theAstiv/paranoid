"""CSRF middleware behaviour — Origin/Referer allowlist for mutating methods."""

import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app
from backend.security.csrf import CSRFMiddleware, parse_allowed_origins


@pytest.fixture
async def client(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def test_parse_allowed_origins_rejects_wildcard():
    with pytest.raises(ValueError, match="ALLOWED_ORIGINS"):
        parse_allowed_origins("http://localhost:8000,*")


def test_parse_allowed_origins_rejects_bare_host():
    """Entries must include a scheme — 'example.com' alone is not an origin."""
    with pytest.raises(ValueError, match="not a valid origin"):
        parse_allowed_origins("example.com")


def test_parse_allowed_origins_empty_string_disables():
    assert parse_allowed_origins("") == []
    assert parse_allowed_origins("   ") == []


def test_parse_allowed_origins_normalises():
    assert parse_allowed_origins("http://localhost:8000,https://app.example.com/ignored-path") == [
        "http://localhost:8000",
        "https://app.example.com",
    ]


@pytest.mark.asyncio
async def test_csrf_rejects_evil_origin_on_patch(client):
    resp = await client.patch(
        "/api/config/",
        json={"default_iterations": 2},
        headers={"Origin": "https://evil.example"},
    )
    assert resp.status_code == 403
    assert "ALLOWED_ORIGINS" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_csrf_allows_matching_origin(client):
    resp = await client.patch(
        "/api/config/",
        json={"default_iterations": 2},
        headers={"Origin": "http://localhost:8000"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_csrf_allows_no_origin_header(client):
    """CLI / server-to-server calls with no Origin header pass through."""
    resp = await client.patch("/api/config/", json={"default_iterations": 2})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_csrf_allows_safe_methods_with_evil_origin(client):
    resp = await client.get("/api/config/", headers={"Origin": "https://evil.example"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_csrf_rejects_evil_referer_when_no_origin(client):
    resp = await client.patch(
        "/api/config/",
        json={"default_iterations": 2},
        headers={"Referer": "https://evil.example/page"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_csrf_asgi_passes_through_multiple_body_chunks():
    """Pure-ASGI CSRF must forward each response-body chunk as it arrives
    rather than buffer the stream. Regression guard against reintroducing
    ``BaseHTTPMiddleware``, which breaks pipeline SSE.
    """
    received: list[dict] = []

    async def inner_app(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/event-stream")],
            }
        )
        await send({"type": "http.response.body", "body": b"a", "more_body": True})
        await send({"type": "http.response.body", "body": b"b", "more_body": True})
        await send({"type": "http.response.body", "body": b"c", "more_body": False})

    middleware = CSRFMiddleware(inner_app, allowed_origins=["http://localhost:8000"])

    scope = {"type": "http", "method": "GET", "path": "/stream", "headers": []}

    async def send(msg):
        received.append(msg)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    await middleware(scope, receive, send)

    body_chunks = [m for m in received if m["type"] == "http.response.body"]
    assert [m["body"] for m in body_chunks] == [b"a", b"b", b"c"]
    assert body_chunks[0].get("more_body") is True
    assert body_chunks[-1].get("more_body") is False


@pytest.mark.asyncio
async def test_csrf_empty_allowlist_disables_check(test_db, monkeypatch):
    """Constructing the middleware with an empty list lets everything through."""
    from fastapi import FastAPI

    app2 = FastAPI()
    app2.add_middleware(CSRFMiddleware, allowed_origins=[])

    @app2.post("/echo")
    async def echo():
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app2), base_url="http://test") as c:
        resp = await c.post("/echo", headers={"Origin": "https://evil.example"})
        assert resp.status_code == 200
