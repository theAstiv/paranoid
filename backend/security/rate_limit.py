"""In-memory token-bucket rate limiter for FastAPI routes.

Designed for the free-form /api/analyze/ endpoint which fires two LLM calls
per request and has no auth guard. A single token bucket per client IP caps
the blast radius of credential-draining abuse without requiring an external
store (Redis, memcached) or an additional dependency (slowapi, limits).

Trade-offs accepted:
- State is process-local — restarts reset counters. Acceptable for a
  self-hosted single-process deployment.
- Multiple workers / Gunicorn with multiple processes will each have their own
  bucket, so the effective limit is limit x workers. For a dev/demo deployment
  this is fine; document clearly so operators know.
- IPv6 /64 prefixes are not aggregated — each distinct address gets its own
  bucket. A determined attacker with a /48 could cycle addresses. For the VULNCON
  demo scenario (one team, one IP), this is more than adequate.

Usage in a route:
    from backend.security.rate_limit import analyze_rate_limit

    @router.post("/")
    async def my_handler(
        _: None = Depends(analyze_rate_limit),
    ) -> ...:
        ...
"""

import asyncio
import time
from collections import OrderedDict

from fastapi import HTTPException, Request


# ---------------------------------------------------------------------------
# Configuration (deliberately not in settings.py — these are security knobs
# that should only be tuned with an understanding of the bucket semantics).
# ---------------------------------------------------------------------------

# How many requests each IP is allowed per time window.
_LIMIT: int = 20

# Window length in seconds.  20 requests / 60 s ≈ 1 req / 3 s burst-smoothed.
_WINDOW_SECONDS: float = 60.0

# Maximum number of distinct IPs to track before evicting the oldest entries.
# Prevents unbounded memory growth under a slow-drip scan from many sources.
_MAX_BUCKETS: int = 2_000


# ---------------------------------------------------------------------------
# Bucket store
# ---------------------------------------------------------------------------

# OrderedDict gives O(1) LRU eviction: move_to_end on access, popitem(last=False)
# to evict oldest when over capacity.
_buckets: OrderedDict[str, list[float]] = OrderedDict()
_lock = asyncio.Lock()


def _get_client_ip(request: Request) -> str:
    """Extract the best-available client IP from the request.

    Prefers X-Forwarded-For (set by reverse proxies) over the raw socket address.
    Only the first forwarded-for entry is used — the leftmost is the original
    client when the proxy chain is trusted.
    """
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


async def analyze_rate_limit(request: Request) -> None:
    """FastAPI dependency — raises HTTP 429 when the caller exceeds the limit.

    Implements a sliding-window counter: keeps the timestamps of each request
    from this IP within the current window, rejects when the count is at or
    above _LIMIT.
    """
    ip = _get_client_ip(request)
    now = time.monotonic()
    cutoff = now - _WINDOW_SECONDS

    async with _lock:
        # Evict the oldest bucket when at capacity (before inserting a new key).
        if ip not in _buckets and len(_buckets) >= _MAX_BUCKETS:
            _buckets.popitem(last=False)

        # Retrieve or create the sliding-window list for this IP, then prune
        # timestamps that have aged out of the window.
        timestamps = _buckets.get(ip, [])
        timestamps = [t for t in timestamps if t > cutoff]

        if len(timestamps) >= _LIMIT:
            # Re-store the pruned list so the bucket stays accurate.
            _buckets[ip] = timestamps
            _buckets.move_to_end(ip)
            retry_after = int(_WINDOW_SECONDS - (now - timestamps[0])) + 1
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Rate limit exceeded: {_LIMIT} requests per "
                    f"{int(_WINDOW_SECONDS)} seconds. "
                    f"Retry after {retry_after} seconds."
                ),
                headers={"Retry-After": str(retry_after)},
            )

        timestamps.append(now)
        _buckets[ip] = timestamps
        _buckets.move_to_end(ip)


# ---------------------------------------------------------------------------
# Pipeline rate limiter — tighter than analyze because each run triggers
# multiple LLM calls and may run for several minutes.
# ---------------------------------------------------------------------------

_PIPELINE_LIMIT: int = 5
_PIPELINE_WINDOW: float = 60.0
_pipeline_buckets: OrderedDict[str, list[float]] = OrderedDict()
_pipeline_lock = asyncio.Lock()


async def pipeline_rate_limit(request: Request) -> None:
    """FastAPI dependency — rate-limits POST /models/{id}/run.

    5 requests per 60 seconds per IP. Each pipeline run may spend minutes
    calling LLM APIs, so a tight limit is appropriate even for legitimate use.
    """
    ip = _get_client_ip(request)
    now = time.monotonic()
    cutoff = now - _PIPELINE_WINDOW

    async with _pipeline_lock:
        if ip not in _pipeline_buckets and len(_pipeline_buckets) >= _MAX_BUCKETS:
            _pipeline_buckets.popitem(last=False)

        timestamps = _pipeline_buckets.get(ip, [])
        timestamps = [t for t in timestamps if t > cutoff]

        if len(timestamps) >= _PIPELINE_LIMIT:
            _pipeline_buckets[ip] = timestamps
            _pipeline_buckets.move_to_end(ip)
            retry_after = int(_PIPELINE_WINDOW - (now - timestamps[0])) + 1
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Rate limit exceeded: {_PIPELINE_LIMIT} pipeline runs per "
                    f"{int(_PIPELINE_WINDOW)} seconds. "
                    f"Retry after {retry_after} seconds."
                ),
                headers={"Retry-After": str(retry_after)},
            )

        timestamps.append(now)
        _pipeline_buckets[ip] = timestamps
        _pipeline_buckets.move_to_end(ip)


# Expose the constants so tests can introspect them without re-importing the
# module multiple times and risking stale references to the bucket dict.
RATE_LIMIT = _LIMIT
RATE_WINDOW = _WINDOW_SECONDS
PIPELINE_RATE_LIMIT = _PIPELINE_LIMIT
PIPELINE_RATE_WINDOW = _PIPELINE_WINDOW


def _reset_for_tests() -> None:
    """Clear all buckets — call from test setUp / fixture teardown only."""
    _buckets.clear()
    _pipeline_buckets.clear()
