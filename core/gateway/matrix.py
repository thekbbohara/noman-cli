"""Matrix (Element) gateway.

Uses matrix-nio or matrix-client libraries for Matrix protocol.
Supports both homeserver and bridge modes.
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
    from matrix_client.client import MatrixClient  # noqa: F401
    from matrix_client.room import Room  # noqa: F401
    HAS_MATRIX = True
except ImportError:
    try:
        import matrix_sdk  # noqa: F401
        HAS_MATRIX = True
    except ImportError:
        HAS_MATRIX = False


class MatrixGateway(GatewayBase):
    """Matrix (Element) gateway.

    Configuration:
        gateway.matrix.homeserver: str - Homeserver URL (e.g. https://matrix.org)
        gateway.matrix.user: str - Bot user ID (e.g. @bot:matrix.org)
        gateway.matrix.password: str - Bot password
        gateway.matrix.device_id: str - Optional device ID
        gateway.matrix.allowed_users: list[str] - User ID allowlist
        gateway.matrix.allowed_rooms: list[str] - Room ID allowlist
    """

    def __init__(self, config: GatewayConfig) -> None:
        super().__init__(config)
        self._homeserver: str = config.config.get("homeserver", "https://matrix.org")
        self._user: str = config.config.get("user", "")
        self._password: str = config.config.get("password", "")
        self._device_id: str = config.config.get("device_id", "")
        self._allowed_users: list[str] = config.allowed_users or []
        self._allowed_rooms: list[str] = config.config.get("allowed_rooms", [])
        self._client: Any = None
        self._running_task: asyncio.Task | None = None

    async def start(self) -> bool:
        """Start the Matrix gateway."""
        if not self._user:
            logger.error("Matrix gateway: user not configured")
            self.health.config_valid = False
            self.health.status = GatewayStatus.ERROR
            self.health.last_error = "Missing user"
            return False

        if not HAS_MATRIX:
            logger.error("Matrix gateway: matrix-sdk not installed")
            logger.error("Install with: pip install matrix-nio")
            self.health.config_valid = False
            self.health.status = GatewayStatus.ERROR
            self.health.last_error = "Missing matrix-sdk dependency"
            return False

        try:
            from matrix_client.client import MatrixClient
            self._client = MatrixClient(self._homeserver)

            # Login
            if self._password:
                login_resp = self._client.login(
                    self._user, self._password,
                    device_id=self._device_id,
                    initial_device_display_name="noman-bot",
                )
            else:
                # Token-based login
                token = self._client.access_token
                if not token:
                    raise ValueError("No login credentials provided")

            self._client.sync_forever(timeout=30000)
            self._running = True
            self.health.status = GatewayStatus.RUNNING
            self.health.config_valid = True
            logger.info("Matrix gateway started (user: %s)", self._user)
            return True

        except Exception as e:
            logger.error("Failed to start Matrix gateway: %s", e)
            self.health.status = GatewayStatus.ERROR
            self.health.last_error = str(e)
            return False

    async def stop(self) -> None:
        """Stop the Matrix gateway."""
        self._running = False
        if self._client:
            self._client.sync_stop()
        if self._running_task:
            self._running_task.cancel()
            try:
                await self._running_task
            except asyncio.CancelledError:
                pass
            self._running_task = None
        logger.info("Matrix gateway stopped")

    async def send_message(
        self,
        user_id: str,
        channel_id: str | None,
        text: str,
        file_urls: list[str] | None = None,
    ) -> bool:
        """Send a message via Matrix."""
        if not self._client or not channel_id:
            return False

        try:
            room = self._client.get_room(channel_id)
            max_len = self.config.max_message_length or 4096
            if len(text) > max_len:
                text = text[:max_len - 3] + "..."

            if file_urls and len(file_urls) > 0:
                # Upload files
                for url in file_urls:
                    room.send_file(url, caption=text[:1024] if text else None)
            else:
                room.send_text_message(text)

            self.record_message()
            return True

        except Exception as e:
            self.record_error(e)
            logger.error("Failed to send Matrix message: %s", e)
            return False

    async def on_message(self, event: GatewayEvent) -> str | None:
        """Handle incoming Matrix message."""
        self.record_message()
        return None

    async def on_command(self, event: GatewayEvent) -> str | None:
        """Handle Matrix m.room.message with command prefix."""
        self.record_message()
        return None

    async def on_file(self, event: GatewayEvent) -> str | None:
        """Handle incoming file from Matrix."""
        self.record_message()
        return None
