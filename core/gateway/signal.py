"""Signal CLI gateway.

Uses signal-cli REST interface for messaging.
Requires signal-cli to be installed and running with REST API enabled.

See: https://github.com/asamk/signal-cli
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from core.gateway.base import GatewayBase, GatewayConfig, GatewayEvent, GatewayStatus, PlatformType

logger = logging.getLogger(__name__)

# Optional dependency
try:
    import httpx  # noqa: F401
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False


class SignalGateway(GatewayBase):
    """Signal CLI gateway via REST API.

    Configuration:
        gateway.signal.number: str - Signal phone number (E.164 format)
        gateway.signal.rest_url: str - signal-cli REST API URL (default: http://localhost:8080)
        gateway.signal.allowed_users: list[str] - Phone number allowlist
    """

    def __init__(self, config: GatewayConfig) -> None:
        super().__init__(config)
        self._number: str = config.config.get("number", "")
        self._rest_url: str = config.config.get("rest_url", "http://localhost:8080")
        self._allowed_users: list[str] = config.allowed_users or []
        self._http_client: httpx.AsyncClient | None = None
        self._polling_task: asyncio.Task | None = None
        self._last_poll_id: int = 0
        self._api_base: str = f"{self._rest_url}/api/v1"

    async def start(self) -> bool:
        """Start the Signal gateway."""
        if not self._number:
            logger.error("Signal gateway: number not configured")
            self.health.config_valid = False
            self.health.status = GatewayStatus.ERROR
            self.health.last_error = "Missing number"
            return False

        if not HAS_HTTPX:
            logger.error("Signal gateway: httpx not installed")
            self.health.config_valid = False
            self.health.status = GatewayStatus.ERROR
            self.health.last_error = "Missing httpx dependency"
            return False

        self._http_client = httpx.AsyncClient(
            base_url=self._rest_url,
            timeout=30.0,
        )
        self._running = True
        self.health.status = GatewayStatus.RUNNING
        self.health.config_valid = True
        logger.info("Signal gateway started (number: %s)", self._number)
        return True

    async def stop(self) -> None:
        """Stop the Signal gateway."""
        self._running = False
        if self._polling_task:
            self._polling_task.cancel()
            try:
                await self._polling_task
            except asyncio.CancelledError:
                pass
            self._polling_task = None
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        logger.info("Signal gateway stopped")

    async def send_message(
        self,
        user_id: str,
        channel_id: str | None,
        text: str,
        file_urls: list[str] | None = None,
    ) -> bool:
        """Send a message via signal-cli REST API."""
        if not self._http_client or not self._number:
            return False

        try:
            url = f"{self._api_base}/send"
            payload = {
                "number": user_id,
                "message": text[:32000],  # Signal message limit
            }

            if file_urls:
                for url_path in file_urls:
                    payload["file"] = url_path

            resp = await self._http_client.post(url, json=payload)
            resp.raise_for_status()
            self.record_message()
            return True

        except Exception as e:
            self.record_error(e)
            logger.error("Failed to send Signal message: %s", e)
            return False

    async def on_message(self, event: GatewayEvent) -> str | None:
        """Handle incoming Signal message."""
        self.record_message()
        return None

    async def on_command(self, event: GatewayEvent) -> str | None:
        """Handle Signal commands (via text parsing)."""
        self.record_message()
        return None

    async def on_file(self, event: GatewayEvent) -> str | None:
        """Handle incoming file from Signal."""
        self.record_message()
        return None

    async def poll_messages(self) -> None:
        """Poll for new messages (long-polling mode)."""
        while self._running:
            try:
                resp = await self._http_client.get(
                    f"{self._api_base}/receive",
                    params={"id": self._last_poll_id},
                    timeout=60.0,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    for msg in data.get("messages", []):
                        self._last_poll_id = max(self._last_poll_id, msg.get("id", self._last_poll_id))
                        from_number = msg.get("address", {}).get("number", "unknown")
                        msg_text = msg.get("message", "")

                        if self._allowed_users and from_number not in self._allowed_users:
                            continue

                        event = GatewayEvent(
                            platform=PlatformType.SIGNAL,
                            event_type="command" if msg_text.startswith("/") else "message",
                            user_id=from_number,
                            text=msg_text,
                        )
                        logger.debug("Signal event: %s from %s", event.event_type, from_number)

            except asyncio.CancelledError:
                break
            except Exception as e:
                if self._running:
                    self.record_error(e)
                    await asyncio.sleep(5)

            await asyncio.sleep(1)
