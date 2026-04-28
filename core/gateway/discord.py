"""Discord Bot gateway."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from core.gateway.base import GatewayBase, GatewayConfig, GatewayEvent, GatewayStatus, PlatformType

logger = logging.getLogger(__name__)

# Optional dependency
try:
    import discord  # noqa: F401
    HAS_DISCORD = True
except ImportError:
    HAS_DISCORD = False


class DiscordGateway(GatewayBase):
    """Discord Bot gateway using discord.py library.

    Configuration:
        gateway.discord.bot_token: str - Bot token from Discord Developer Portal
        gateway.discord.client_id: str - Optional client ID for slash commands
        gateway.discord.allowed_users: list[str] - Optional user ID allowlist
    """

    def __init__(self, config: GatewayConfig) -> None:
        super().__init__(config)
        self._bot_token: str = config.config.get("bot_token", "")
        self._client_id: str = config.config.get("client_id", "")
        self._allowed_users: list[str] = config.allowed_users or []
        self._bot: Any = None
        self._running_task: asyncio.Task | None = None

    async def start(self) -> bool:
        """Start the Discord gateway."""
        if not self._bot_token:
            logger.error("Discord gateway: bot_token not configured")
            self.health.config_valid = False
            self.health.status = GatewayStatus.ERROR
            self.health.last_error = "Missing bot_token"
            return False

        if not HAS_DISCORD:
            logger.error("Discord gateway: discord.py not installed")
            logger.error("Install with: pip install discord.py")
            self.health.config_valid = False
            self.health.status = GatewayStatus.ERROR
            self.health.last_error = "Missing discord.py dependency"
            return False

        try:
            from discord import Bot, Intents, ApplicationCommand
            intents = Intents.default()
            intents.message_content = True
            intents.members = True

            self._bot = Bot(intents=intents)

            @self._bot.event
            async def on_ready() -> None:
                logger.info("Discord bot ready as %s", self._bot.user)
                self.health.status = GatewayStatus.RUNNING
                self.health.config_valid = True

            @self._bot.event
            async def on_message(message: discord.Message) -> None:
                await self._dispatch_message(message)

            # Register slash commands if client_id provided
            if self._client_id:
                # Commands will be registered on first ready
                pass

            self._running_task = asyncio.create_task(
                self._bot.start(self._bot_token),
                name="discord-bot",
            )
            self._running = True
            logger.info("Discord gateway started")
            return True

        except Exception as e:
            logger.error("Failed to start Discord gateway: %s", e)
            self.health.status = GatewayStatus.ERROR
            self.health.last_error = str(e)
            return False

    async def stop(self) -> None:
        """Stop the Discord gateway."""
        self._running = False
        if self._bot:
            await self._bot.close()
        if self._running_task:
            self._running_task.cancel()
            try:
                await self._running_task
            except asyncio.CancelledError:
                pass
            self._running_task = None
        logger.info("Discord gateway stopped")

    async def send_message(
        self,
        user_id: str,
        channel_id: str | None,
        text: str,
        file_urls: list[str] | None = None,
    ) -> bool:
        """Send a message back to Discord."""
        if not self._bot or not channel_id:
            return False

        try:
            import discord
            channel = await self._bot.fetch_channel(int(channel_id))

            # Handle file uploads
            if file_urls and len(file_urls) > 0:
                for url in file_urls:
                    from io import BytesIO
                    import httpx
                    async with httpx.AsyncClient() as http:
                        resp = await http.get(url)
                        if resp.status_code == 200:
                            file_obj = discord.File(
                                BytesIO(resp.content),
                                filename=url.split("/")[-1],
                            )
                            await channel.send(text[:2000] or "File attached", file=file_obj)
                return True

            # Discord limit
            max_len = self.config.max_message_length or 2000
            if len(text) > max_len:
                text = text[:max_len - 3] + "..."
            await channel.send(text)
            return True

        except Exception as e:
            self.record_error(e)
            logger.error("Failed to send Discord message: %s", e)
            return False

    async def on_message(self, event: GatewayEvent) -> str | None:
        """Handle incoming Discord message."""
        self.record_message()
        return None

    async def on_command(self, event: GatewayEvent) -> str | None:
        """Handle Discord slash commands."""
        self.record_message()
        return None

    async def on_file(self, event: GatewayEvent) -> str | None:
        """Handle incoming file from Discord."""
        self.record_message()
        return None

    async def _dispatch_message(self, message: Any) -> None:
        """Dispatch a Discord message to the router."""
        user_id = str(message.author.id)
        chat_id = str(message.channel.id)

        if self._allowed_users and user_id not in self._allowed_users:
            return

        text = message.content or ""
        files = [a.url for a in message.attachments if a.url] if message.attachments else []

        event = GatewayEvent(
            platform=PlatformType.DISCORD,
            event_type="command" if text.startswith("/") else "message",
            user_id=user_id,
            channel_id=chat_id,
            text=text,
            file_urls=files,
        )
        logger.debug("Discord event: %s from %s", event.event_type, user_id)
