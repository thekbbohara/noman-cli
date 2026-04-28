"""SMS client for sending and receiving messages."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SMSConfig:
    """SMS configuration."""
    provider: str = "twilio"
    account_sid: str = ""
    auth_token: str = ""
    from_number: str = ""
    api_key: str = ""
    api_secret: str = ""


class SMSClient:
    """SMS client supporting multiple providers."""

    def __init__(self, config: SMSConfig | None = None):
        self._config = config or SMSConfig()
        self._provider = None

    async def initialize(self) -> bool:
        """Initialize the SMS provider."""
        provider = self._config.provider.lower()
        if provider == "twilio":
            from core.sms.providers.twilio import TwilioProvider
            self._provider = TwilioProvider(self._config)
        elif provider == "plivo":
            from core.sms.providers.plivo import PlivoProvider
            self._provider = PlivoProvider(self._config)
        elif provider == "gammu":
            from core.sms.providers.gammu import GammuProvider
            self._provider = GammuProvider(self._config)
        else:
            logger.error(f"Unknown SMS provider: {provider}")
            return False
        return self._provider is not None

    async def send(self, to: str, text: str) -> str:
        """Send an SMS message."""
        if not self._provider:
            await self.initialize()
        if not self._provider:
            return "error: not initialized"
        return await self._provider.send(to, text)

    async def list(self, max_results: int = 10) -> list[dict]:
        """List recent SMS messages."""
        if not self._provider:
            await self.initialize()
        if not self._provider:
            return []
        return await self._provider.list(max_results)

    async def close(self) -> None:
        """Close the client."""
        if self._provider:
            await self._provider.close()
