"""CSRF middleware — Origin/Referer allowlist for mutating methods.

Rationale: the app has no user auth in v1. The moment ``PATCH /api/config``
accepts API keys, an attacker-controlled webpage the user has open in
another tab can issue a cross-origin fetch that redirects the user's traffic
to an attacker-owned key. CORS alone does not help — ``CORS_ORIGINS="*"`` is
fine for a self-hosted tool but useless as a CSRF allowlist.

Behaviour:
- GET/HEAD/OPTIONS pass through unconditionally (safe methods).
- Mutating methods with no Origin and no Referer pass through — covers CLI,
  curl, and server-to-server callers. Browsers always send Origin on
  cross-origin fetch, so the false-negative surface is narrow.
- Mutating methods with an Origin or Referer: scheme+authority must match
  one of ``ALLOWED_ORIGINS``. Otherwise 403.
- Empty allowlist disables the check entirely (opt-in escape hatch).

This is implemented as pure ASGI (not ``BaseHTTPMiddleware``) because the
latter buffers response bodies, which breaks the pipeline SSE stream.
"""

import json
import logging
from urllib.parse import urlparse


logger = logging.getLogger(__name__)

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def parse_allowed_origins(raw: str) -> list[str]:
    """Parse and validate ``ALLOWED_ORIGINS``.

    Returns a list of normalised origins (``scheme://host[:port]``).
    Empty list means CSRF is disabled. Raises ``ValueError`` on ``*``.
    """
    items = [o.strip() for o in raw.split(",") if o.strip()]
    if "*" in items:
        raise ValueError(
            "ALLOWED_ORIGINS must be concrete origins, not '*'. If you want "
            "no CSRF protection, set ALLOWED_ORIGINS= (empty) and understand "
            "the risk."
        )
    normalised = []
    for item in items:
        parsed = urlparse(item)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError(
                f"ALLOWED_ORIGINS entry {item!r} is not a valid origin "
                "(expected scheme://host[:port])"
            )
        normalised.append(f"{parsed.scheme}://{parsed.netloc}")
    return normalised


def _origin_of(header_value: str) -> str | None:
    parsed = urlparse(header_value)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


class CSRFMiddleware:
    """Pure-ASGI middleware that rejects mutating requests whose Origin /
    Referer is not in the allowlist.

    Implemented at the raw ASGI layer because ``BaseHTTPMiddleware`` buffers
    response bodies and breaks the pipeline's SSE stream.
    """

    def __init__(self, app, allowed_origins: list[str]) -> None:
        self.app = app
        self._allowed = frozenset(allowed_origins)

    async def __call__(self, scope, receive, send) -> None:
        # Only HTTP. Lifespan and websocket scopes are passed through
        # verbatim — the app ships no mutating websocket routes today. If
        # one is added later, extend the origin check to ``"websocket"``
        # scopes too (the ASGI spec puts the Origin header in the same
        # ``scope["headers"]`` shape).
        if scope["type"] != "http" or not self._allowed:
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        if method in SAFE_METHODS:
            await self.app(scope, receive, send)
            return

        origin: str | None = None
        referer: str | None = None
        for raw_name, raw_value in scope.get("headers", ()):
            name = raw_name.decode("latin-1").lower()
            if name == "origin":
                origin = raw_value.decode("latin-1")
            elif name == "referer":
                referer = raw_value.decode("latin-1")

        # CLI / server-to-server callers omit both headers — let them through.
        if not origin and not referer:
            await self.app(scope, receive, send)
            return

        for header_value in (origin, referer):
            if not header_value:
                continue
            normalised = _origin_of(header_value)
            if normalised and normalised in self._allowed:
                await self.app(scope, receive, send)
                return

        logger.warning(
            "CSRF reject: method=%s origin=%r referer=%r path=%s",
            method,
            origin,
            referer,
            scope.get("path"),
        )
        body = json.dumps(
            {
                "detail": (
                    "Request origin is not permitted. See the ALLOWED_ORIGINS environment variable."
                )
            }
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
