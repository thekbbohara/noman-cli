"""WhatsApp Cloud API gateway."""

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


class WhatsAppGateway(GatewayBase):
    """WhatsApp Business Cloud API gateway.

    Uses the WhatsApp Cloud API directly via HTTP calls.
    Webhook-based: you set up a webhook URL in the Meta developer portal.

    Configuration:
        gateway.whatsapp.phone_number_id: str - Phone number ID
        gateway.whatsapp.business_account_id: str - Business account ID
        gateway.whatsapp.verify_token: str - Verification token for webhook
        gateway.whatsapp.access_token: str - Temporary access token
        gateway.whatsapp.webhook_secret: str - Webhook verification secret
        gateway.whatsapp.allowed_users: list[str] - Phone number allowlist
    """

    def __init__(self, config: GatewayConfig) -> None:
        super().__init__(config)
        self._phone_number_id: str = config.config.get("phone_number_id", "")
        self._business_account_id: str = config.config.get("business_account_id", "")
        self._verify_token: str = config.config.get("verify_token", "")
        self._access_token: str = config.config.get("access_token", "")
        self._webhook_secret: str = config.config.get("webhook_secret", "")
        self._allowed_users: list[str] = config.allowed_users or []
        self._http_client: httpx.AsyncClient | None = None
        self._running_task: asyncio.Task | None = None
        self._api_base: str = "https://graph.facebook.com/v18.0"

    async def start(self) -> bool:
        """Start the WhatsApp gateway."""
        if not self._phone_number_id or not self._access_token:
            logger.error("WhatsApp gateway: phone_number_id and access_token required")
            self.health.config_valid = False
            self.health.status = GatewayStatus.ERROR
            self.health.last_error = "Missing phone_number_id or access_token"
            return False

        if not HAS_HTTPX:
            logger.error("WhatsApp gateway: httpx not installed")
            self.health.config_valid = False
            self.health.status = GatewayStatus.ERROR
            self.health.last_error = "Missing httpx dependency"
            return False

        self._http_client = httpx.AsyncClient(timeout=30.0)
        self._running = True
        self.health.status = GatewayStatus.RUNNING
        self.health.config_valid = True
        logger.info(
            "WhatsApp gateway started (phone: %s)",
            self._phone_number_id,
        )
        return True

    async def stop(self) -> None:
        """Stop the WhatsApp gateway."""
        self._running = False
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        if self._running_task:
            self._running_task.cancel()
            try:
                await self._running_task
            except asyncio.CancelledError:
                pass
            self._running_task = None
        logger.info("WhatsApp gateway stopped")

    async def send_message(
        self,
        user_id: str,
        channel_id: str | None,
        text: str,
        file_urls: list[str] | None = None,
    ) -> bool:
        """Send a message via WhatsApp Cloud API."""
        if not self._http_client or not self._phone_number_id:
            return False

        try:
            url = f"{self._api_base}/{self._phone_number_id}/messages"
            headers = {
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json",
            }

            if file_urls and len(file_urls) > 0:
                # Send media message
                media_url = file_urls[0]
                media_type = "document" if media_url.endswith((".pdf", ".doc", ".docx")) else "image"
                payload = {
                    "messaging_product": "whatsapp",
                    "to": user_id,
                    "type": media_type,
                    media_type: {"link": media_url},
                    "caption": text[:1024] if text else "",
                }
            else:
                payload = {
                    "messaging_product": "whatsapp",
                    "to": user_id,
                    "type": "text",
                    "text": {
                        "preview_url": False,
                        "body": text[:6144],  # WhatsApp text limit
                    },
                }

            resp = await self._http_client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            self.record_message()
            return True

        except Exception as e:
            self.record_error(e)
            logger.error("Failed to send WhatsApp message: %s", e)
            return False

    async def on_message(self, event: GatewayEvent) -> str | None:
        """Handle incoming WhatsApp message."""
        self.record_message()
        return None

    async def on_command(self, event: GatewayEvent) -> str | None:
        """Handle WhatsApp commands (via text parsing)."""
        self.record_message()
        return None

    async def on_file(self, event: GatewayEvent) -> str | None:
        """Handle incoming file from WhatsApp."""
        self.record_message()
        return None

    async def verify_webhook(self, challenge: str, mode: str, token: str,
                            hub: str) -> str | None:
        """Handle webhook verification from Meta."""
        if mode == "subscribe" and token == self._verify_token:
            return challenge
        return None

    async def process_webhook(self, payload: dict) -> bool:
        """Process an incoming webhook payload from Meta."""
        try:
            entries = payload.get("entry", [])
            for entry in entries:
                changes = entry.get("changes", [])
                for change in changes:
                    value = change.get("value", {})
                    messages = value.get("messages", [])
                    for msg in messages:
                        from_user = value.get("contacts", [{}])[0].get("wa_id", "unknown")
                        msg_text = msg.get("text", {}).get("body", "")
                        msg_type = msg.get("type", "text")

                        if msg_type == "text":
                            event = GatewayEvent(
                                platform=PlatformType.WHATSAPP,
                                event_type="command" if msg_text.startswith("/") else "message",
                                user_id=from_user,
                                text=msg_text,
                            )
                        elif msg_type == "document":
                            event = GatewayEvent(
                                platform=PlatformType.WHATSAPP,
                                event_type="file",
                                user_id=from_user,
                                text=msg.get("document", {}).get("caption", ""),
                                file_urls=[msg.get("document", {}).get("url", "")],
                            )
                        else:
                            continue

                        logger.debug(
                            "WhatsApp event: %s from %s", msg_type, from_user
                        )

            return True
        except Exception as e:
            self.record_error(e)
            return False
