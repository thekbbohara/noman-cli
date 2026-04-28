"""TUI plugin system."""

from __future__ import annotations

import logging
import importlib
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class Plugin:
    """A TUI plugin."""
    name: str
    version: str
    enabled: bool = True
    description: str = ""
    author: str = ""
    config: dict = field(default_factory=dict)


class PluginManager:
    """TUI plugin manager."""

    def __init__(self):
        self._plugins: dict[str, Plugin] = {}
        self._hooks: dict[str, list] = {}

    def register(self, plugin: Plugin) -> None:
        """Register a plugin."""
        self._plugins[plugin.name] = plugin

    def enable(self, name: str) -> bool:
        """Enable a plugin."""
        if name in self._plugins:
            self._plugins[name].enabled = True
            return True
        return False

    def disable(self, name: str) -> bool:
        """Disable a plugin."""
        if name in self._plugins:
            self._plugins[name].enabled = False
            return True
        return False

    def list_plugins(self) -> list[dict]:
        """List all plugins."""
        return [
            {
                "name": p.name,
                "version": p.version,
                "enabled": p.enabled,
                "description": p.description,
            }
            for p in self._plugins.values()
        ]

    def load_hook(self, hook_name: str, *args, **kwargs):
        """Load and execute a hook."""
        results = []
        for plugin in self._plugins.values():
            if plugin.enabled and hook_name in plugin.config:
                try:
                    results.append(plugin.config[hook_name](*args, **kwargs))
                except Exception as e:
                    logger.error(f"Plugin {plugin.name} hook {hook_name} failed: {e}")
        return results
