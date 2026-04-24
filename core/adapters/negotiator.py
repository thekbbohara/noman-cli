"""Capability negotiation and validation."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from core.adapters.base import BaseAdapter, ModelCapabilities

logger = logging.getLogger(__name__)

DEFAULT_CONTEXT_LIMITS = {
    "claude-sonnet": 100000,
    "claude-opus": 100000,
    "gpt-4-turbo": 100000,
    "gpt-4o": 100000,
    "gpt-4o-mini": 16000,
    "gpt-3.5-turbo": 16385,
    "codellama": 16384,
    "mixtral": 32768,
    "llama": 4096,
    "mistral": 8192,
    "qwen": 8192,
    "default": 8192,
}


@dataclass
class CapabilityCache:
    """Cache for probed capabilities with TTL."""

    capabilities: ModelCapabilities
    probed_at: float = field(default_factory=time.time)
    ttl_sec: float = 3600.0

    def is_expired(self) -> bool:
        return time.time() - self.probed_at > self.ttl_sec


class CapabilityNegotiator:
    """Negotiate and validate model capabilities."""

    def __init__(self, ttl_sec: float = 3600.0) -> None:
        self._cache: dict[str, CapabilityCache] = {}
        self._ttl = ttl_sec

    async def negotiate(
        self, adapter: BaseAdapter, force_refresh: bool = False
    ) -> ModelCapabilities:
        """Get capabilities, using cache if available."""
        key = adapter.config.get("model", "")

        if not force_refresh:
            cached = self._cache.get(key)
            if cached and not cached.is_expired():
                logger.debug(f"Using cached capabilities for {key}")
                return cached.capabilities

        caps = await adapter.probe_capabilities()
        self._cache[key] = CapabilityCache(
            capabilities=caps,
            ttl_sec=self._ttl,
        )
        logger.info(f"Probed capabilities for {key}: {caps}")
        return caps

    def get_conservative_limit(self, model: str) -> int:
        """Get conservative context limit for model."""
        base = model.split("-")[0].split(":")[0]
        return DEFAULT_CONTEXT_LIMITS.get(base, DEFAULT_CONTEXT_LIMITS["default"])

    def validate_budget(
        self, model: str, requested_budget: int
    ) -> tuple[int, list[str]]:
        """
        Validate requested budget against conservative limits.

        Returns (adjusted_budget, warnings).
        """
        limit = self.get_conservative_limit(model)
        warnings = []

        if requested_budget > limit:
            warnings.append(
                f"Requested {requested_budget} > conservative limit {limit}"
            )

        adjusted = min(requested_budget, int(limit * 0.9))
        if adjusted < requested_budget:
            warnings.append(
                f"Budget adjusted to {adjusted} (90% of {limit} for safety)"
            )

        return adjusted, warnings

    def clear_cache(self, model: str | None = None) -> None:
        """Clear capability cache."""
        if model:
            self._cache.pop(model, None)
        else:
            self._cache.clear()
