"""Direct unit tests for backend.providers.healthcheck primitives."""

import pytest

from backend.providers import healthcheck
from backend.providers.healthcheck import _scrub, rate_limit_check


class TestScrub:
    def test_replaces_single_occurrence(self):
        assert _scrub("auth failed for sk-ant-abc", "sk-ant-abc") == ("auth failed for ***")

    def test_replaces_multiple_occurrences(self):
        text = "header=sk-x trace=sk-x again sk-x"
        assert _scrub(text, "sk-x") == "header=*** trace=*** again ***"

    def test_empty_secret_is_noop(self):
        """Empty secrets don't destroy the input (``str.replace('', '***')``
        would otherwise explode every character)."""
        assert _scrub("untouched", "") == "untouched"

    def test_secret_not_in_text_is_noop(self):
        assert _scrub("nothing to see here", "sk-absent") == "nothing to see here"

    def test_multiple_secrets_all_replaced(self):
        out = _scrub("a=sk-one b=sk-two", "sk-one", "sk-two")
        assert out == "a=*** b=***"


class TestRateLimit:
    @pytest.fixture(autouse=True)
    def _reset(self):
        healthcheck._reset_rate_limit_for_tests()
        yield
        healthcheck._reset_rate_limit_for_tests()

    @pytest.mark.asyncio
    async def test_allows_up_to_max(self):
        for _ in range(healthcheck._RATE_MAX):
            assert await rate_limit_check() is None

    @pytest.mark.asyncio
    async def test_rejects_over_max_with_retry_after(self):
        for _ in range(healthcheck._RATE_MAX):
            await rate_limit_check()
        retry = await rate_limit_check()
        assert retry is not None
        assert 0 < retry <= healthcheck._RATE_WINDOW_S

    @pytest.mark.asyncio
    async def test_window_expiry_frees_slots(self, monkeypatch):
        """Timestamps older than the window are dropped via popleft()."""
        import time as time_mod

        base = time_mod.monotonic()
        # Fake the clock: first 10 calls happen at t=0, the 11th at t=window+1.
        clock = {"now": base}
        monkeypatch.setattr("backend.providers.healthcheck.time.monotonic", lambda: clock["now"])
        for _ in range(healthcheck._RATE_MAX):
            assert await rate_limit_check() is None
        # 11th in the same window → rejected.
        assert await rate_limit_check() is not None
        # Advance past the window; popleft should drain the bucket.
        clock["now"] = base + healthcheck._RATE_WINDOW_S + 1
        assert await rate_limit_check() is None
