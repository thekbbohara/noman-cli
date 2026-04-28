"""WeChat (Enterprise/Official Account) gateway.

Supports WeChat Enterprise (WeCom) and Official Account APIs.
WeChat Enterprise uses a different API from personal WeChat.
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


class WechatGateway(GatewayBase):
    """WeChat Enterprise gateway.

    Configuration:
        gateway.wechat.app_id: str - CorpID (enterprise ID)
        gateway.wechat.app_secret: str - Secret for API access
        gateway.wechat.agent_id: str - Agent ID for the bot application
        gateway.wechat.encoding_aes_key: str - Encoding AES key
        gateway.wechat.token: str - Verification token
        gateway.wechat.allowed_users: list[str] - User ID allowlist
    """

    def __init__(self, config: GatewayConfig) -> None:
        super().__init__(config)
        self._corp_id: str = config.config.get("app_id", "")
        self._app_secret: str = config.config.get("app_secret", "")
        self._agent_id: str = config.config.get("agent_id", "")
        self._encoding_aes_key: str = config.config.get("encoding_aes_key", "")
        self._token: str = config.config.get("token", "")
        self._allowed_users: list[str] = config.allowed_users or []
        self._access_token: str = ""
        self._http_client: httpx.AsyncClient | None = None
        self._token_refresh_task: asyncio.Task | None = None

    async def start(self) -> bool:
        """Start the WeChat gateway."""
        if not self._corp_id or not self._app_secret:
            logger.error("WeChat gateway: app_id and app_secret required")
            self.health.config_valid = False
            self.health.status = GatewayStatus.ERROR
            self.health.last_error = "Missing app_id or app_secret"
            return False

        if not HAS_HTTPX:
            logger.error("WeChat gateway: httpx not installed")
            self.health.config_valid = False
            self.health.status = GatewayStatus.ERROR
            self.health.last_error = "Missing httpx dependency"
            return False

        try:
            self._http_client = httpx.AsyncClient(timeout=30.0)
            await self._refresh_token()

            self._running = True
            self.health.status = GatewayStatus.RUNNING
            self.health.config_valid = True
            logger.info("WeChat gateway started (corp: %s)", self._corp_id)
            return True

        except Exception as e:
            logger.error("Failed to start WeChat gateway: %s", e)
            self.health.status = GatewayStatus.ERROR
            self.health.last_error = str(e)
            return False

    async def stop(self) -> None:
        """Stop the WeChat gateway."""
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
        logger.info("WeChat gateway stopped")

    async def send_message(
        self,
        user_id: str,
        channel_id: str | None,
        text: str,
        file_urls: list[str] | None = None,
    ) -> bool:
        """Send a message via WeChat Enterprise API."""
        if not self._http_client or not self._access_token:
            return False

        try:
            to_user = user_id or "@all"
            url = "https://qyapi.weixin.qq.com/cgi-bin/message/send"
            params = {"access_token": self._access_token}

            content = text[:20000] if text else ""

            payload = {
                "touser": to_user,
                "msgtype": "text",
                "agentid": self._agent_id,
                "text": {"content": content},
                "safe": 0,
            }

            resp = await self._http_client.post(url, params=params, json=payload)
            resp.raise_for_status()
            data = resp.json()

            if data.get("errcode") != 0:
                logger.error("WeChat API error: %s", data)
                return False

            self.record_message()
            return True

        except Exception as e:
            self.record_error(e)
            logger.error("Failed to send WeChat message: %s", e)
            return False

    async def on_message(self, event: GatewayEvent) -> str | None:
        """Handle incoming WeChat message."""
        self.record_message()
        return None

    async def on_command(self, event: GatewayEvent) -> str | None:
        """Handle WeChat enterprise message commands."""
        self.record_message()
        return None

    async def on_file(self, event: GatewayEvent) -> str | None:
        """Handle incoming file from WeChat."""
        self.record_message()
        return None

    async def process_event(self, payload: dict, timestamp: str,
                            nonce: str, signature: str) -> bool:
        """Process incoming WeChat event callback."""
        try:
            # Verify signature
            if self._token:
                items = sorted([self._token, timestamp, nonce])
                computed = hmac.new(
                    self._token.encode(),
                    "".join(items).encode(),
                    hashlib.sha1,
                ).hexdigest()
                if computed != signature:
                    logger.warning("WeChat signature verification failed")
                    return False

            # Parse event
            msg_type = payload.get("MsgType", "")
            from_user = payload.get("FromUserName", "unknown")
            content = payload.get("Content", "")

            if msg_type == "text":
                event = GatewayEvent(
                    platform=PlatformType.WECHAT,
                    event_type="command" if content.startswith("/") else "message",
                    user_id=from_user,
                    text=content,
                )
            elif msg_type == "image":
                media_id = payload.get("MediaId", "")
                event = GatewayEvent(
                    platform=PlatformType.WECHAT,
                    event_type="file",
                    user_id=from_user,
                    text=f"Received image: {media_id}",
                )
            else:
                event = GatewayEvent(
                    platform=PlatformType.WECHAT,
                    event_type="message",
                    user_id=from_user,
                    text=f"[{msg_type} message]",
                )

            logger.debug("WeChat event: %s from %s", msg_type, from_user)
            return True

        except Exception as e:
            self.record_error(e)
            return False

    async def _refresh_token(self) -> None:
        """Refresh WeChat access token."""
        if not self._http_client:
            return
        try:
            resp = await self._http_client.get(
                "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
                params={
                    "corpid": self._corp_id,
                    "corpsecret": self._app_secret,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("errcode") == 0:
                self._access_token = data.get("access_token", "")
                expires = data.get("expires_in", 7200)
                logger.info("WeChat token refreshed (expires in %ds)", expires)
            else:
                logger.error("WeChat token refresh failed: %s", data)
        except Exception as e:
            logger.error("Failed to refresh WeChat token: %s", e)
