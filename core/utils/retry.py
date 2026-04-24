"""Exponential backoff retry logic."""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from core.errors import NoManError

logger = logging.getLogger(__name__)
T = TypeVar("T")


@dataclass(frozen=True)
class RetryConfig:
    """Configuration for retry behaviour."""

    max_attempts: int = 3
    base_delay_sec: float = 1.0
    max_delay_sec: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True
    jitter_max: float = 0.5
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,)


DEFAULT_RETRY_CONFIG = RetryConfig(
    max_attempts=3,
    base_delay_sec=1.0,
    retryable_exceptions=(NoManError, ConnectionError, TimeoutError),
)


class RetryManager:
    """Execute a callable with exponential-backoff retries."""

    def __init__(self, config: RetryConfig | None = None) -> None:
        self.config = config or DEFAULT_RETRY_CONFIG

    def _delay_for_attempt(self, attempt: int) -> float:
        """Compute delay (with optional jitter) for a given attempt."""
        raw = self.config.base_delay_sec * (self.config.exponential_base ** attempt)
        delay = min(raw, self.config.max_delay_sec)
        if self.config.jitter:
            delay += random.uniform(0, self.config.jitter_max)
        return delay

    async def execute(
        self,
        fn: Callable[..., T],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """Run *fn* with retries; raise last exception on exhaustion."""
        last_exc: Exception | None = None
        for attempt in range(1, self.config.max_attempts + 1):
            try:
                if asyncio.iscoroutinefunction(fn):
                    return await fn(*args, **kwargs)
                return fn(*args, **kwargs)
            except self.config.retryable_exceptions as exc:
                last_exc = exc
                if attempt < self.config.max_attempts:
                    delay = self._delay_for_attempt(attempt - 1)
                    logger.warning(
                        "Retry %d/%d for %s after %.2fs: %s",
                        attempt,
                        self.config.max_attempts,
                        fn.__qualname__,
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)
        raise last_exc  # type: ignore[misc]


def with_retry(config: RetryConfig | None = None):
    """Decorator factory: attach retry logic to any async/sync function."""
    mgr = RetryManager(config)

    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            return await mgr.execute(fn, *args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator
