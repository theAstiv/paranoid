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
from backend.config import settings
from backend.security.rate_limit import (
    AUTH_RATE_LIMIT,
    ENRICHMENT_RATE_LIMIT,
    ENRICHMENT_RATE_WINDOW,
    PIPELINE_RATE_LIMIT,
    PIPELINE_RATE_WINDOW,
    RATE_LIMIT,
    RATE_WINDOW,
    REGISTER_RATE_LIMIT,
    WRITE_RATE_LIMIT,
    WRITE_RATE_WINDOW,
    analyze_rate_limit,
    auth_rate_limit,
    enrichment_rate_limit,
    pipeline_rate_limit,
    register_rate_limit,
    write_rate_limit,
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


def _forwarded_request(peer: str, forwarded_for: str) -> MagicMock:
    req = MagicMock()
    req.headers = {"X-Forwarded-For": forwarded_for}
    req.client = MagicMock()
    req.client.host = peer
    return req


def test_x_forwarded_for_is_ignored_without_trusted_proxies(monkeypatch):
    """BB-45: a client-sent header must not choose its own bucket."""
    monkeypatch.setattr(settings, "trusted_proxies", "")
    assert rl._get_client_ip(_forwarded_request("10.0.0.1", "203.0.113.5")) == "10.0.0.1"


def test_x_forwarded_for_is_ignored_from_an_untrusted_peer(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxies", "10.0.0.0/24")
    assert rl._get_client_ip(_forwarded_request("198.51.100.9", "203.0.113.5")) == "198.51.100.9"


def test_x_forwarded_for_is_used_when_the_peer_is_a_trusted_proxy(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxies", "10.0.0.0/24")
    assert rl._get_client_ip(_forwarded_request("10.0.0.1", "203.0.113.5")) == "203.0.113.5"


def test_x_forwarded_for_takes_the_rightmost_untrusted_hop(monkeypatch):
    """A proxy appends to the client's header, so left-hand entries are spoofable."""
    monkeypatch.setattr(settings, "trusted_proxies", "10.0.0.0/24")
    req = _forwarded_request("10.0.0.1", "1.2.3.4, 203.0.113.5, 10.0.0.2")
    assert rl._get_client_ip(req) == "203.0.113.5"


def test_invalid_trusted_proxy_entry_is_ignored(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxies", "not-an-ip, 10.0.0.1")
    assert rl._get_client_ip(_forwarded_request("10.0.0.1", "203.0.113.5")) == "203.0.113.5"


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


# ---------------------------------------------------------------------------
# Write rate limiter tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_requests_under_limit_pass():
    """WRITE_RATE_LIMIT - 1 requests from the same IP all succeed."""
    req = _mock_request("10.20.0.1")
    for _ in range(WRITE_RATE_LIMIT - 1):
        await write_rate_limit(req)


@pytest.mark.asyncio
async def test_write_request_at_limit_passes():
    """Exactly WRITE_RATE_LIMIT requests succeed."""
    req = _mock_request("10.20.0.2")
    for _ in range(WRITE_RATE_LIMIT):
        await write_rate_limit(req)


@pytest.mark.asyncio
async def test_write_request_over_limit_raises_429():
    """The (WRITE_RATE_LIMIT + 1)th request raises HTTP 429."""
    from fastapi import HTTPException

    req = _mock_request("10.20.0.3")
    for _ in range(WRITE_RATE_LIMIT):
        await write_rate_limit(req)

    with pytest.raises(HTTPException) as exc_info:
        await write_rate_limit(req)

    assert exc_info.value.status_code == 429
    assert "Rate limit exceeded" in exc_info.value.detail
    assert "Retry-After" in exc_info.value.headers


@pytest.mark.asyncio
async def test_write_bucket_independent_from_analyze_and_pipeline():
    """Exhausting the write bucket does not affect analyze or pipeline buckets."""
    from fastapi import HTTPException

    req = _mock_request("10.20.0.4")

    for _ in range(WRITE_RATE_LIMIT):
        await write_rate_limit(req)
    with pytest.raises(HTTPException):
        await write_rate_limit(req)

    # analyze and pipeline buckets should be fresh for the same IP
    for _ in range(RATE_LIMIT):
        await analyze_rate_limit(req)
    for _ in range(PIPELINE_RATE_LIMIT):
        await pipeline_rate_limit(req)


@pytest.mark.asyncio
async def test_write_bucket_refills_after_window():
    """After the window expires, the same IP can make new write requests."""
    from fastapi import HTTPException

    req = _mock_request("10.20.0.5")

    for _ in range(WRITE_RATE_LIMIT):
        await write_rate_limit(req)
    with pytest.raises(HTTPException):
        await write_rate_limit(req)

    old_time = time.monotonic() - WRITE_RATE_WINDOW - 1.0
    rl._write_buckets["10.20.0.5"] = [old_time] * WRITE_RATE_LIMIT

    for _ in range(WRITE_RATE_LIMIT):
        await write_rate_limit(req)


# ---------------------------------------------------------------------------
# Enrichment rate limiter tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enrichment_requests_under_limit_pass():
    """ENRICHMENT_RATE_LIMIT - 1 requests from the same IP all succeed."""
    req = _mock_request("10.30.0.1")
    for _ in range(ENRICHMENT_RATE_LIMIT - 1):
        await enrichment_rate_limit(req)


@pytest.mark.asyncio
async def test_enrichment_request_at_limit_passes():
    """Exactly ENRICHMENT_RATE_LIMIT requests succeed."""
    req = _mock_request("10.30.0.2")
    for _ in range(ENRICHMENT_RATE_LIMIT):
        await enrichment_rate_limit(req)


@pytest.mark.asyncio
async def test_enrichment_request_over_limit_raises_429():
    """The (ENRICHMENT_RATE_LIMIT + 1)th request raises HTTP 429."""
    from fastapi import HTTPException

    req = _mock_request("10.30.0.3")
    for _ in range(ENRICHMENT_RATE_LIMIT):
        await enrichment_rate_limit(req)

    with pytest.raises(HTTPException) as exc_info:
        await enrichment_rate_limit(req)

    assert exc_info.value.status_code == 429
    assert "Rate limit exceeded" in exc_info.value.detail
    assert "Retry-After" in exc_info.value.headers


@pytest.mark.asyncio
async def test_enrichment_bucket_independent_from_write():
    """Exhausting the write bucket does not affect the enrichment bucket."""
    from fastapi import HTTPException

    req = _mock_request("10.30.0.4")

    for _ in range(WRITE_RATE_LIMIT):
        await write_rate_limit(req)
    with pytest.raises(HTTPException):
        await write_rate_limit(req)

    # enrichment bucket should be fresh despite same IP
    for _ in range(ENRICHMENT_RATE_LIMIT):
        await enrichment_rate_limit(req)


@pytest.mark.asyncio
async def test_enrichment_bucket_refills_after_window():
    """After the window expires, the same IP can make new enrichment requests."""
    from fastapi import HTTPException

    req = _mock_request("10.30.0.5")

    for _ in range(ENRICHMENT_RATE_LIMIT):
        await enrichment_rate_limit(req)
    with pytest.raises(HTTPException):
        await enrichment_rate_limit(req)

    old_time = time.monotonic() - ENRICHMENT_RATE_WINDOW - 1.0
    rl._enrichment_buckets["10.30.0.5"] = [old_time] * ENRICHMENT_RATE_LIMIT

    for _ in range(ENRICHMENT_RATE_LIMIT):
        await enrichment_rate_limit(req)


# ---------------------------------------------------------------------------
# Routes that carry a tier (S3, S4 in the 2026-11-02 review)
# ---------------------------------------------------------------------------


@pytest.fixture
async def client(test_db):
    from httpx import ASGITransport, AsyncClient

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["analyze", "extract"])
async def test_llm_model_endpoints_are_rate_limited(client, action):
    """Both make LLM calls; the limit is checked before the handler, so an unknown
    model 404s until the bucket is empty and then gets 429 without any LLM call."""
    path = f"/api/models/no-such-model/{action}"
    for _ in range(ENRICHMENT_RATE_LIMIT):
        resp = await client.post(path)
        assert resp.status_code != 429
    resp = await client.post(path)
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers


@pytest.mark.asyncio
async def test_register_is_rate_limited_before_hashing(client):
    """S3: every registration is an argon2id hash, so a refused call must not hash."""
    from unittest.mock import AsyncMock, patch

    hashes = MagicMock(return_value="$argon2id$stub")
    created = {"id": "u1", "username": "u", "email": "u@test.local", "is_active": 1}
    with (
        patch("backend.routes.auth.get_user_by_username", new=AsyncMock(return_value=None)),
        patch("backend.routes.auth.get_user_by_email", new=AsyncMock(return_value=None)),
        patch("backend.routes.auth.create_user", new=AsyncMock(return_value=created)),
        patch("backend.routes.auth.hash_password", new=hashes),
    ):
        body = {"username": "newuser", "email": "new@test.local", "password": "password123"}
        for _ in range(REGISTER_RATE_LIMIT):
            assert (await client.post("/api/auth/register", json=body)).status_code == 201
        resp = await client.post("/api/auth/register", json=body)

    assert resp.status_code == 429
    assert "Retry-After" in resp.headers
    assert hashes.call_count == REGISTER_RATE_LIMIT


@pytest.mark.asyncio
async def test_register_bucket_independent_from_login():
    """Sign-up spam from a shared IP must not lock everyone behind it out of login."""
    from fastapi import HTTPException

    req = _mock_request("10.40.0.1")
    for _ in range(REGISTER_RATE_LIMIT):
        await register_rate_limit(req)
    with pytest.raises(HTTPException):
        await register_rate_limit(req)

    for _ in range(AUTH_RATE_LIMIT):
        await auth_rate_limit(req)
