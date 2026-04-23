"""Circuit breaker + error boundary pattern."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Coroutine, TypeVar

from . import CircuitBreakerOpenError, NoManError

logger = logging.getLogger(__name__)
T = TypeVar("T")


class State(Enum):
    CLOSED = auto()
    OPEN = auto()
    HALF_OPEN = auto()


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5
    recovery_timeout_sec: float = 30.0
    half_open_max_calls: int = 3


class CircuitBreaker:
    """Prevent cascading failures by opening after repeated errors."""

    def __init__(self, name: str, config: CircuitBreakerConfig | None = None) -> None:
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self._state = State.CLOSED
        self._failures = 0
        self._last_failure_time: float = 0.0
        self._half_open_calls = 0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> State:
        return self._state

    async def _transition_to(self, new_state: State) -> None:
        old = self._state
        self._state = new_state
        logger.warning("Circuit breaker %s: %s → %s", self.name, old.name, new_state.name)
        if new_state == State.OPEN:
            self._last_failure_time = time.monotonic()
        elif new_state == State.HALF_OPEN:
            self._half_open_calls = 0

    async def call(self, fn: Callable[..., Coroutine[Any, Any, T]], *args: Any, **kwargs: Any) -> T:
        async with self._lock:
            if self._state == State.OPEN:
                if time.monotonic() - self._last_failure_time >= self.config.recovery_timeout_sec:
                    await self._transition_to(State.HALF_OPEN)
                else:
                    raise CircuitBreakerOpenError(
                        f"Circuit breaker '{self.name}' is OPEN"
                    )
            elif self._state == State.HALF_OPEN:
                if self._half_open_calls >= self.config.half_open_max_calls:
                    raise CircuitBreakerOpenError(
                        f"Circuit breaker '{self.name}' is HALF_OPEN (limit reached)"
                    )
                self._half_open_calls += 1

        try:
            result = await fn(*args, **kwargs)
        except Exception as exc:
            async with self._lock:
                self._failures += 1
                if self._failures >= self.config.failure_threshold:
                    await self._transition_to(State.OPEN)
            raise

        # Success path
        async with self._lock:
            if self._state == State.HALF_OPEN:
                await self._transition_to(State.CLOSED)
                self._failures = 0
            elif self._state == State.CLOSED:
                self._failures = max(0, self._failures - 1)

        return result


class ErrorBoundary:
    """Isolate a subsystem so its failures don't propagate."""

    def __init__(self, name: str, breaker: CircuitBreaker | None = None) -> None:
        self.name = name
        self.breaker = breaker or CircuitBreaker(name)

    async def execute(
        self,
        fn: Callable[..., Coroutine[Any, Any, T]],
        *args: Any,
        default: T | None = None,
        **kwargs: Any,
    ) -> T | None:
        """Run *fn* inside the boundary, returning *default* on failure."""
        try:
            return await self.breaker.call(fn, *args, **kwargs)
        except (NoManError, CircuitBreakerOpenError) as exc:
            logger.error("ErrorBoundary %s caught: %s", self.name, exc)
            return default
        except Exception as exc:
            logger.exception("ErrorBoundary %s caught unexpected: %s", self.name, exc)
            return default
