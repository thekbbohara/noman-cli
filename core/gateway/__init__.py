"""Multi-platform gateway system for noman-cli.

Routes messages from Telegram, Discord, Slack, WhatsApp, Signal, Matrix,
Feishu, WeChat, and Home Assistant into the noman orchestrator.

Usage:
    from core.gateway import GatewayManager, GatewayBase
    manager = GatewayManager()
    await manager.start()

CLI:
    noman gateway run      - Start configured gateways
    noman gateway status   - Show gateway status
    noman gateway setup    - Configure platforms
    noman gateway install  - Install as a service
"""

from __future__ import annotations

from core.gateway.base import GatewayBase, GatewayStatus, PlatformType
from core.gateway.router import MessageRouter, SessionManager
from core.gateway.scheduler import GatewayManager

__all__ = [
    "GatewayBase",
    "GatewayStatus",
    "PlatformType",
    "MessageRouter",
    "SessionManager",
    "GatewayManager",
]
