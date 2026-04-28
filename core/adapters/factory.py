"""Adapter factory and registry."""

from __future__ import annotations

import logging
from typing import Any

from core.adapters.anthropic import AnthropicAdapter
from core.adapters.base import BaseAdapter
from core.adapters.custom import CustomAdapter
from core.adapters.dashscope import DashScopeAdapter
from core.adapters.deepseek import DeepSeekAdapter
from core.adapters.gemini import GeminiAdapter
from core.adapters.glm import GLMAdapter
from core.adapters.huggingface import HuggingFaceAdapter
from core.adapters.kimi import KimiAdapter
from core.adapters.minimax import MiniMaxAdapter
from core.adapters.minimax_cn import MiniMaxCNAdapter
from core.adapters.mistral import MistralAdapter
from core.adapters.nvidia import NvidiaAdapter
from core.adapters.openai import OpenAIAdapter
from core.adapters.perplexity import PerplexityAdapter
from core.adapters.sambanova import SambaNovaAdapter
from core.adapters.together import TogetherAdapter
from core.adapters.voyage import VoyageAdapter
from core.adapters.xai import XAIAdapter
from core.errors import ConfigError, ProviderConfigError

logger = logging.getLogger(__name__)

# ── Adapter class mapping ──

ADAPTER_CLASSES = {
    # OpenAI-compatible (generic)
    "openai": OpenAIAdapter,
    "ollama": OpenAIAdapter,
    "groq": OpenAIAdapter,
    "lite llm": OpenAIAdapter,
    "lite_llm": OpenAIAdapter,
    "custom": CustomAdapter,
    # Provider-specific adapters
    "anthropic": AnthropicAdapter,
    "gemini": GeminiAdapter,
    "deepseek": DeepSeekAdapter,
    "xai": XAIAdapter,
    "huggingface": HuggingFaceAdapter,
    "kimi": KimiAdapter,
    "minimax": MiniMaxAdapter,
    "minimax_cn": MiniMaxCNAdapter,
    "dashscope": DashScopeAdapter,
    "glm": GLMAdapter,
    "mistral": MistralAdapter,
    "together": TogetherAdapter,
    "sambanova": SambaNovaAdapter,
    "nvidia": NvidiaAdapter,
    "voyage": VoyageAdapter,
    "perplexity": PerplexityAdapter,
}


def create_adapter(config: dict[str, Any]) -> BaseAdapter:
    """Create an adapter from config dict.

    Supports all registered providers. Provider type is determined by
    config['type'] (lowercased). Falls back to 'openai' if not specified.

    Args:
        config: Provider configuration dict. Must include 'type' and 'api_key'.

    Returns:
        A BaseAdapter instance configured for the specified provider.

    Raises:
        ProviderConfigError: If required config fields are missing.
        ConfigError: If the provider type is unknown.
    """
    provider_type = config.get("type", "openai").lower().strip()
    model = config.get("model", "")

    # Map known provider types to their specific adapter class
    if provider_type == "anthropic":
        if not config.get("api_key"):
            raise ProviderConfigError("Anthropic adapter requires api_key")
        return AnthropicAdapter(config)

    if provider_type == "gemini":
        if not config.get("api_key"):
            raise ProviderConfigError("Gemini adapter requires api_key")
        return GeminiAdapter(config)

    if provider_type == "deepseek":
        if not config.get("api_key"):
            raise ProviderConfigError("DeepSeek adapter requires api_key")
        return DeepSeekAdapter(config)

    if provider_type == "xai":
        if not config.get("api_key"):
            raise ProviderConfigError("xAI adapter requires api_key")
        return XAIAdapter(config)

    if provider_type == "huggingface":
        if not config.get("api_key"):
            raise ProviderConfigError("HuggingFace adapter requires api_key")
        if not config.get("base_url"):
            raise ProviderConfigError("HuggingFace adapter requires base_url")
        return HuggingFaceAdapter(config)

    if provider_type == "kimi":
        if not config.get("api_key"):
            raise ProviderConfigError("Kimi adapter requires api_key")
        return KimiAdapter(config)

    if provider_type == "minimax":
        if not config.get("api_key"):
            raise ProviderConfigError("MiniMax adapter requires api_key")
        return MiniMaxAdapter(config)

    if provider_type == "minimax_cn":
        if not config.get("api_key"):
            raise ProviderConfigError("MiniMax CN adapter requires api_key")
        return MiniMaxCNAdapter(config)

    if provider_type == "dashscope":
        if not config.get("api_key"):
            raise ProviderConfigError("DashScope adapter requires api_key")
        return DashScopeAdapter(config)

    if provider_type == "glm":
        if not config.get("api_key"):
            raise ProviderConfigError("GLM adapter requires api_key")
        return GLMAdapter(config)

    if provider_type == "mistral":
        if not config.get("api_key"):
            raise ProviderConfigError("Mistral adapter requires api_key")
        return MistralAdapter(config)

    if provider_type == "together":
        if not config.get("api_key"):
            raise ProviderConfigError("Together AI adapter requires api_key")
        return TogetherAdapter(config)

    if provider_type == "sambanova":
        if not config.get("api_key"):
            raise ProviderConfigError("SambaNova adapter requires api_key")
        return SambaNovaAdapter(config)

    if provider_type == "nvidia":
        if not config.get("api_key"):
            raise ProviderConfigError("NVIDIA adapter requires api_key")
        return NvidiaAdapter(config)

    if provider_type == "voyage":
        if not config.get("api_key"):
            raise ProviderConfigError("Voyage AI adapter requires api_key")
        return VoyageAdapter(config)

    if provider_type == "perplexity":
        if not config.get("api_key"):
            raise ProviderConfigError("Perplexity adapter requires api_key")
        return PerplexityAdapter(config)

    if provider_type == "custom":
        if not config.get("base_url"):
            raise ProviderConfigError("Custom adapter requires base_url")
        return CustomAdapter(config)

    # Generic OpenAI-compatible providers (ollama, groq, lite-llm, etc.)
    if provider_type in ("openai", "ollama", "groq", "lite llm", "lite_llm"):
        if provider_type != "ollama" and not config.get("api_key"):
            raise ProviderConfigError(f"{provider_type} adapter requires api_key")
        return OpenAIAdapter(config)

    # Unknown provider type
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


def get_supported_providers() -> list[str]:
    """Return a list of all supported provider type strings."""
    return sorted(ADAPTER_CLASSES.keys())
