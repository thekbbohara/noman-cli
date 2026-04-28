"""Status bar widget for TUI."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class StatusBarConfig:
    """Status bar configuration."""
    show_model: bool = True
    show_tokens: bool = True
    show_time: bool = True
    show_tools: bool = True
    show_gateway: bool = True
    show_profile: bool = True


class StatusBar:
    """Enhanced status bar for TUI."""

    def __init__(self, config: StatusBarConfig | None = None):
        self._config = config or StatusBarConfig()
        self._model: str = "unknown"
        self._tokens: int = 0
        self._tool_count: int = 0
        self._gateway_status: str = "disconnected"
        self._profile: str = "default"

    def update_model(self, model: str) -> None:
        """Update displayed model."""
        self._model = model

    def update_tokens(self, tokens: int) -> None:
        """Update token count."""
        self._tokens = tokens

    def update_tool_count(self, count: int) -> None:
        """Update tool count."""
        self._tool_count = count

    def update_gateway_status(self, status: str) -> None:
        """Update gateway status."""
        self._gateway_status = status

    def update_profile(self, profile: str) -> None:
        """Update profile display."""
        self._profile = profile

    def get_status_text(self) -> str:
        """Get current status bar text."""
        parts = []
        if self._config.show_profile:
            parts.append(f"[profile:{self._profile}]")
        if self._config.show_model:
            parts.append(f"[model:{self._model}]")
        if self._config.show_tokens:
            parts.append(f"[tokens:{self._tokens}]")
        if self._config.show_tools:
            parts.append(f"[tools:{self._tool_count}]")
        if self._config.show_gateway:
            status_color = "green" if self._gateway_status == "connected" else "red"
            parts.append(f"[{status_color}:{self._gateway_status}]")
        if self._config.show_time:
            parts.append(f"[{datetime.now().strftime('%H:%M:%S')}]")
        return " | ".join(parts)
