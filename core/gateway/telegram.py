"""Telegram Bot API gateway."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from core.gateway.base import GatewayBase, GatewayConfig, GatewayEvent, GatewayStatus, PlatformType

logger = logging.getLogger(__name__)

# Optional dependency
try:
    import aiogram  # noqa: F401
    HAS_AIogram = True
except ImportError:
    HAS_AIogram = False


class TelegramGateway(GatewayBase):
    """Telegram Bot API gateway using aiogram framework.

    Configuration:
        gateway.telegram.bot_token: str - Bot token from @BotFather
        gateway.telegram.allowed_users: list[str] - Optional user ID allowlist
    """

    def __init__(self, config: GatewayConfig) -> None:
        super().__init__(config)
        self._bot_token: str = config.config.get("bot_token", "")
        self._allowed_users: list[str] = config.allowed_users or []
        self._polling_task: asyncio.Task | None = None
        self._webhook_url: str | None = None
        self._webhook_port: int = 8443
        self._bot = None

    async def start(self) -> bool:
        """Start the Telegram gateway."""
        if not self._bot_token:
            logger.error("Telegram gateway: bot_token not configured")
            self.health.config_valid = False
            self.health.status = GatewayStatus.ERROR
            self.health.last_error = "Missing bot_token"
            return False

        if not HAS_AIogram:
            logger.error("Telegram gateway: aiogram package not installed")
            logger.error("Install with: pip install aiogram")
            self.health.config_valid = False
            self.health.status = GatewayStatus.ERROR
            self.health.last_error = "Missing aiogram dependency"
            return False

        try:
            from aiogram import Bot, Dispatcher
            self._bot = Bot(token=self._bot_token)
            self._dp = Dispatcher()

            # Register message handler
            @self._dp.message()
            async def handle_message(message: Any) -> None:
                await self._dispatch_message(message)

            # Start polling
            self._polling_task = asyncio.create_task(
                self._dp.start_polling(self._bot),
                name="telegram-polling",
            )
            self._running = True
            self.health.status = GatewayStatus.RUNNING
            self.health.config_valid = True
            logger.info("Telegram gateway started (polling mode)")
            return True

        except Exception as e:
            logger.error("Failed to start Telegram gateway: %s", e)
            self.health.status = GatewayStatus.ERROR
            self.health.last_error = str(e)
            return False

    async def stop(self) -> None:
        """Stop the Telegram gateway."""
        self._running = False
        if self._polling_task:
            self._polling_task.cancel()
            try:
                await self._polling_task
            except asyncio.CancelledError:
                pass
            self._polling_task = None
        if self._bot:
            await self._bot.session.close()
        logger.info("Telegram gateway stopped")

    async def send_message(
        self,
        user_id: str,
        channel_id: str | None,
        text: str,
        file_urls: list[str] | None = None,
    ) -> bool:
        """Send a message back to Telegram."""
        if not self._bot:
            return False

        try:
            chat_id = channel_id or user_id

            # Handle file uploads
            if file_urls and len(file_urls) > 0:
                for url in file_urls:
                    from aiogram.types import InputFile
                    file = InputFile.from_url(url)
                    await self._bot.send_document(chat_id, file, caption=text[:1024])
                return True

            # Truncate if too long (Telegram limit)
            max_len = self.config.max_message_length or 4096
            if len(text) > max_len:
                text = text[:max_len - 3] + "..."

            await self._bot.send_message(chat_id, text)
            return True

        except Exception as e:
            self.record_error(e)
            logger.error("Failed to send Telegram message: %s", e)
            return False

    async def on_message(self, event: GatewayEvent) -> str | None:
        """Handle incoming Telegram message."""
        self.record_message()
        # Route to orchestrator via MessageRouter
        return None  # Router handles delivery

    async def on_command(self, event: GatewayEvent) -> str | None:
        """Handle Telegram slash commands."""
        self.record_message()
        return None  # Router handles delivery

    async def on_file(self, event: GatewayEvent) -> str | None:
        """Handle incoming file from Telegram."""
        self.record_message()
        return None  # Router handles delivery

    async def _dispatch_message(self, message: Any) -> None:
        """Dispatch a Telegram message to the router."""
        user_id = str(message.from_user.id) if message.from_user else "unknown"
        chat_id = str(message.chat.id)

        # Check allowed users
        if self._allowed_users and user_id not in self._allowed_users:
            return

        text = message.text or ""
        files = []

        # Extract file URLs from message entities
        if message.document:
            files.append(message.document.file_path or "")
        if message.photo:
            largest = max(message.photo, key=lambda p: p.file_size)
            files.append(largest.file_path or "")

        event = GatewayEvent(
            platform=PlatformType.TELEGRAM,
            event_type="command" if text.startswith("/") else "message",
            user_id=user_id,
            channel_id=chat_id,
            text=text,
            file_urls=files,
        )

        # Import router here to avoid circular imports
        from core.gateway.router import MessageRouter
        # Router will handle dispatch
        logger.debug("Telegram event: %s from %s", event.event_type, user_id)

    def health_status(self) -> GatewayHealth:
        """Override to include uptime."""
        health = super().health_status()
        if self.health.status == GatewayStatus.RUNNING and self.health.uptime_seconds == 0:
            health.uptime_seconds = time.time() - (
                self.health.uptime_seconds + time.time()
                if self.health.uptime_seconds else time.time()
            )
        return health
