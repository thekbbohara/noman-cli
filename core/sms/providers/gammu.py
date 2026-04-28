"""Gammu (local GSM modem) SMS provider."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


class GammuProvider:
    """Gammu SMS provider for local GSM modem."""

    def __init__(self, config):
        self._config = config

    async def send(self, to: str, text: str) -> str:
        logger.info(f"Sending SMS via Gammu to {to}")
        return "sent"

    async def list(self, max_results: int = 10) -> list[dict]:
        return []

    async def close(self) -> None:
        pass
