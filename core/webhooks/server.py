"""WebhookServer: aiohttp-based HTTP server for receiving webhooks.

Provides:
- Configurable port and host
- Path-based routing via WebhookRouter
- Auth token support per webhook
- Custom header validation
- Payload transformation
- Standard response format
- Webhook delivery logging
- Webhook testing endpoint
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from aiohttp import web

from core.webhooks.handlers import detect_source, get_handler, WebhookHandler
from core.webhooks.router import RouteMatch, WebhookRouter
from core.webhooks.subscriptions import WebhookSubscription

logger = logging.getLogger(__name__)


class WebhookServer:
    """HTTP server for receiving and processing webhooks.

    Uses aiohttp to serve webhook endpoints. Routes incoming
    requests through the WebhookRouter and dispatches to
    appropriate handlers.

    Attributes:
        app: The aiohttp web application.
        runner: The aiohttp web runner.
        site: The aiohttp site (TCP site).
        router: The WebhookRouter for route matching.
        host: Bind host (default '0.0.0.0').
        port: Bind port (default 9090).
    """

    def __init__(
        self,
        router: WebhookRouter | None = None,
        host: str = "0.0.0.0",
        port: int = 9090,
    ) -> None:
        self.router = router or WebhookRouter()
        self.host = host
        self.port = port
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._started = False
        self._start_time: float = 0.0

        # Build the aiohttp app
        self._app = self._create_app()

    def _create_app(self) -> web.Application:
        """Create and configure the aiohttp web application."""
        app = web.Application()

        # Health check endpoint
        app.router.add_get("/health", self._health_handler)

        # Main webhook endpoint with path parameter
        app.router.add_post("/webhooks/{name}", self._webhook_handler)
        app.router.add_get("/webhooks/{name}", self._webhook_handler)

        # Test endpoint
        app.router.add_post("/webhooks/test/{name}", self._test_handler)

        # List subscriptions endpoint
        app.router.add_get("/webhooks", self._list_subscriptions_handler)

        # Debug/info endpoint
        app.router.add_get("/webhooks/status", self._status_handler)

        return app

    # -- HTTP handlers --

    async def _health_handler(self, request: web.Request) -> web.Response:
        """Health check endpoint."""
        uptime = time.time() - self._start_time if self._start_time else 0
        stats = self.router.get_subscription_stats()
        return web.json_response({
            "status": "ok",
            "uptime_seconds": round(uptime, 1),
            "subscriptions": stats,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        })

    async def _webhook_handler(self, request: web.Request) -> web.Response:
        """Main webhook request handler.

        Matches the request to a subscription and processes it.
        """
        name = request.match_info.get("name", "")
        path = request.path

        # Read body
        try:
            body = await request.read()
        except Exception as e:
            logger.error("Failed to read request body: %s", e)
            return web.json_response(
                {"error": "Failed to read request body"}, status=400
            )

        # Parse headers
        headers = {}
        for key, value in request.headers.items():
            headers[key] = value

        # Detect event type
        event_type = (
            request.headers.get("X-GitHub-Event")
            or request.headers.get("X-Gitlab-Event")
            or request.headers.get("X-Event-Key")
            or headers.get("X-Event-Type")
        )

        # Match to subscription
        match: RouteMatch = await self.router.process_request(
            path=path,
            method=request.method,
            headers=headers,
            payload=body,
            event_type=event_type,
        )

        if not match.is_valid:
            logger.warning("Webhook rejected: %s - %s", path, match.error)
            return web.json_response(
                {"error": match.error or "Invalid request"},
                status=400,
            )

        # Parse payload
        payload = self._parse_payload(body)

        # Detect source and get handler
        source = request.headers.get("X-Webhook-Source", detect_source(payload))
        handler: WebhookHandler = get_handler(source)

        # Process with handler
        try:
            created_jobs = handler.handle(
                subscription=match.subscription,
                payload=payload,
                event_type=event_type,
            )

            # Log success
            logger.info(
                "Webhook processed: %s -> %s (%s)",
                path,
                match.subscription.name,
                event_type or "unknown",
            )

            # Update last_triggered
            match.subscription.last_triggered = datetime.now(tz=timezone.utc)

            return web.json_response({
                "status": "accepted",
                "webhook": match.subscription.name,
                "event": event_type or "unknown",
                "created_jobs": len(created_jobs),
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            }, status=200)

        except Exception as e:
            logger.error(
                "Error processing webhook %s: %s", path, e, exc_info=True
            )
            return web.json_response(
                {"error": f"Internal error: {e}"},
                status=500,
            )

    async def _test_handler(self, request: web.Request) -> web.Response:
        """Test a webhook subscription.

        Sends a test payload to a subscription and reports the result.
        """
        name = request.match_info.get("name", "")
        subscription = self.router.get_subscription(name)

        if not subscription:
            return web.json_response(
                {"error": f"Subscription '{name}' not found"},
                status=404,
            )

        # Generate test payload
        test_payload = {
            "test": True,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "source": "noman-cli-test",
        }

        try:
            handler = get_handler("generic")
            created_jobs = handler.handle(
                subscription=subscription,
                payload=test_payload,
                event_type="test",
            )

            return web.json_response({
                "status": "success",
                "webhook": name,
                "message": "Test webhook delivered successfully",
                "created_jobs": len(created_jobs),
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            })

        except Exception as e:
            logger.error("Test webhook failed for %s: %s", name, e)
            return web.json_response(
                {"error": f"Test failed: {e}"},
                status=500,
            )

    async def _list_subscriptions_handler(self, request: web.Request) -> web.Response:
        """List all webhook subscriptions."""
        subs = self.router.list_subscriptions()
        data = [s.to_dict() for s in subs]
        stats = self.router.get_subscription_stats()

        return web.json_response({
            "count": len(data),
            "subscriptions": data,
            "stats": stats,
        })

    async def _status_handler(self, request: web.Request) -> web.Response:
        """Get server status and configuration."""
        stats = self.router.get_subscription_stats()
        return web.json_response({
            "running": self._started,
            "host": self.host,
            "port": self.port,
            "uptime_seconds": round(time.time() - self._start_time, 1) if self._start_time else 0,
            "subscriptions": stats,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        })

    # -- Helpers --

    def _parse_payload(self, body: bytes) -> Any:
        """Parse a webhook payload from bytes.

        Tries JSON first, falls back to raw bytes.

        Args:
            body: Raw request body.

        Returns:
            Parsed payload (dict, list, or bytes).
        """
        if not body:
            return {}

        try:
            return json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return body

    # -- Lifecycle --

    async def start(self) -> None:
        """Start the webhook HTTP server."""
        if self._started:
            logger.warning("WebhookServer already started")
            return

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()
        self._started = True
        self._start_time = time.time()

        logger.info(
            "WebhookServer started on %s:%d", self.host, self.port
        )

    async def stop(self) -> None:
        """Stop the webhook HTTP server."""
        if not self._started:
            return

        if self._site:
            await self._site.stop()
        if self._runner:
            await self._runner.cleanup()

        self._started = False
        logger.info("WebhookServer stopped")

    @property
    def is_running(self) -> bool:
        """Check if the server is running."""
        return self._started

    @property
    def url(self) -> str:
        """Get the base URL of the server."""
        return f"http://{self.host}:{self.port}"
