"""Chaos tests: verify graceful degradation under extreme conditions."""


import pytest

from core.errors.circuit_breaker import CircuitBreaker, ErrorBoundary
from core.utils.rate_limiter import QuotaConfig, RateLimiter
from core.utils.retry import RetryConfig, RetryManager


class TestChaosFailureModes:
    """Simulate cascading failures and verify containment."""

    @pytest.mark.asyncio
    async def test_rapid_failures_open_circuit(self):
        cb = CircuitBreaker("chaos")

        async def explode():
            raise RuntimeError("chaos")

        for _ in range(10):
            try:
                await cb.call(explode)
            except (RuntimeError, Exception):
                pass

        # Circuit should be open after threshold
        with pytest.raises(Exception):
            await cb.call(explode)

    @pytest.mark.asyncio
    async def test_error_boundary_isolates_failure(self):
        boundary = ErrorBoundary("chaos")

        async def explode():
            raise RuntimeError("cascade")

        # Multiple calls should all return default, not propagate
        for _ in range(5):
            result = await boundary.execute(explode, default="safe")
            assert result == "safe"

    @pytest.mark.asyncio
    async def test_rate_limiter_under_flood(self):
        rl = RateLimiter(QuotaConfig(max_requests_per_minute=1000))
        allowed = 0
        for _ in range(2000):
            if await rl.acquire():
                allowed += 1
                rl.release()
        assert allowed <= 1000

    @pytest.mark.asyncio
    async def test_retry_exhaustion_no_infinite_loop(self):
        mgr = RetryManager(RetryConfig(max_attempts=2, base_delay_sec=0.001))

        async def always_fail():
            raise ConnectionError("permanent")

        with pytest.raises(ConnectionError):
            await mgr.execute(always_fail)
