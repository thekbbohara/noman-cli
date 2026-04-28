"""Feishu/Lark gateway.

Feishu is a Chinese enterprise messaging platform (similar to Slack).
Uses Feishu Open API for bot interactions.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
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


class FeishuGateway(GatewayBase):
    """Feishu/Lark Bot gateway.

    Configuration:
        gateway.feishu.app_id: str - App ID from Feishu Developer Console
        gateway.feishu.app_secret: str - App Secret
        gateway.feishu.verify_token: str - Verify token for events
        gateway.feishu.encoding_aes_key: str - Optional encryption key
        gateway.feishu.allowed_users: list[str] - User ID allowlist
    """

    def __init__(self, config: GatewayConfig) -> None:
        super().__init__(config)
        self._app_id: str = config.config.get("app_id", "")
        self._app_secret: str = config.config.get("app_secret", "")
        self._verify_token: str = config.config.get("verify_token", "")
        self._encoding_aes_key: str = config.config.get("encoding_aes_key", "")
        self._allowed_users: list[str] = config.allowed_users or []
        self._access_token: str = ""
        self._http_client: httpx.AsyncClient | None = None
        self._token_refresh_task: asyncio.Task | None = None

    async def start(self) -> bool:
        """Start the Feishu gateway."""
        if not self._app_id or not self._app_secret:
            logger.error("Feishu gateway: app_id and app_secret required")
            self.health.config_valid = False
            self.health.status = GatewayStatus.ERROR
            self.health.last_error = "Missing app_id or app_secret"
            return False

        if not HAS_HTTPX:
            logger.error("Feishu gateway: httpx not installed")
            self.health.config_valid = False
            self.health.status = GatewayStatus.ERROR
            self.health.last_error = "Missing httpx dependency"
            return False

        try:
            self._http_client = httpx.AsyncClient(timeout=30.0)
            # Get access token
            await self._refresh_token()

            self._running = True
            self.health.status = GatewayStatus.RUNNING
            self.health.config_valid = True
            logger.info("Feishu gateway started (app: %s)", self._app_id)
            return True

        except Exception as e:
            logger.error("Failed to start Feishu gateway: %s", e)
            self.health.status = GatewayStatus.ERROR
            self.health.last_error = str(e)
            return False

    async def stop(self) -> None:
        """Stop the Feishu gateway."""
        self._running = False
        if self._token_refresh_task:
            self._token_refresh_task.cancel()
            try:
                await self._token_refresh_task
            except asyncio.CancelledError:
                pass
            self._token_refresh_task = None
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        logger.info("Feishu gateway stopped")

    async def send_message(
        self,
        user_id: str,
        channel_id: str | None,
        text: str,
        file_urls: list[str] | None = None,
    ) -> bool:
        """Send a message via Feishu Open API."""
        if not self._http_client or not self._access_token:
            return False

        try:
            receive_id = channel_id or user_id
            url = "https://open.feishu.cn/open-apis/im/v1/messages"
            params = {"receive_id_type": "open_id"}

            # Get open_id if we have a user_id
            if channel_id and not channel_id.startswith("ou_"):
                receive_id = channel_id

            content = json.dumps({
                "text": text[:20000] if text else "",
            })

            headers = {
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json; charset=utf-8",
            }

            payload = {
                "receive_id": receive_id,
                "content": content,
                "msg_type": "text",
            }

            resp = await self._http_client.post(
                f"{url}/receive/{receive_id}/messages",
                json=payload,
                headers=headers,
                params=params,
            )
            resp.raise_for_status()
            self.record_message()
            return True

        except Exception as e:
            self.record_error(e)
            logger.error("Failed to send Feishu message: %s", e)
            return False

    async def on_message(self, event: GatewayEvent) -> str | None:
        """Handle incoming Feishu message."""
        self.record_message()
        return None

    async def on_command(self, event: GatewayEvent) -> str | None:
        """Handle Feishu interactive message commands."""
        self.record_message()
        return None

    async def on_file(self, event: GatewayEvent) -> str | None:
        """Handle incoming file from Feishu."""
        self.record_message()
        return None

    async def process_event(self, payload: dict) -> bool:
        """Process an incoming Feishu event (webhook)."""
        try:
            # Verify token for event subscription
            header = payload.get("header", {})
            token = header.get("token", "")
            if token and token != self._verify_token:
                logger.warning("Feishu event verification failed")
                return False

            event_type = header.get("event_type", "")
            event_data = payload.get("event", {})
            sender = event_data.get("sender", {})
            sender_id = sender.get("sender_id", {}).get("open_id", "unknown")

            msg_data = event_data.get("message", {})
            msg_type = msg_data.get("message_type", "")
            msg_content = json.loads(msg_data.get("content", "{}"))
            text = msg_content.get("text", "")

            # Handle different message types
            if msg_type == "text":
                event = GatewayEvent(
                    platform=PlatformType.FEISHU,
                    event_type="command" if text.startswith("/") else "message",
                    user_id=sender_id,
                    channel_id=event_data.get("conversation_id", ""),
                    text=text,
                )
            elif msg_type == "file":
                file_key = msg_content.get("file_key", "")
                event = GatewayEvent(
                    platform=PlatformType.FEISHU,
                    event_type="file",
                    user_id=sender_id,
                    channel_id=event_data.get("conversation_id", ""),
                    text=f"Received file: {file_key}",
                )
            else:
                event = GatewayEvent(
                    platform=PlatformType.FEISHU,
                    event_type="message",
                    user_id=sender_id,
                    channel_id=event_data.get("conversation_id", ""),
                    text=f"[{msg_type} message]",
                )

            logger.debug("Feishu event: %s from %s", event_type, sender_id)
            return True

        except Exception as e:
            self.record_error(e)
            return False

    async def _refresh_token(self) -> None:
        """Refresh the Feishu access token."""
        if not self._http_client:
            return
        try:
            resp = await self._http_client.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={
                    "app_id": self._app_id,
                    "app_secret": self._app_secret,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            self._access_token = data.get("tenant_access_token", "")
            expires = data.get("expire", 7200)
            logger.info("Feishu token refreshed (expires in %ds)", expires)
        except Exception as e:
            logger.error("Failed to refresh Feishu token: %s", e)
