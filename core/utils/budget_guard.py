"""Budget guard: hard stop before token exhaustion."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from core.errors import QuotaExceeded

logger = logging.getLogger(__name__)


@dataclass
class BudgetConfig:
    max_tokens: int = 128_000
    warning_threshold: float = 0.75
    hard_stop_threshold: float = 0.90
    max_turns: int = 50


@dataclass
class BudgetGuard:
    config: BudgetConfig = field(default_factory=BudgetConfig)
    _used: int = field(default=0, repr=False)
    _turns: int = field(default=0, repr=False)

    @property
    def used(self) -> int:
        return self._used

    @property
    def remaining(self) -> int:
        return self.config.max_tokens - self._used

    def check(self, incoming_tokens: int) -> None:
        """Raise QuotaExceeded if adding *incoming_tokens* breaches budget."""
        self._turns += 1
        if self._turns > self.config.max_turns:
            raise QuotaExceeded(
                f"Turn limit exceeded ({self._turns} > {self.config.max_turns})"
            )

        projected = self._used + incoming_tokens
        ratio = projected / self.config.max_tokens

        if ratio >= self.config.hard_stop_threshold:
            raise QuotaExceeded(
                f"Token budget would exceed {self.config.hard_stop_threshold:.0%}: "
                f"{projected}/{self.config.max_tokens}"
            )
        if ratio >= self.config.warning_threshold:
            logger.warning(
                "Token budget at %.0f%% (%s/%s)", ratio, projected, self.config.max_tokens
            )

    def consume(self, tokens: int) -> None:
        """Record *tokens* as used."""
        self._used += tokens
        logger.info("Budget: %s/%s tokens used", self._used, self.config.max_tokens)

    def summarize(self) -> dict:
        return {
            "used": self._used,
            "remaining": self.remaining,
            "turns": self._turns,
            "max_tokens": self.config.max_tokens,
        }
