"""Per-provider liveness probes for the Settings "Test connection" button.

Each probe returns a small structured result instead of raising — callers
(the ``/api/config/test-provider`` route) surface the outcome to the UI as
a 200 response with ``ok: false`` + a stable error code. Probes MUST NOT
log the supplied credential; many SDKs and ``httpx`` responses echo
request headers or the URL into exception messages on failure, which is
why each probe sanitises error strings before returning.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass

import httpx


logger = logging.getLogger(__name__)

# How long we give each provider before declaring the probe dead. Kept short
# because the UI spinner is blocking — a real auth error returns in <1s; a
# timeout almost always means the base URL is wrong or the server is down.
_PROBE_TIMEOUT_S = 5.0


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    latency_ms: int
    # Stable machine-readable code when ok is False. One of:
    #   invalid_api_key, rate_limited, network_error, timeout,
    #   provider_error, config_error.
    error: str | None = None
    message: str | None = None


def _scrub(text: str, *secrets: str) -> str:
    """Replace every occurrence of each secret with ``***``.

    Providers sometimes echo the request in error strings (URL query params,
    Authorization headers, etc.); scrubbing guards against those leaks
    reaching the response body or logs.

    Limitation: exact-substring match only. If an SDK URL-encodes or
    base64-wraps the key in its error string, the wrapped form won't be
    scrubbed. For the SDKs we use today (anthropic, openai, httpx) this is
    fine — they echo keys verbatim when they echo them at all.
    """
    scrubbed = text
    for s in secrets:
        if s:
            scrubbed = scrubbed.replace(s, "***")
    return scrubbed


async def ping_anthropic(api_key: str, model: str) -> ProbeResult:
    """1-token completion against the configured model.

    Cheapest call that validates the key AND the model name — a valid key
    with an unknown model still fails (useful signal for the user).
    """
    from anthropic import APIStatusError, AuthenticationError
    from anthropic import AsyncAnthropic as _AsyncAnthropic

    started = time.monotonic()
    try:
        async with _AsyncAnthropic(api_key=api_key, timeout=_PROBE_TIMEOUT_S) as client:
            await client.messages.create(
                model=model,
                max_tokens=1,
                messages=[{"role": "user", "content": "."}],
            )
    except AuthenticationError as exc:
        return ProbeResult(
            ok=False,
            latency_ms=_elapsed(started),
            error="invalid_api_key",
            message=_scrub(str(exc), api_key),
        )
    except APIStatusError as exc:
        status = getattr(exc, "status_code", None)
        code = "rate_limited" if status == 429 else "provider_error"
        return ProbeResult(
            ok=False,
            latency_ms=_elapsed(started),
            error=code,
            message=_scrub(str(exc), api_key),
        )
    except httpx.TimeoutException:
        return ProbeResult(
            ok=False,
            latency_ms=_elapsed(started),
            error="timeout",
            message=f"Anthropic did not respond within {_PROBE_TIMEOUT_S:.0f}s",
        )
    except Exception as exc:  # network, DNS, SSL, etc.  noqa: BLE001
        return ProbeResult(
            ok=False,
            latency_ms=_elapsed(started),
            error="network_error",
            message=_scrub(str(exc), api_key),
        )
    return ProbeResult(ok=True, latency_ms=_elapsed(started))


async def ping_openai(api_key: str, model: str | None = None) -> ProbeResult:
    """``GET /v1/models`` — free, validates the key, requires no model.

    ``model`` is accepted for symmetry with ping_anthropic but ignored; if
    the caller wants to verify a specific model exists they can do so by
    inspecting the returned list (out of scope for this probe).
    """
    del model  # intentionally unused — kept for signature symmetry
    started = time.monotonic()
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as client:
            resp = await client.get("https://api.openai.com/v1/models", headers=headers)
    except httpx.TimeoutException:
        return ProbeResult(
            ok=False,
            latency_ms=_elapsed(started),
            error="timeout",
            message=f"OpenAI did not respond within {_PROBE_TIMEOUT_S:.0f}s",
        )
    except httpx.HTTPError as exc:
        return ProbeResult(
            ok=False,
            latency_ms=_elapsed(started),
            error="network_error",
            message=_scrub(str(exc), api_key),
        )

    latency = _elapsed(started)
    if resp.status_code == 200:
        return ProbeResult(ok=True, latency_ms=latency)
    if resp.status_code in (401, 403):
        return ProbeResult(
            ok=False,
            latency_ms=latency,
            error="invalid_api_key",
            message=f"OpenAI returned {resp.status_code}",
        )
    if resp.status_code == 429:
        return ProbeResult(
            ok=False,
            latency_ms=latency,
            error="rate_limited",
            message="OpenAI rate limit exceeded",
        )
    return ProbeResult(
        ok=False,
        latency_ms=latency,
        error="provider_error",
        message=f"OpenAI returned HTTP {resp.status_code}",
    )


async def ping_ollama(base_url: str) -> ProbeResult:
    """``GET {base_url}/api/tags`` — unauthenticated, lists available models.

    Ollama exposes no key concept, so this probe is really a reachability
    check. A common failure is the container's default
    ``host.docker.internal:11434`` pointing at a server that isn't running.
    """
    url = base_url.rstrip("/") + "/api/tags"
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as client:
            resp = await client.get(url)
    except httpx.TimeoutException:
        return ProbeResult(
            ok=False,
            latency_ms=_elapsed(started),
            error="timeout",
            message=f"Ollama at {base_url} did not respond within {_PROBE_TIMEOUT_S:.0f}s",
        )
    except httpx.HTTPError as exc:
        return ProbeResult(
            ok=False,
            latency_ms=_elapsed(started),
            error="network_error",
            message=str(exc),
        )

    latency = _elapsed(started)
    if resp.status_code == 200:
        return ProbeResult(ok=True, latency_ms=latency)
    return ProbeResult(
        ok=False,
        latency_ms=latency,
        error="provider_error",
        message=f"Ollama returned HTTP {resp.status_code}",
    )


def _elapsed(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


# Token bucket — simple in-process timestamp deque, no Redis / middleware.
# 10 requests / 60 seconds / process. The rate lives at module level so a
# single backend process (the only kind we run) applies the same budget
# across all clients; this is a single-user tool, per-IP buckets would add
# complexity without meaningful security benefit.
_RATE_WINDOW_S = 60.0
_RATE_MAX = 10
_bucket: deque[float] = deque()
_bucket_lock = asyncio.Lock()


async def rate_limit_check() -> float | None:
    """Returns ``None`` if under budget, else the retry-after delay in seconds."""
    async with _bucket_lock:
        now = time.monotonic()
        # Drop timestamps that have fallen out of the window.
        cutoff = now - _RATE_WINDOW_S
        while _bucket and _bucket[0] < cutoff:
            _bucket.popleft()
        if len(_bucket) >= _RATE_MAX:
            return _RATE_WINDOW_S - (now - _bucket[0])
        _bucket.append(now)
        return None


def _reset_rate_limit_for_tests() -> None:
    _bucket.clear()
