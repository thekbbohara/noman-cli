"""Home Assistant webhook gateway.

Receives events and commands from Home Assistant automations.
Sends messages back through the Home Assistant webhook API.
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


class HomeAssistantGateway(GatewayBase):
    """Home Assistant webhook gateway.

    Receives webhook events from Home Assistant automations and
    sends responses back via the Home Assistant webhook API.

    Configuration:
        gateway.homeassistant.hass_url: str - Home Assistant URL (e.g. http://homeassistant.local:8123)
        gateway.homeassistant.api_key: str - Long-lived access token
        gateway.homeassistant.webhook_id: str - Unique webhook ID
        gateway.homeassistant.allowed_areas: list[str] - Area/device allowlist
    """

    def __init__(self, config: GatewayConfig) -> None:
        super().__init__(config)
        self._hass_url: str = config.config.get("hass_url", "http://homeassistant.local:8123")
        self._api_key: str = config.config.get("api_key", "")
        self._webhook_id: str = config.config.get("webhook_id", "noman")
        self._allowed_areas: list[str] = config.config.get("allowed_areas", [])
        self._http_client: httpx.AsyncClient | None = None

    async def start(self) -> bool:
        """Start the Home Assistant gateway."""
        if not self._api_key:
            logger.error("Home Assistant gateway: api_key required")
            self.health.config_valid = False
            self.health.status = GatewayStatus.ERROR
            self.health.last_error = "Missing api_key"
            return False

        if not HAS_HTTPX:
            logger.error("Home Assistant gateway: httpx not installed")
            self.health.config_valid = False
            self.health.status = GatewayStatus.ERROR
            self.health.last_error = "Missing httpx dependency"
            return False

        try:
            self._http_client = httpx.AsyncClient(
                base_url=self._hass_url,
                timeout=30.0,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Hassio-API": "1",
                },
            )

            # Verify connectivity
            resp = await self._http_client.get("/api/states")
            if resp.status_code in (200, 401, 403):
                self._running = True
                self.health.status = GatewayStatus.RUNNING
                self.health.config_valid = True
                logger.info("Home Assistant gateway started (url: %s)", self._hass_url)
                return True
            else:
                logger.error("Home Assistant connection failed: %d", resp.status_code)
                return False

        except Exception as e:
            logger.error("Failed to start Home Assistant gateway: %s", e)
            self.health.status = GatewayStatus.ERROR
            self.health.last_error = str(e)
            return False

    async def stop(self) -> None:
        """Stop the Home Assistant gateway."""
        self._running = False
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        logger.info("Home Assistant gateway stopped")

    async def send_message(
        self,
        user_id: str,
        channel_id: str | None,
        text: str,
        file_urls: list[str] | None = None,
    ) -> bool:
        """Send a message via Home Assistant notify API."""
        if not self._http_client:
            return False

        try:
            # Try to send via notify service
            payload = {
                "target": user_id or channel_id or "",
                "message": text[:10000] if text else "",
            }

            # Use notify.webhook_* service
            url = f"/api/services/notify/webhook_{self._webhook_id}"
            resp = await self._http_client.post(url, json=payload)

            if resp.status_code in (200, 201):
                self.record_message()
                return True

            logger.warning("Home Assistant notify failed: %d", resp.status_code)
            return False

        except Exception as e:
            self.record_error(e)
            logger.error("Failed to send Home Assistant message: %s", e)
            return False

    async def on_message(self, event: GatewayEvent) -> str | None:
        """Handle incoming Home Assistant event."""
        self.record_message()
        return None

    async def on_command(self, event: GatewayEvent) -> str | None:
        """Handle Home Assistant automation trigger commands."""
        self.record_message()
        return None

    async def on_file(self, event: GatewayEvent) -> str | None:
        """Handle incoming file from Home Assistant."""
        self.record_message()
        return None

    async def process_webhook(self, payload: dict) -> bool:
        """Process a webhook event from Home Assistant."""
        try:
            # Home Assistant webhook payloads vary by automation
            data = payload.get("data", payload)
            event_type = payload.get("event_type", "")
            origin = payload.get("origin", "")

            # Extract context information
            context = data.get("context", {})
            user_id = context.get("user_id", "unknown")
            device_id = data.get("device_id", "")
            area_id = data.get("area_id", "")

            # Check allowed areas
            if self._allowed_areas and area_id and area_id not in self._allowed_areas:
                logger.info("Event from unauthorized area: %s", area_id)
                return False

            # Extract message from different payload formats
            text = (
                data.get("message") or data.get("state")
                or data.get("event") or data.get("text")
                or data.get("command") or ""
            )

            event = GatewayEvent(
                platform=PlatformType.HOMEASSISTANT,
                event_type="command" if str(text).startswith("/") else "message",
                user_id=str(user_id),
                channel_id=area_id or device_id,
                text=str(text),
                metadata={
                    "event_type": event_type,
                    "origin": str(origin),
                    "device_id": str(device_id),
                    "area_id": str(area_id),
                    "raw_payload": data,
                },
            )

            logger.debug(
                "Home Assistant event: %s from area=%s",
                event_type, area_id,
            )
            return True

        except Exception as e:
            self.record_error(e)
            return False

    async def get_state(self, entity_id: str) -> Any | None:
        """Get the current state of a Home Assistant entity."""
        if not self._http_client:
            return None
        try:
            resp = await self._http_client.get(f"/api/states/{entity_id}")
            if resp.status_code == 200:
                return resp.json()
            return None
        except Exception as e:
            logger.error("Failed to get Home Assistant state: %s", e)
            return None

    async def call_service(self, domain: str, service: str,
                           service_data: dict | None = None) -> bool:
        """Call a Home Assistant service."""
        if not self._http_client:
            return False
        try:
            payload = service_data or {}
            resp = await self._http_client.post(
                f"/api/services/{domain}/{service}",
                json=payload,
            )
            return resp.status_code in (200, 201)
        except Exception as e:
            logger.error("Failed to call Home Assistant service: %s", e)
            return False
