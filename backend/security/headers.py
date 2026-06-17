"""ASGI middleware that injects security-related HTTP response headers.

Adds five defensive headers to every response:
- X-Content-Type-Options: nosniff          — prevents MIME-type sniffing
- X-Frame-Options: DENY                    — blocks framing (clickjacking guard)
- Referrer-Policy: strict-origin-when-cross-origin — limits referrer leakage
- Permissions-Policy: geolocation=(), camera=(), microphone=()
                                           — opts out of browser APIs we never use
- Content-Security-Policy                  — restricts script execution origin;
                                             blocks inline script injection (stored XSS)

CSP notes:
- script-src 'self'       blocks inline <script> and eval — the key XSS guard
- style-src 'unsafe-inline' required for Svelte scoped styles and Mermaid SVG output
- img-src data: blob:     needed for base64 diagram embeds and Blob URLs
- frame-ancestors 'none'  supersedes X-Frame-Options in modern browsers
"""

from starlette.types import ASGIApp, Receive, Scope, Send


_CSP = (
    b"default-src 'self'; "
    b"script-src 'self'; "
    b"style-src 'self' 'unsafe-inline'; "
    b"img-src 'self' data: blob:; "
    b"connect-src 'self'; "
    b"font-src 'self'; "
    b"object-src 'none'; "
    b"base-uri 'self'; "
    b"frame-ancestors 'none'"
)


class SecurityHeadersMiddleware:
    """ASGI middleware that injects security response headers on every reply."""

    _HEADERS: list[tuple[bytes, bytes]] = [
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"referrer-policy", b"strict-origin-when-cross-origin"),
        (b"permissions-policy", b"geolocation=(), camera=(), microphone=()"),
        (b"content-security-policy", _CSP),
    ]

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: dict) -> None:
            if message["type"] == "http.response.start":
                # Assign once — reused for both the set comprehension and the copy.
                raw = list(message.get("headers", []))
                existing_names = {h[0].lower() for h in raw}
                extra = [
                    (name, value) for name, value in self._HEADERS if name not in existing_names
                ]
                if extra:
                    message = {**message, "headers": raw + extra}
            await send(message)

        await self.app(scope, receive, send_with_headers)
