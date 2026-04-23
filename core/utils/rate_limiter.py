"""Rate limiting and quota management."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict

from core.errors import RateLimitError


@dataclass(frozen=True)
class QuotaConfig:
    """Rate-limiting parameters."""

    max_requests_per_minute: int = 60
    max_requests_per_hour: int = 1000
    max_tokens_per_minute: int = 100_000
    max_tokens_per_day: int = 1_000_000
    max_concurrent_requests: int = 5
    max_tool_calls_per_turn: int = 20
    max_tool_calls_per_session: int = 100
    max_turns_per_session: int = 50


class RateLimiter:
    """Sliding-window rate limiter."""

    def __init__(self, config: QuotaConfig | None = None) -> None:
        self.config = config or QuotaConfig()
        self._request_timestamps: list[datetime] = []
        self._token_counts: Dict[date, int] = defaultdict(int)
        self._concurrent = 0
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: int = 0) -> bool:
        """Return True if the request is within limits."""
        async with self._lock:
            now = datetime.now()
            minute_ago = now - timedelta(minutes=1)
            hour_ago = now - timedelta(hours=1)

            # prune stale entries
            self._request_timestamps = [
                ts for ts in self._request_timestamps if ts > hour_ago
            ]

            reqs_last_min = sum(1 for ts in self._request_timestamps if ts > minute_ago)
            if reqs_last_min >= self.config.max_requests_per_minute:
                return False

            if len(self._request_timestamps) >= self.config.max_requests_per_hour:
                return False

            if self._concurrent >= self.config.max_concurrent_requests:
                return False

            today = now.date()
            if self._token_counts[today] + tokens > self.config.max_tokens_per_day:
                return False

            self._request_timestamps.append(now)
            self._token_counts[today] += tokens
            self._concurrent += 1
            return True

    def release(self) -> None:
        """Release a concurrent-request slot."""
        self._concurrent = max(0, self._concurrent - 1)

    async def __aenter__(self) -> RateLimiter:
        if not await self.acquire():
            raise RateLimitError("Rate limit exceeded")
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.release()


class QuotaManager:
    """High-level quota tracker for sessions, tools, and turns."""

    def __init__(self, config: QuotaConfig | None = None) -> None:
        self.config = config or QuotaConfig()
        self.rate_limiter = RateLimiter(config)
        self._tool_calls: Dict[str, int] = defaultdict(int)
        self._turn_counts: Dict[str, int] = defaultdict(int)

    async def check_tool_call(self, tool_name: str) -> None:
        """Raise if the tool call would exceed limits."""
        if self._tool_calls[tool_name] >= self.config.max_tool_calls_per_session:
            raise RateLimitError(
                f"Tool '{tool_name}' exceeded {self.config.max_tool_calls_per_session} "
                "calls per session"
            )
        if not await self.rate_limiter.acquire():
            raise RateLimitError("Rate limit exceeded")
        self._tool_calls[tool_name] += 1

    async def check_turn(self, session_id: str) -> None:
        """Raise if the turn would exceed the session limit."""
        if self._turn_counts[session_id] >= self.config.max_turns_per_session:
            raise RateLimitError(
                f"Session '{session_id}' exceeded {self.config.max_turns_per_session} turns"
            )
        if not await self.rate_limiter.acquire():
            raise RateLimitError("Rate limit exceeded")
        self._turn_counts[session_id] += 1

    def usage_report(self) -> Dict[str, int]:
        """Return current usage counters."""
        return {
            "tool_calls_total": sum(self._tool_calls.values()),
            "turns_total": sum(self._turn_counts.values()),
            **self.rate_limiter._token_counts,
        }
