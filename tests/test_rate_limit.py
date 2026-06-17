"""Tests for backend/security/rate_limit.py.

Covers the sliding-window token-bucket behaviour:
- Requests under the limit pass through.
- The (LIMIT+1)th request in the window raises HTTP 429 with Retry-After.
- After the window slides past, the bucket refills and requests succeed again.
- Distinct IPs have independent buckets.
- The bucket store evicts the oldest entry when _MAX_BUCKETS is exceeded.
"""

import time
from unittest.mock import MagicMock

import pytest

import backend.security.rate_limit as rl
from backend.security.rate_limit import (
    PIPELINE_RATE_LIMIT,
    PIPELINE_RATE_WINDOW,
    RATE_LIMIT,
    RATE_WINDOW,
    analyze_rate_limit,
    pipeline_rate_limit,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_request(ip: str) -> MagicMock:
    req = MagicMock()
    req.headers = {}
    req.client = MagicMock()
    req.client.host = ip
    return req


@pytest.fixture(autouse=True)
def reset_buckets():
    """Clear the bucket store before every test."""
    rl._reset_for_tests()
    yield
    rl._reset_for_tests()


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_requests_under_limit_pass():
    """RATE_LIMIT - 1 requests from the same IP all succeed."""
    req = _mock_request("10.0.0.1")
    for _ in range(RATE_LIMIT - 1):
        await analyze_rate_limit(req)  # should not raise


@pytest.mark.asyncio
async def test_request_at_limit_passes():
    """Exactly RATE_LIMIT requests succeed."""
    req = _mock_request("10.0.0.2")
    for _ in range(RATE_LIMIT):
        await analyze_rate_limit(req)


@pytest.mark.asyncio
async def test_request_over_limit_raises_429():
    """The (RATE_LIMIT + 1)th request in the window raises HTTP 429."""
    from fastapi import HTTPException

    req = _mock_request("10.0.0.3")
    for _ in range(RATE_LIMIT):
        await analyze_rate_limit(req)

    with pytest.raises(HTTPException) as exc_info:
        await analyze_rate_limit(req)

    assert exc_info.value.status_code == 429
    assert "Rate limit exceeded" in exc_info.value.detail
    assert "Retry-After" in exc_info.value.headers


@pytest.mark.asyncio
async def test_distinct_ips_have_independent_buckets():
    """Exhausting one IP's bucket does not affect a different IP."""
    from fastapi import HTTPException

    req_a = _mock_request("10.1.0.1")
    req_b = _mock_request("10.1.0.2")

    for _ in range(RATE_LIMIT):
        await analyze_rate_limit(req_a)

    with pytest.raises(HTTPException):
        await analyze_rate_limit(req_a)

    # IP B has a fresh bucket — should not raise
    for _ in range(RATE_LIMIT):
        await analyze_rate_limit(req_b)


@pytest.mark.asyncio
async def test_x_forwarded_for_is_used_when_present():
    """X-Forwarded-For overrides the socket IP for bucket keying."""
    req = MagicMock()
    req.headers = {"X-Forwarded-For": "203.0.113.5, 10.0.0.1"}
    req.client = MagicMock()
    req.client.host = "10.0.0.1"

    # Should bucket on 203.0.113.5, not 10.0.0.1
    await analyze_rate_limit(req)
    assert "203.0.113.5" in rl._buckets
    assert "10.0.0.1" not in rl._buckets


@pytest.mark.asyncio
async def test_bucket_refills_after_window(monkeypatch):
    """After the window expires, the same IP can make RATE_LIMIT new requests."""
    from fastapi import HTTPException

    req = _mock_request("10.2.0.1")

    # Exhaust the bucket
    for _ in range(RATE_LIMIT):
        await analyze_rate_limit(req)

    with pytest.raises(HTTPException):
        await analyze_rate_limit(req)

    # Fast-forward: backdate all existing timestamps so they're outside the window.
    old_time = time.monotonic() - RATE_WINDOW - 1.0
    rl._buckets["10.2.0.1"] = [old_time] * RATE_LIMIT

    # Now the sliding window should be empty — all RATE_LIMIT requests should pass.
    for _ in range(RATE_LIMIT):
        await analyze_rate_limit(req)


@pytest.mark.asyncio
async def test_oldest_bucket_evicted_at_capacity():
    """When _MAX_BUCKETS is exceeded, the oldest entry is evicted."""
    original_max = rl._MAX_BUCKETS
    try:
        rl._MAX_BUCKETS = 3
        for i in range(4):
            req = _mock_request(f"10.3.0.{i}")
            await analyze_rate_limit(req)
        # Only 3 buckets should remain; the first IP was evicted
        assert len(rl._buckets) == 3
        assert "10.3.0.0" not in rl._buckets
    finally:
        rl._MAX_BUCKETS = original_max


# ---------------------------------------------------------------------------
# Pipeline rate limiter tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_requests_under_limit_pass():
    """PIPELINE_RATE_LIMIT - 1 requests from the same IP all succeed."""
    req = _mock_request("10.10.0.1")
    for _ in range(PIPELINE_RATE_LIMIT - 1):
        await pipeline_rate_limit(req)


@pytest.mark.asyncio
async def test_pipeline_request_at_limit_passes():
    """Exactly PIPELINE_RATE_LIMIT requests succeed."""
    req = _mock_request("10.10.0.2")
    for _ in range(PIPELINE_RATE_LIMIT):
        await pipeline_rate_limit(req)


@pytest.mark.asyncio
async def test_pipeline_request_over_limit_raises_429():
    """The (PIPELINE_RATE_LIMIT + 1)th request raises HTTP 429."""
    from fastapi import HTTPException

    req = _mock_request("10.10.0.3")
    for _ in range(PIPELINE_RATE_LIMIT):
        await pipeline_rate_limit(req)

    with pytest.raises(HTTPException) as exc_info:
        await pipeline_rate_limit(req)

    assert exc_info.value.status_code == 429
    assert "Rate limit exceeded" in exc_info.value.detail
    assert "Retry-After" in exc_info.value.headers


@pytest.mark.asyncio
async def test_pipeline_bucket_independent_from_analyze_bucket():
    """Exhausting the pipeline bucket does not affect the analyze bucket."""
    from fastapi import HTTPException

    req = _mock_request("10.10.0.4")

    # Exhaust pipeline bucket
    for _ in range(PIPELINE_RATE_LIMIT):
        await pipeline_rate_limit(req)
    with pytest.raises(HTTPException):
        await pipeline_rate_limit(req)

    # Same IP should still have a fresh analyze bucket
    for _ in range(RATE_LIMIT):
        await analyze_rate_limit(req)


@pytest.mark.asyncio
async def test_pipeline_bucket_refills_after_window(monkeypatch):
    """After the window expires, the same IP can make new pipeline requests."""
    from fastapi import HTTPException

    req = _mock_request("10.10.0.5")

    for _ in range(PIPELINE_RATE_LIMIT):
        await pipeline_rate_limit(req)
    with pytest.raises(HTTPException):
        await pipeline_rate_limit(req)

    # Backdate all timestamps past the window
    old_time = time.monotonic() - PIPELINE_RATE_WINDOW - 1.0
    rl._pipeline_buckets["10.10.0.5"] = [old_time] * PIPELINE_RATE_LIMIT

    for _ in range(PIPELINE_RATE_LIMIT):
        await pipeline_rate_limit(req)
