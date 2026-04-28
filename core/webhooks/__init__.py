"""Webhook infrastructure for noman-cli.

Provides:
- WebhookServer: aiohttp-based HTTP server for receiving webhooks
- WebhookRouter: path-based routing to subscriptions
- WebhookSubscription: subscription data model with HMAC verification
- Webhook handlers for GitHub, GitLab, Bitbucket, and generic webhooks

Usage:
    from core.webhooks.server import WebhookServer
    from core.webhooks.router import WebhookRouter
    from core.webhooks.subscriptions import WebhookSubscription

    router = WebhookRouter()
    router.add_subscription(WebhookSubscription(
        name="github",
        path="/webhooks/github",
        events=["push", "pull_request"],
    ))

    server = WebhookServer(router=router, port=9090)
    await server.start()
"""

from __future__ import annotations

from core.webhooks.router import RouteMatch, WebhookRouter
from core.webhooks.server import WebhookServer
from core.webhooks.subscriptions import WebhookSubscription
from core.webhooks.handlers import (
    BitbucketHandler,
    GitHubHandler,
    GenericHandler,
    GitLabHandler,
    WebhookHandler,
    detect_source,
    get_handler,
)

__all__ = [
    # Server
    "WebhookServer",
    # Router
    "WebhookRouter",
    "RouteMatch",
    # Subscriptions
    "WebhookSubscription",
    # Handlers
    "GitHubHandler",
    "GitLabHandler",
    "BitbucketHandler",
    "GenericHandler",
    "WebhookHandler",
    "detect_source",
    "get_handler",
]
