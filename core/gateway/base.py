"""Abstract gateway base class and shared types."""

from __future__ import annotations

import asyncio
import enum
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class PlatformType(enum.Enum):
    """Supported messaging platforms."""
    TELEGRAM = "telegram"
    DISCORD = "discord"
    SLACK = "slack"
    WHATSAPP = "whatsapp"
    SIGNAL = "signal"
    MATRIX = "matrix"
    WEBHOOK = "webhook"
    FEISHU = "feishu"
    WECHAT = "wechat"
    HOMEASSISTANT = "homeassistant"


class GatewayStatus(enum.Enum):
    """Gateway lifecycle status."""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"
    RECONNECTING = "reconnecting"


@dataclass
class GatewayHealth:
    """Health status for a gateway."""
    status: GatewayStatus = GatewayStatus.STOPPED
    uptime_seconds: float = 0.0
    messages_processed: int = 0
    errors: int = 0
    last_error: str | None = None
    last_message_at: float = 0.0
    reconnect_attempts: int = 0
    config_valid: bool = True


@dataclass
class GatewayEvent:
    """Event dispatched by a gateway."""
    platform: PlatformType
    event_type: str  # message, command, file, reaction, etc.
    user_id: str
    channel_id: str | None = None
    text: str | None = None
    file_urls: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class GatewayConfig:
    """Configuration for a single gateway."""
    platform: PlatformType
    enabled: bool = False
    config: dict[str, Any] = field(default_factory=dict)
    rate_limit: float = 1.0  # minimum seconds between messages
    max_message_length: int = 4096
    session_ttl_seconds: float = 3600.0
    auto_reconnect: bool = True
    max_reconnect_attempts: int = 5
    reconnect_base_delay: float = 2.0
    health_check_interval: float = 30.0
    allowed_users: list[str] = field(default_factory=list)
    admin_users: list[str] = field(default_factory=list)


class GatewayBase(ABC):
    """Abstract base class for all platform gateways.

    Each concrete gateway must:
    - Implement on_message() for text message handling
    - Implement on_command() for slash command handling
    - Implement on_file() for file attachment handling
    - Implement start() and stop() for lifecycle management
    - Implement health_status() for status reporting
    - Implement send_message() for delivering responses back
    """

    def __init__(self, config: GatewayConfig) -> None:
        self.config = config
        self.health = GatewayHealth(status=GatewayStatus.STOPPED)
        self._running = False
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._rate_limiter: asyncio.Semaphore | None = None
        self._last_message_time: float = 0.0
        self._message_count: int = 0
        self._error_count: int = 0

    @property
    def platform(self) -> PlatformType:
        return self.config.platform

    @property
    def name(self) -> str:
        return self.config.platform.value

    @property
    def is_running(self) -> bool:
        return self._running

    @abstractmethod
    async def start(self) -> bool:
        """Start the gateway. Return True if successful."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop the gateway and clean up resources."""
        ...

    @abstractmethod
    async def send_message(
        self,
        user_id: str,
        channel_id: str | None,
        text: str,
        file_urls: list[str] | None = None,
    ) -> bool:
        """Send a response back to the user on this platform."""
        ...

    @abstractmethod
    async def on_message(
        self, event: GatewayEvent,
    ) -> str | None:
        """Handle an incoming text message. Return response text."""
        ...

    @abstractmethod
    async def on_command(
        self, event: GatewayEvent,
    ) -> str | None:
        """Handle an incoming slash command. Return response text."""
        ...

    @abstractmethod
    async def on_file(
        self, event: GatewayEvent,
    ) -> str | None:
        """Handle an incoming file attachment. Return response text."""
        ...

    def health_status(self) -> GatewayHealth:
        """Return current health status."""
        if self._running:
            self.health.status = GatewayStatus.RUNNING
        else:
            self.health.status = GatewayStatus.STOPPED
        return self.health

    def record_message(self) -> None:
        """Record a processed message."""
        self._message_count += 1
        self.health.messages_processed = self._message_count
        self.health.last_message_at = time.time()

    def record_error(self, error: Exception | str) -> None:
        """Record an error."""
        self._error_count += 1
        self.health.errors = self._error_count
        self.health.last_error = str(error)

    def _check_rate_limit(self) -> bool:
        """Check if we're within the rate limit."""
        now = time.time()
        elapsed = now - self._last_message_time
        if elapsed < self.config.rate_limit:
            return False
        self._last_message_time = now
        return True

    def _check_allowed_user(self, user_id: str) -> bool:
        """Check if user is allowed to use this gateway."""
        if not self.config.allowed_users:
            return True
        return user_id in self.config.allowed_users

    def _is_admin(self, user_id: str) -> bool:
        """Check if user is an admin."""
        return user_id in self.config.admin_users

    async def _reconnect_loop(self) -> None:
        """Auto-reconnect loop with exponential backoff."""
        delay = self.config.reconnect_base_delay
        while self.config.auto_reconnect and self._running:
            try:
                logger.info(
                    "%s: reconnecting (attempt %d, delay %.1fs)",
                    self.name,
                    self.health.reconnect_attempts + 1,
                    delay,
                )
                self.health.status = GatewayStatus.RECONNECTING
                self.health.reconnect_attempts += 1
                await asyncio.sleep(delay)
                success = await self.start()
                if success:
                    self.health.status = GatewayStatus.RUNNING
                    self.health.reconnect_attempts = 0
                    delay = self.config.reconnect_base_delay
                else:
                    delay = min(delay * 2, 300.0)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.record_error(e)
                delay = min(delay * 2, 300.0)

    async def _ensure_rate_limit(self) -> bool:
        """Acquire rate limit slot, waiting if necessary."""
        if not self.config.rate_limit or self.config.rate_limit <= 0:
            return True
        acquired = False
        while not acquired:
            if self._check_rate_limit():
                return True
            await asyncio.sleep(self.config.rate_limit)
        return True

    @property
    def status_report(self) -> dict[str, Any]:
        """Return a JSON-serializable status report."""
        health = self.health_status()
        return {
            "platform": self.name,
            "status": health.status.value,
            "uptime_seconds": health.uptime_seconds,
            "messages_processed": health.messages_processed,
            "errors": health.errors,
            "last_error": health.last_error,
            "reconnect_attempts": health.reconnect_attempts,
            "config_valid": health.config_valid,
            "enabled": self.config.enabled,
        }
