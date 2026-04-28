"""Message routing between gateways and the noman orchestrator."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable

from core.gateway.base import (
    GatewayBase,
    GatewayConfig,
    GatewayEvent,
    GatewayStatus,
    PlatformType,
)

logger = logging.getLogger(__name__)


@dataclass
class GatewaySession:
    """Per-user per-platform session state."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    user_id: str = ""
    platform: PlatformType = PlatformType.WEBHOOK
    channel_id: str | None = None
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    turn_count: int = 0
    is_active: bool = True
    context: dict[str, Any] = field(default_factory=dict)

    def touch(self) -> None:
        """Update last active timestamp."""
        self.last_active = time.time()

    def is_expired(self, ttl: float = 3600.0) -> bool:
        """Check if session has expired."""
        return (time.time() - self.last_active) > ttl


class SessionManager:
    """Manages per-user per-platform sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, GatewaySession] = {}
        self._lock = asyncio.Lock()

    def _session_key(self, user_id: str, platform: PlatformType, channel_id: str | None = None) -> str:
        if channel_id:
            return f"{platform.value}:{channel_id}:{user_id}"
        return f"{platform.value}:{user_id}"

    async def get_session(
        self,
        user_id: str,
        platform: PlatformType,
        channel_id: str | None = None,
        ttl: float = 3600.0,
    ) -> GatewaySession:
        """Get or create a session for a user on a platform."""
        key = self._session_key(user_id, platform, channel_id)
        async with self._lock:
            session = self._sessions.get(key)
            if session and not session.is_expired(ttl):
                session.touch()
                return session
            # Clean expired session
            if session:
                session.is_active = False
            new_session = GatewaySession(
                user_id=user_id,
                platform=platform,
                channel_id=channel_id,
            )
            self._sessions[key] = new_session
            return new_session

    async def close_session(self, user_id: str, platform: PlatformType, channel_id: str | None = None) -> None:
        """Close and remove a session."""
        key = self._session_key(user_id, platform, channel_id)
        async with self._lock:
            if key in self._sessions:
                self._sessions[key].is_active = False
                del self._sessions[key]

    async def list_active_sessions(self) -> list[GatewaySession]:
        """List all active sessions."""
        async with self._lock:
            return [s for s in self._sessions.values() if s.is_active]

    async def count_sessions(self) -> int:
        """Count active sessions."""
        async with self._lock:
            return sum(1 for s in self._sessions.values() if s.is_active)


# Type alias for response callback
ResponseCallback = Callable[[str, str | None, str, list[str] | None], bool]


class MessageRouter:
    """Routes messages from any gateway to the noman orchestrator.

    Manages the message lifecycle:
    1. Gateway dispatches events to router
    2. Router resolves session
    3. Router parses /commands
    4. Router calls orchestrator for text
    5. Router delivers response back via gateway
    """

    def __init__(self) -> None:
        self._sessions = SessionManager()
        self._gateways: dict[PlatformType, GatewayBase] = {}
        self._response_callbacks: dict[PlatformType, ResponseCallback] = {}
        self._command_handlers: dict[str, Callable] = {}
        self._running = False
        self._lock = asyncio.Lock()

    @property
    def session_manager(self) -> SessionManager:
        return self._sessions

    def register_gateway(self, gateway: GatewayBase) -> None:
        """Register a gateway for message routing."""
        self._gateways[gateway.platform] = gateway
        logger.info("Registered gateway: %s", gateway.name)

    def unregister_gateway(self, platform: PlatformType) -> None:
        """Unregister a gateway."""
        self._gateways.pop(platform, None)
        self._response_callbacks.pop(platform, None)
        logger.info("Unregistered gateway: %s", platform.value)

    def set_response_callback(
        self, platform: PlatformType, callback: ResponseCallback,
    ) -> None:
        """Set the response delivery callback for a gateway."""
        self._response_callbacks[platform] = callback

    def register_command(self, command: str, handler: Callable) -> None:
        """Register a custom command handler."""
        self._command_handlers[command] = handler

    async def handle_event(self, event: GatewayEvent) -> bool:
        """Handle a gateway event. Returns True if processed."""
        gateway = self._gateways.get(event.platform)
        if not gateway:
            logger.warning("No gateway registered for platform %s", event.platform)
            return False

        # Check user permissions
        if not gateway._check_allowed_user(event.user_id):
            return False

        gateway.record_message()

        try:
            if event.event_type == "command":
                response = await gateway.on_command(event)
            elif event.event_type == "file":
                response = await gateway.on_file(event)
            else:
                response = await gateway.on_message(event)

            if response and self._response_callbacks.get(event.platform):
                callback = self._response_callbacks[event.platform]
                try:
                    callback(
                        event.user_id,
                        event.channel_id,
                        response,
                        event.file_urls,
                    )
                except Exception as e:
                    logger.error(
                        "Response delivery failed for %s: %s",
                        event.platform.value, e,
                    )

            return True

        except Exception as e:
            gateway.record_error(e)
            logger.error("Error handling %s event from %s: %s",
                         event.event_type, event.platform.value, e)
            return False

    async def process_message(
        self,
        gateway: GatewayBase,
        user_id: str,
        channel_id: str | None,
        text: str,
        file_urls: list[str] | None = None,
    ) -> str | None:
        """Process a message through the orchestrator pipeline.

        Handles:
        - /command parsing
        - Session resolution
        - Orchestrator invocation
        - Response delivery
        """
        # Check rate limit
        if not gateway._check_rate_limit():
            return "Rate limited. Please slow down."

        # Check user permissions
        if not gateway._check_allowed_user(user_id):
            return "You are not authorized to use this gateway."

        # Parse slash commands
        if text.startswith("/"):
            return await self._handle_command(gateway, user_id, channel_id, text)

        # Handle file uploads
        if file_urls and file_urls:
            event = GatewayEvent(
                platform=gateway.platform,
                event_type="file",
                user_id=user_id,
                channel_id=channel_id,
                text=text or "",
                file_urls=file_urls,
            )
            response = await gateway.on_file(event)
            if response and self._response_callbacks.get(gateway.platform):
                callback = self._response_callbacks[gateway.platform]
                callback(user_id, channel_id, response, file_urls)
            return response

        # Normal message: route through orchestrator
        session = await self._sessions.get_session(
            user_id, gateway.platform, channel_id,
        )
        session.turn_count += 1
        session.touch()

        event = GatewayEvent(
            platform=gateway.platform,
            event_type="message",
            user_id=user_id,
            channel_id=channel_id,
            text=text,
        )
        response = await gateway.on_message(event)

        if response and self._response_callbacks.get(gateway.platform):
            callback = self._response_callbacks[gateway.platform]
            callback(user_id, channel_id, response, None)

        return response

    async def _handle_command(
        self,
        gateway: GatewayBase,
        user_id: str,
        channel_id: str | None,
        text: str,
    ) -> str | None:
        """Parse and dispatch slash commands."""
        parts = text.strip().split(" ", 1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        # Built-in commands
        builtin_commands = {
            "/help": lambda: self._cmd_help(gateway),
            "/reset": lambda: self._cmd_reset(gateway, user_id, channel_id),
            "/status": lambda: self._cmd_status(gateway),
            "/model": lambda: self._cmd_model(args),
            "/sessions": lambda: self._cmd_sessions(user_id, gateway.platform),
        }

        # Custom handlers take priority
        if command in self._command_handlers:
            return self._command_handlers[command](args)

        if command in builtin_commands:
            return builtin_commands[command]()

        return f"Unknown command: {command}. Use /help for available commands."

    @staticmethod
    def _cmd_help(gateway: GatewayBase) -> str:
        """Help command."""
        return (
            f"**{gateway.name} commands:**\n"
            f"  /help          - Show this help\n"
            f"  /reset         - Reset current session\n"
            f"  /status        - Show gateway status\n"
            f"  /model <name>  - Switch model\n"
            f"  /sessions      - List active sessions\n"
            f"  /clear         - Clear conversation context\n"
            f"  /info          - Show bot info\n"
        )

    async def _cmd_reset(
        self,
        gateway: GatewayBase,
        user_id: str,
        channel_id: str | None,
    ) -> str:
        """Reset session command."""
        await self._sessions.close_session(user_id, gateway.platform, channel_id)
        return "Session reset. Starting fresh."

    @staticmethod
    def _cmd_status(gateway: GatewayBase) -> str:
        """Status command."""
        health = gateway.health_status()
        return (
            f"**{gateway.name} Status:**\n"
            f"  Status: {health.status.value}\n"
            f"  Messages: {health.messages_processed}\n"
            f"  Errors: {health.errors}\n"
            f"  Reconnects: {health.reconnect_attempts}\n"
            f"  Config valid: {health.config_valid}"
        )

    @staticmethod
    def _cmd_model(args: str) -> str:
        """Model switch command (placeholder)."""
        if args:
            return f"Model set to: {args}"
        return "Usage: /model <model_name>"

    @staticmethod
    async def _cmd_sessions(user_id: str, platform: PlatformType) -> str:
        """List active sessions."""
        sessions = await SessionManager().list_active_sessions()
        count = sum(1 for s in sessions if s.user_id == user_id and s.platform == platform)
        return f"Active sessions for you: {count}"

    async def start(self) -> None:
        """Start the message router."""
        self._running = True
        logger.info("MessageRouter started, %d gateways registered", len(self._gateways))

    async def stop(self) -> None:
        """Stop the message router."""
        self._running = False
        logger.info("MessageRouter stopped")

    @property
    def status_report(self) -> dict[str, Any]:
        """Router status report."""
        return {
            "running": self._running,
            "gateways": {
                p.value: g.health_status().status.value
                for p, g in self._gateways.items()
            },
            "active_sessions": 0,  # Will be updated by session manager
        }
