"""Integration tests for gateway system."""

import pytest
import asyncio


async def test_gateway_base():
    """Test GatewayBase initialization."""
    from core.gateway.base import GatewayBase, PlatformType, GatewayStatus
    assert GatewayStatus.RUNNING.value == "running"
    assert GatewayStatus.STOPPED.value == "stopped"


async def test_message_router():
    """Test MessageRouter."""
    from core.gateway.router import MessageRouter
    router = MessageRouter()
    assert router is not None


async def test_gateway_manager():
    """Test GatewayManager."""
    from core.gateway.scheduler import GatewayManager
    manager = GatewayManager()
    assert manager is not None


async def test_telegram_gateway():
    """Test Telegram gateway import."""
    from core.gateway.telegram import TelegramGateway
    assert TelegramGateway is not None


async def test_discord_gateway():
    """Test Discord gateway import."""
    from core.gateway.discord import DiscordGateway
    assert DiscordGateway is not None


async def test_slack_gateway():
    """Test Slack gateway import."""
    from core.gateway.slack import SlackGateway
    assert SlackGateway is not None


async def test_webhook_gateway():
    """Test webhook gateway import."""
    from core.gateway.webhook import WebhookGateway
    assert WebhookGateway is not None
