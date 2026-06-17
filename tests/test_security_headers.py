"""Tests for SecurityHeadersMiddleware.

Verifies that all five defensive headers are present on both success and
error responses, and that the middleware does not duplicate existing headers.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.security.headers import SecurityHeadersMiddleware


@pytest.fixture
def client():
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    return TestClient(app, raise_server_exceptions=False)


def test_x_content_type_options(client):
    r = client.get("/ping")
    assert r.headers.get("x-content-type-options") == "nosniff"


def test_x_frame_options(client):
    r = client.get("/ping")
    assert r.headers.get("x-frame-options") == "DENY"


def test_referrer_policy(client):
    r = client.get("/ping")
    assert r.headers.get("referrer-policy") == "strict-origin-when-cross-origin"


def test_permissions_policy(client):
    r = client.get("/ping")
    assert r.headers.get("permissions-policy") == "geolocation=(), camera=(), microphone=()"


def test_content_security_policy(client):
    r = client.get("/ping")
    csp = r.headers.get("content-security-policy", "")
    # Core XSS guard — must block inline scripts.
    assert "script-src 'self'" in csp
    # Required by Svelte scoped styles and Mermaid SVG output; removing it
    # would break all CSS styling and attack-tree renders in the browser.
    assert "style-src 'self' 'unsafe-inline'" in csp
    # Required for base64 diagram embeds and Blob URLs (architecture diagrams).
    assert "img-src 'self' data: blob:" in csp
    # Locks down plugin embeds and base URL hijacking.
    assert "object-src 'none'" in csp
    assert "base-uri 'self'" in csp
    # Modern framing guard (complements X-Frame-Options for newer browsers).
    assert "frame-ancestors 'none'" in csp


def test_headers_on_404(client):
    """Security headers must appear on error responses too."""
    r = client.get("/not-found")
    assert r.status_code == 404
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"
    assert r.headers.get("referrer-policy") == "strict-origin-when-cross-origin"
    assert "script-src 'self'" in r.headers.get("content-security-policy", "")


def test_no_duplicate_headers(client):
    """Middleware must not inject a header that already exists in the response."""
    from starlette.responses import Response
    from starlette.testclient import TestClient as StarletteClient

    app2 = FastAPI()
    app2.add_middleware(SecurityHeadersMiddleware)

    @app2.get("/already-set")
    async def already_set():
        return Response(
            content="ok",
            headers={"x-frame-options": "SAMEORIGIN"},
        )

    c2 = StarletteClient(app2)
    r = c2.get("/already-set")
    # The pre-existing value must be preserved; no second entry added.
    values = [v for k, v in r.headers.items() if k.lower() == "x-frame-options"]
    assert len(values) == 1
    assert values[0] == "SAMEORIGIN"
