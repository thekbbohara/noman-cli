"""Validate user configuration (config.toml)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from core.errors import ConfigError, ProviderConfigError

logger = logging.getLogger(__name__)

REQUIRED_PROVIDER_KEYS = {"base_url", "api_key", "model"}
VALID_ROLES = {"planner", "executor", "critic", "embedder"}


@dataclass(frozen=True)
class ValidatedConfig:
    providers: dict[str, dict[str, Any]]
    default_provider: str
    role_routing: dict[str, str]
    security: dict[str, Any]
    budget: dict[str, int]


class ConfigValidator:
    """Validate and normalize user config.toml."""

    def validate(self, raw: dict[str, Any]) -> ValidatedConfig:
        providers = raw.get("providers", {})
        if not providers:
            raise ConfigError("No providers configured")

        for name, cfg in providers.items():
            missing = REQUIRED_PROVIDER_KEYS - set(cfg.keys())
            if missing:
                raise ProviderConfigError(
                    f"Provider '{name}' missing keys: {missing}"
                )

        default = raw.get("model", {}).get("default", next(iter(providers)))
        if default not in providers:
            raise ConfigError(f"Default provider '{default}' not found in providers")

        role_routing = raw.get("model", {})
        for role, provider in role_routing.items():
            if role in VALID_ROLES and provider not in providers:
                raise ConfigError(
                    f"Role '{role}' routes to unknown provider '{provider}'"
                )

        security = raw.get("security", {})
        budget = raw.get("budget", {})

        logger.info("Config validated: %d providers", len(providers))
        return ValidatedConfig(
            providers=providers,
            default_provider=default,
            role_routing=role_routing,
            security=security,
            budget=budget,
        )
