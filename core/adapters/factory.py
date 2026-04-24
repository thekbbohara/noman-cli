"""Adapter factory and registry."""

from __future__ import annotations

import logging
from typing import Any

from core.adapters.anthropic import AnthropicAdapter
from core.adapters.base import BaseAdapter
from core.adapters.openai import OpenAIAdapter
from core.errors import ConfigError, ProviderConfigError

logger = logging.getLogger(__name__)

ADAPTER_CLASSES = {
    "openai": OpenAIAdapter,
    "anthropic": AnthropicAdapter,
    "ollama": OpenAIAdapter,
    "groq": OpenAIAdapter,
    "lite llm": OpenAIAdapter,
}


def create_adapter(config: dict[str, Any]) -> BaseAdapter:
    """Create an adapter from config dict."""
    provider_type = config.get("type", "openai").lower()
    model = config.get("model", "")

    if provider_type == "anthropic":
        if not config.get("api_key"):
            raise ProviderConfigError("Anthropic adapter requires api_key")
        return AnthropicAdapter(config)

    if provider_type in ("openai", "ollama", "groq"):
        if not config.get("api_key") and provider_type != "ollama":
            raise ProviderConfigError(f"{provider_type} adapter requires api_key")
        return OpenAIAdapter(config)

    raise ConfigError(f"Unknown provider type: {provider_type}")


def get_default_adapter_name(config: dict[str, Any]) -> str:
    """Get default adapter name from config."""
    return config.get("default", "openai")


class AdapterRegistry:
    """Registry for managing multiple adapter instances."""

    def __init__(self) -> None:
        self._adapters: dict[str, BaseAdapter] = {}
        self._defaults: dict[str, str] = {}

    def register(self, name: str, adapter: BaseAdapter, default: bool = False) -> None:
        """Register an adapter by name."""
        self._adapters[name] = adapter
        if default:
            self._defaults[name] = name

    def get(self, name: str) -> BaseAdapter | None:
        """Get adapter by name."""
        return self._adapters.get(name)

    def get_default(self, role: str | None = None) -> BaseAdapter | None:
        """Get default adapter, optionally for a specific role."""
        if role:
            name = self._defaults.get(role)
            if name:
                return self._adapters.get(name)
        return next(iter(self._adapters.values()), None) if self._adapters else None

    def list_adapters(self) -> list[str]:
        """List all registered adapter names."""
        return list(self._adapters.keys())

    async def close_all(self) -> None:
        """Close all adapters."""
        for adapter in self._adapters.values():
            await adapter.close()


_default_registry: AdapterRegistry | None = None


def get_registry() -> AdapterRegistry:
    """Get the default global registry."""
    global _default_registry
    if _default_registry is None:
        _default_registry = AdapterRegistry()
    return _default_registry
