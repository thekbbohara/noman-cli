"""Tests for circuit breaker and error boundary."""

import asyncio

import pytest

from core.errors import CircuitBreakerOpenError
from core.errors.circuit_breaker import CircuitBreaker, CircuitBreakerConfig, ErrorBoundary


@pytest.mark.asyncio
async def test_cb_closed_allows_calls():
    cb = CircuitBreaker("test")
    result = await cb.call(lambda: asyncio.sleep(0))
    assert cb.state.name == "CLOSED"


@pytest.mark.asyncio
async def test_cb_opens_after_failures():
    cb = CircuitBreaker("test", CircuitBreakerConfig(failure_threshold=2))

    async def fail():
        raise ValueError("boom")

    with pytest.raises(ValueError):
        await cb.call(fail)
    with pytest.raises(ValueError):
        await cb.call(fail)
    with pytest.raises(CircuitBreakerOpenError):
        await cb.call(fail)


@pytest.mark.asyncio
async def test_error_boundary_returns_default():
    boundary = ErrorBoundary("test")

    async def fail():
        raise ValueError("boom")

    result = await boundary.execute(fail, default="fallback")
    assert result == "fallback"


@pytest.mark.asyncio
async def test_error_boundary_passes_success():
    boundary = ErrorBoundary("test")

    async def ok():
        return 42

    result = await boundary.execute(ok, default=0)
    assert result == 42
