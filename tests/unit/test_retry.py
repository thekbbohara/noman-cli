"""Tests for retry logic."""

import pytest

from core.utils.retry import RetryConfig, RetryManager, with_retry


@pytest.mark.asyncio
async def test_retry_success_on_first():
    async def ok():
        return 42

    mgr = RetryManager()
    assert await mgr.execute(ok) == 42


@pytest.mark.asyncio
async def test_retry_eventually_succeeds():
    calls = 0

    async def flaky():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ConnectionError("fail")
        return "ok"

    mgr = RetryManager(RetryConfig(max_attempts=3, base_delay_sec=0.01))
    assert await mgr.execute(flaky) == "ok"
    assert calls == 3


@pytest.mark.asyncio
async def test_retry_exhaustion():
    async def always_fail():
        raise ConnectionError("nope")

    mgr = RetryManager(RetryConfig(max_attempts=2, base_delay_sec=0.01))
    with pytest.raises(ConnectionError, match="nope"):
        await mgr.execute(always_fail)


@pytest.mark.asyncio
async def test_retry_decorator():
    @with_retry(RetryConfig(max_attempts=2, base_delay_sec=0.01))
    async def fn():
        return 1

    assert await fn() == 1
