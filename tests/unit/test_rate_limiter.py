"""Tests for rate limiting."""


import pytest

from core.errors import RateLimitError
from core.utils.rate_limiter import QuotaConfig, QuotaManager, RateLimiter


@pytest.mark.asyncio
async def test_rate_limiter_allows_under_limit():
    rl = RateLimiter(QuotaConfig(max_requests_per_minute=2))
    assert await rl.acquire()
    assert await rl.acquire()


@pytest.mark.asyncio
async def test_rate_limiter_blocks_over_limit():
    rl = RateLimiter(QuotaConfig(max_requests_per_minute=1))
    await rl.acquire()
    assert not await rl.acquire()


@pytest.mark.asyncio
async def test_rate_limiter_context_manager():
    rl = RateLimiter(QuotaConfig(max_requests_per_minute=1))
    async with rl:
        pass
    with pytest.raises(RateLimitError):
        async with rl:
            pass


@pytest.mark.asyncio
async def test_quota_manager_tool_limit():
    qm = QuotaManager(QuotaConfig(max_tool_calls_per_session=1))
    await qm.check_tool_call("read")
    with pytest.raises(RateLimitError):
        await qm.check_tool_call("read")


@pytest.mark.asyncio
async def test_quota_manager_turn_limit():
    qm = QuotaManager(QuotaConfig(max_turns_per_session=1))
    await qm.check_turn("sess-1")
    with pytest.raises(RateLimitError):
        await qm.check_turn("sess-1")
