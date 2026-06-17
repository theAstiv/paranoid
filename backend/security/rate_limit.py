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
from dataclasses import dataclass, field

from fastapi import HTTPException, Request


# Maximum number of distinct IPs to track before evicting the oldest entries.
# Prevents unbounded memory growth under a slow-drip scan from many sources.
_MAX_BUCKETS: int = 2_000


@dataclass
class _RateLimitTier:
    """Bundle a rate-limit tier's state and config into a single named object.

    Using a struct instead of positional parameters prevents silent wrong-tier
    substitution: all three fields (buckets, lock, limit, window, unit) carry
    names, so a caller passing _write_tier where _pipeline_tier is expected
    produces an obvious semantic mismatch rather than a silent runtime bug.

    Each tier has its own independent bucket dict and lock — exhausting one
    tier does not affect any other tier for the same IP.
    """

    limit: int
    window: float
    unit: str  # human-readable label used in 429 detail messages
    buckets: OrderedDict[str, list[float]] = field(default_factory=OrderedDict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


# ---------------------------------------------------------------------------
# Tier definitions — add a new tier here; _ALL_TIERS and _reset_for_tests()
# handle it automatically.
# ---------------------------------------------------------------------------

# Analyze tier: /api/analyze/ — two LLM calls per request.
_ANALYZE_TIER = _RateLimitTier(limit=20, window=60.0, unit="requests")

# Write tier: DB-only mutations — model creation, code-source creation, reindex.
# No LLM cost, so more permissive than enrichment.
_WRITE_TIER = _RateLimitTier(limit=30, window=60.0, unit="requests")

# Enrichment tier: single-LLM-call endpoints — attack trees, test cases.
# Separate from write_rate_limit so that 30 model creations do not exhaust
# the budget for LLM enrichment calls on the same IP.
_ENRICHMENT_TIER = _RateLimitTier(limit=20, window=60.0, unit="requests")

# Pipeline tier: POST /models/{id}/run — multi-step, multi-minute pipeline runs.
_PIPELINE_TIER = _RateLimitTier(limit=5, window=60.0, unit="pipeline runs")

# Registry — the only place that must be updated when a new tier is added.
# _reset_for_tests() iterates this list, so new tiers are automatically cleared.
_ALL_TIERS: list[_RateLimitTier] = [
    _ANALYZE_TIER,
    _WRITE_TIER,
    _ENRICHMENT_TIER,
    _PIPELINE_TIER,
]

# Module-level aliases so tests can backdate timestamps directly.
# These reference the same OrderedDict object as the tier — mutating them
# is equivalent to mutating tier.buckets.
_buckets = _ANALYZE_TIER.buckets
_write_buckets = _WRITE_TIER.buckets
_enrichment_buckets = _ENRICHMENT_TIER.buckets
_pipeline_buckets = _PIPELINE_TIER.buckets


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


async def _check_bucket(ip: str, tier: _RateLimitTier) -> None:
    """Shared sliding-window check — raises HTTP 429 when ip exceeds tier.limit.

    Args:
        ip:   Client IP used as the bucket key.
        tier: The rate-limit tier to check against (buckets, lock, limit, window, unit).
    """
    now = time.monotonic()
    cutoff = now - tier.window

    async with tier.lock:
        # Evict the oldest bucket when at capacity (before inserting a new key).
        if ip not in tier.buckets and len(tier.buckets) >= _MAX_BUCKETS:
            tier.buckets.popitem(last=False)

        # Prune timestamps outside the window.
        timestamps = [t for t in tier.buckets.get(ip, []) if t > cutoff]

        if len(timestamps) >= tier.limit:
            tier.buckets[ip] = timestamps
            tier.buckets.move_to_end(ip)
            retry_after = int(tier.window - (now - timestamps[0])) + 1
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Rate limit exceeded: {tier.limit} {tier.unit} per "
                    f"{int(tier.window)} seconds. "
                    f"Retry after {retry_after} seconds."
                ),
                headers={"Retry-After": str(retry_after)},
            )

        timestamps.append(now)
        tier.buckets[ip] = timestamps
        tier.buckets.move_to_end(ip)


# ---------------------------------------------------------------------------
# Public FastAPI dependencies — one per tier.
# ---------------------------------------------------------------------------


async def analyze_rate_limit(request: Request) -> None:
    """FastAPI dependency — rate-limits /api/analyze/ (20 req / 60 s per IP)."""
    await _check_bucket(_get_client_ip(request), _ANALYZE_TIER)


async def write_rate_limit(request: Request) -> None:
    """FastAPI dependency — rate-limits DB-only write endpoints (30 req / 60 s per IP).

    Covers: model creation, code-source creation, reindex.
    Does NOT cover LLM-backed enrichment endpoints — use enrichment_rate_limit for those.
    """
    await _check_bucket(_get_client_ip(request), _WRITE_TIER)


async def enrichment_rate_limit(request: Request) -> None:
    """FastAPI dependency — rate-limits single-LLM-call enrichment endpoints (20 req / 60 s per IP).

    Covers: attack-tree generation, test-case generation.
    Separate from write_rate_limit so that DB-write traffic does not exhaust
    the LLM enrichment budget for the same IP.
    """
    await _check_bucket(_get_client_ip(request), _ENRICHMENT_TIER)


async def pipeline_rate_limit(request: Request) -> None:
    """FastAPI dependency — rate-limits POST /models/{id}/run (5 req / 60 s per IP).

    Each pipeline run spawns multiple LLM calls and may run for several minutes.
    This limit covers the full pipeline endpoint only — NOT enrichment endpoints.
    """
    await _check_bucket(_get_client_ip(request), _PIPELINE_TIER)


# Expose the constants so tests can introspect them without re-importing the
# module multiple times and risking stale references to the bucket dict.
RATE_LIMIT = _ANALYZE_TIER.limit
RATE_WINDOW = _ANALYZE_TIER.window
WRITE_RATE_LIMIT = _WRITE_TIER.limit
WRITE_RATE_WINDOW = _WRITE_TIER.window
ENRICHMENT_RATE_LIMIT = _ENRICHMENT_TIER.limit
ENRICHMENT_RATE_WINDOW = _ENRICHMENT_TIER.window
PIPELINE_RATE_LIMIT = _PIPELINE_TIER.limit
PIPELINE_RATE_WINDOW = _PIPELINE_TIER.window


def _reset_for_tests() -> None:
    """Clear all tier buckets — call from test setUp / fixture teardown only.

    Iterates _ALL_TIERS so adding a new tier is the only change needed to
    keep test isolation correct — no manual .clear() line required here.
    """
    for tier in _ALL_TIERS:
        tier.buckets.clear()
