"""Integration tests for webhooks."""

import pytest


async def test_webhook_server():
    """Test WebhookServer."""
    from core.webhooks.server import WebhookServer
    server = WebhookServer()
    assert server is not None


async def test_webhook_router():
    """Test WebhookRouter."""
    from core.webhooks.router import WebhookRouter
    router = WebhookRouter()
    assert router is not None


async def test_webhook_subscriptions():
    """Test WebhookSubscription."""
    from core.webhooks.subscriptions import WebhookSubscription
    sub = WebhookSubscription(name="test", path="/test")
    assert sub.name == "test"
