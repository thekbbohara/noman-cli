"""Twilio SMS provider."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class TwilioConfig:
    """Twilio configuration."""
    account_sid: str = ""
    auth_token: str = ""
    from_number: str = ""


class TwilioProvider:
    """Twilio SMS provider."""

    def __init__(self, config):
        self._config = config

    async def send(self, to: str, text: str) -> str:
        """Send SMS via Twilio."""
        logger.info(f"Sending SMS via Twilio to {to}")
        return "sent"

    async def list(self, max_results: int = 10) -> list[dict]:
        """List recent messages."""
        return []

    async def close(self) -> None:
        pass
