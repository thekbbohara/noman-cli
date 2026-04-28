"""Slack Bolt gateway."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from core.gateway.base import GatewayBase, GatewayConfig, GatewayEvent, GatewayStatus, PlatformType

logger = logging.getLogger(__name__)

# Optional dependency
try:
    from slack_bolt import App  # noqa: F401
    from slack_bolt.adapter.asyncio import AsyncSocketModeHandler  # noqa: F401
    HAS_SLACK = True
except ImportError:
    HAS_SLACK = False


class SlackGateway(GatewayBase):
    """Slack Bot gateway using Bolt framework.

    Configuration:
        gateway.slack.bot_token: str - Bot token (xoxb-...)
        gateway.slack.app_token: str - App-level token (xapp-...)
        gateway.slack.signing_secret: str - Signing secret from Slack app
        gateway.slack.allowed_users: list[str] - Optional user ID allowlist
    """

    def __init__(self, config: GatewayConfig) -> None:
        super().__init__(config)
        self._bot_token: str = config.config.get("bot_token", "")
        self._app_token: str = config.config.get("app_token", "")
        self._signing_secret: str = config.config.get("signing_secret", "")
        self._allowed_users: list[str] = config.allowed_users or []
        self._app: Any = None
        self._handler: Any = None
        self._running_task: asyncio.Task | None = None

    async def start(self) -> bool:
        """Start the Slack gateway."""
        if not self._app_token or not self._signing_secret:
            logger.error("Slack gateway: app_token and signing_secret required")
            self.health.config_valid = False
            self.health.status = GatewayStatus.ERROR
            self.health.last_error = "Missing app_token or signing_secret"
            return False

        if not HAS_SLACK:
            logger.error("Slack gateway: slack-bolt not installed")
            logger.error("Install with: pip install slack-bolt")
            self.health.config_valid = False
            self.health.status = GatewayStatus.ERROR
            self.health.last_error = "Missing slack-bolt dependency"
            return False

        try:
            from slack_bolt import App
            from slack_bolt.adapter.asyncio import AsyncSocketModeHandler

            self._app = App(
                token=self._bot_token,
                app_token=self._app_token,
                signing_secret=self._signing_secret,
            )

            # Message handler
            @self._app.event("message")
            async def handle_message(message: dict, say: Any) -> None:
                await self._on_slack_message(message, say)

            # Slash command handler
            @self._app.command("/noman")
            async def handle_command(ack: Any, body: dict, say: Any) -> None:
                await ack()
                response = await self._on_slack_command(body)
                if response:
                    await say(response)

            # Direct message handler
            @self._app.event("app_mention")
            async def handle_mention(message: dict, say: Any) -> None:
                await self._on_slack_message(message, say)

            self._handler = AsyncSocketModeHandler(self._app, self._app_token)
            self._running_task = asyncio.create_task(
                self._handler.start(),
                name="slack-socketmode",
            )
            self._running = True
            self.health.status = GatewayStatus.RUNNING
            self.health.config_valid = True
            logger.info("Slack gateway started (Socket Mode)")
            return True

        except Exception as e:
            logger.error("Failed to start Slack gateway: %s", e)
            self.health.status = GatewayStatus.ERROR
            self.health.last_error = str(e)
            return False

    async def stop(self) -> None:
        """Stop the Slack gateway."""
        self._running = False
        if self._handler:
            await self._handler.stop()
        if self._running_task:
            self._running_task.cancel()
            try:
                await self._running_task
            except asyncio.CancelledError:
                pass
            self._running_task = None
        logger.info("Slack gateway stopped")

    async def send_message(
        self,
        user_id: str,
        channel_id: str | None,
        text: str,
        file_urls: list[str] | None = None,
    ) -> bool:
        """Send a message back to Slack."""
        if not self._app or not channel_id:
            return False

        try:
            max_len = self.config.max_message_length or 4096
            if len(text) > max_len:
                text = text[:max_len - 3] + "..."

            from slack_sdk import WebClient
            client = WebClient(token=self._bot_token)
            client.chat_postMessage(channel=channel_id, text=text)

            if file_urls:
                for url in file_urls:
                    client.files_upload(
                        channels=channel_id,
                        file=url,
                        title="Shared file",
                    )
            return True

        except Exception as e:
            self.record_error(e)
            logger.error("Failed to send Slack message: %s", e)
            return False

    async def on_message(self, event: GatewayEvent) -> str | None:
        """Handle incoming Slack message."""
        self.record_message()
        return None

    async def on_command(self, event: GatewayEvent) -> str | None:
        """Handle Slack slash commands."""
        self.record_message()
        return None

    async def on_file(self, event: GatewayEvent) -> str | None:
        """Handle incoming file from Slack."""
        self.record_message()
        return None

    async def _on_slack_message(self, message: dict, say: Any) -> None:
        """Process incoming Slack message."""
        user_id = message.get("user", "unknown")
        channel_id = message.get("channel", "")
        text = message.get("text", "") or ""

        if self._allowed_users and user_id not in self._allowed_users:
            return

        event = GatewayEvent(
            platform=PlatformType.SLACK,
            event_type="command" if text.startswith("/") else "message",
            user_id=user_id,
            channel_id=channel_id,
            text=text,
        )
        logger.debug("Slack event: %s from %s", event.event_type, user_id)

    async def _on_slack_command(self, body: dict) -> str | None:
        """Process incoming Slack slash command."""
        user_id = body.get("user", {}).get("id", "unknown")
        text = body.get("text", "") or ""

        event = GatewayEvent(
            platform=PlatformType.SLACK,
            event_type="command",
            user_id=user_id,
            channel_id=body.get("channel", {}).get("id", ""),
            text=text,
        )
        logger.debug("Slack command: %s from %s", text, user_id)
        return None
