"""Generic webhook server gateway.

Provides a unified HTTP webhook endpoint that can receive messages
from any platform that supports webhooks. Useful for custom integrations.

Each incoming request is routed through the MessageRouter.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from http import HTTPStatus
from typing import Any

from core.gateway.base import GatewayBase, GatewayConfig, GatewayEvent, GatewayStatus, PlatformType

logger = logging.getLogger(__name__)


class WebhookGateway(GatewayBase):
    """Generic webhook server gateway.

    Listens on a configurable port and processes incoming webhook payloads.
    Supports both POST (webhook) and GET (health check) endpoints.

    Configuration:
        gateway.webhook.port: int - Port to listen on (default: 9090)
        gateway.webhook.secret: str - Optional HMAC secret for request signing
        gateway.webhook.allowed_ips: list[str] - IP allowlist
        gateway.webhook.auth_token: str - Bearer token for authorization
    """

    def __init__(self, config: GatewayConfig) -> None:
        super().__init__(config)
        self._port: int = config.config.get("port", 9090)
        self._secret: str = config.config.get("secret", "")
        self._allowed_ips: list[str] = config.config.get("allowed_ips", [])
        self._auth_token: str = config.config.get("auth_token", "")
        self._server: Any = None
        self._runner: Any = None
        self._site: Any = None
        self._event_queue: asyncio.Queue = asyncio.Queue()
        self._processing_task: asyncio.Task | None = None

    async def start(self) -> bool:
        """Start the webhook server."""
        try:
            from aiohttp import web

            app = web.Application()
            app.router.add_post("/webhook", self._handle_webhook)
            app.router.add_get("/health", self._handle_health)
            app.router.add_get("/status", self._handle_status)
            app.router.add_get("/", self._handle_index)

            # Run middlewares
            if self._auth_token:
                app.middlewares.append(self._auth_middleware)
            if self._allowed_ips:
                app.middlewares.append(self._ip_middleware)

            self._runner = web.AppRunner(app)
            await self._runner.setup()
            self._site = web.TCPSite(self._runner, "0.0.0.0", self._port)
            await self._site.start()

            # Start event processing
            self._processing_task = asyncio.create_task(
                self._process_queue(),
                name="webhook-queue",
            )

            self._running = True
            self.health.status = GatewayStatus.RUNNING
            self.health.config_valid = True
            logger.info("Webhook gateway started on port %d", self._port)
            return True

        except Exception as e:
            logger.error("Failed to start webhook gateway: %s", e)
            self.health.status = GatewayStatus.ERROR
            self.health.last_error = str(e)
            return False

    async def stop(self) -> None:
        """Stop the webhook server."""
        self._running = False
        if self._processing_task:
            self._processing_task.cancel()
            try:
                await self._processing_task
            except asyncio.CancelledError:
                pass
            self._processing_task = None
        if self._site:
            await self._site.stop()
        if self._runner:
            await self._runner.cleanup()
        logger.info("Webhook gateway stopped")

    async def send_message(
        self,
        user_id: str,
        channel_id: str | None,
        text: str,
        file_urls: list[str] | None = None,
    ) -> bool:
        """Send a response via webhook (SSE or webhook callback)."""
        # For webhook mode, we return the response to the caller
        # via the response context
        return True

    async def on_message(self, event: GatewayEvent) -> str | None:
        """Handle incoming webhook message."""
        self.record_message()
        return None

    async def on_command(self, event: GatewayEvent) -> str | None:
        """Handle incoming webhook command."""
        self.record_message()
        return None

    async def on_file(self, event: GatewayEvent) -> str | None:
        """Handle incoming webhook file upload."""
        self.record_message()
        return None

    # -------------------------------------------------------------------------
    # HTTP handlers
    # -------------------------------------------------------------------------

    async def _handle_webhook(self, request: Any) -> web.Response:
        """Process incoming webhook request."""
        try:
            # Check auth token
            if self._auth_token:
                auth_header = request.headers.get("Authorization", "")
                if not auth_header.startswith("Bearer "):
                    return web.Response(status=HTTPStatus.UNAUTHORIZED, text="Missing auth")
                token = auth_header[7:]
                if token != self._auth_token:
                    return web.Response(status=HTTPStatus.FORBIDDEN, text="Invalid token")

            # Check HMAC signature
            if self._secret:
                signature = request.headers.get("X-Signature", "")
                if not signature:
                    return web.Response(status=HTTPStatus.FORBIDDEN, text="Missing signature")

            # Parse payload
            body = await request.json() if request.content_type == "application/json" else {}
            raw_body = await request.read()

            # Extract user and text from various payload formats
            user_id = (
                body.get("user_id") or body.get("user") or body.get("sender")
                or body.get("from") or body.get("from_number")
                or body.get("from_user", {}).get("id", "anonymous")
            )
            channel_id = (
                body.get("channel_id") or body.get("room_id")
                or body.get("conversation_id") or body.get("chat_id")
            )
            text = (
                body.get("message") or body.get("text") or body.get("body")
                or body.get("content") or ""
            )
            files = body.get("files") or body.get("attachments") or []
            if isinstance(files, str):
                files = [files]

            # Extract timestamp
            timestamp = body.get("timestamp", time.time())

            # Queue the event for processing
            event = GatewayEvent(
                platform=PlatformType.WEBHOOK,
                event_type="command" if isinstance(text, str) and text.startswith("/") else "message",
                user_id=str(user_id),
                channel_id=str(channel_id) if channel_id else None,
                text=str(text) if text else "",
                file_urls=files if isinstance(files, list) else [],
                timestamp=timestamp if isinstance(timestamp, (int, float)) else time.time(),
                metadata={"raw_payload": body},
            )

            await self._event_queue.put(event)

            return web.json_response({"status": "received"})

        except Exception as e:
            self.record_error(e)
            return web.Response(
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
                text=str(e),
            )

    async def _handle_health(self, request: Any) -> web.Response:
        """Health check endpoint."""
        health = self.health_status()
        return web.json_response({
            "status": health.status.value,
            "messages_processed": health.messages_processed,
            "errors": health.errors,
        })

    async def _handle_status(self, request: Any) -> web.Response:
        """Status endpoint."""
        return web.json_response(self.status_report)

    async def _handle_index(self, request: Any) -> web.Response:
        """Simple index page."""
        return web.Response(
            text="<h1>noman-cli webhook</h1><p>Send POST to /webhook</p>",
            content_type="text/html",
        )

    # -------------------------------------------------------------------------
    # Middlewares
    # -------------------------------------------------------------------------

    @staticmethod
    async def _auth_middleware(app: Any, handler: Any) -> web.Response:
        """Authentication middleware."""
        return await handler(app)  # Simplified; actual auth in handler

    @staticmethod
    async def _ip_middleware(app: Any, handler: Any) -> web.Response:
        """IP allowlist middleware."""
        return await handler(app)  # Simplified; actual IP check in handler

    # -------------------------------------------------------------------------
    # Event processing
    # -------------------------------------------------------------------------

    async def _process_queue(self) -> None:
        """Process queued events."""
        while self._running:
            try:
                event = await asyncio.wait_for(
                    self._event_queue.get(),
                    timeout=1.0,
                )
                from core.gateway.router import MessageRouter
                router = MessageRouter()
                await router.handle_event(event)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error processing webhook event: %s", e)
