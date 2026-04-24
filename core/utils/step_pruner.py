"""Step pruner: skip redundant or circular tool calls."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class StepPruner:
    """Track tool calls to prevent redundant or circular execution."""

    _history: list[str] = field(default_factory=list, repr=False)
    _unique_calls: set[str] = field(default_factory=set, repr=False)
    max_repeats: int = 2
    max_history: int = 100

    def _key(self, tool: str, args: tuple, kwargs: dict) -> str:
        """Deterministic call fingerprint."""
        from core.utils.action_cache import _make_key
        return _make_key(tool, args, kwargs)

    def should_execute(self, tool: str, args: tuple = (), kwargs: dict | None = None) -> bool:
        """Return False if this call is redundant or circular."""
        key = self._key(tool, args, kwargs or {})

        # Count recent repeats
        recent = self._history[-self.max_repeats * 2 :]
        repeat_count = sum(1 for h in reversed(recent) if h == key)

        if repeat_count >= self.max_repeats:
            logger.warning("StepPruner BLOCKED: %s repeated %s times", tool, repeat_count)
            return False

        self._history.append(key)
        if len(self._history) > self.max_history:
            self._history.pop(0)
        self._unique_calls.add(key)
        return True

    def is_redundant(self, tool: str, args: tuple = (), kwargs: dict | None = None) -> bool:
        """Check if this exact call was already made (without updating history)."""
        key = self._key(tool, args, kwargs or {})
        return key in self._unique_calls

    def reset(self) -> None:
        self._history.clear()
        self._unique_calls.clear()
