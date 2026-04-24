"""Cache tool results to prevent redundant execution."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


def _make_key(tool: str, args: tuple, kwargs: dict) -> str:
    """Deterministic cache key from tool name + arguments."""
    payload = json.dumps({"tool": tool, "args": args, "kwargs": kwargs}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


@dataclass
class ActionCache:
    """In-memory cache for tool call results."""

    _store: dict[str, Any] = field(default_factory=dict, repr=False)
    hits: int = field(default=0, repr=False)
    misses: int = field(default=0, repr=False)

    def get(self, tool: str, args: tuple = (), kwargs: dict | None = None) -> Any:
        """Return cached result or sentinel if miss."""
        key = _make_key(tool, args, kwargs or {})
        if key in self._store:
            self.hits += 1
            logger.debug("ActionCache HIT: %s", tool)
            return self._store[key]
        self.misses += 1
        raise KeyError(tool)

    def set(self, tool: str, result: Any, args: tuple = (), kwargs: dict | None = None) -> None:
        """Store *result* for *tool* call."""
        key = _make_key(tool, args, kwargs or {})
        self._store[key] = result
        logger.debug("ActionCache SET: %s", tool)

    def invalidate(self, tool: str) -> None:
        """Drop all entries for *tool*."""
        to_drop = [k for k in self._store if k.startswith(tool)]
        for k in to_drop:
            del self._store[k]
        logger.debug("ActionCache INVALIDATE: %s (%s entries)", tool, len(to_drop))

    def clear(self) -> None:
        self._store.clear()
        self.hits = self.misses = 0

    def summary(self) -> dict:
        total = self.hits + self.misses
        hit_rate = self.hits / total if total else 0.0
        return {"hits": self.hits, "misses": self.misses, "hit_rate": hit_rate}
