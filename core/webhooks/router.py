"""WebhookRouter: routes incoming webhook requests to subscriptions and jobs.

The router matches incoming webhook requests to subscriptions based on:
- URL path matching
- Event type filtering
- Signature verification
- Custom header validation
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.webhooks.subscriptions import WebhookSubscription, WebhookSubscription as Subscription

logger = logging.getLogger(__name__)


class RouteMatch:
    """Result of a route lookup for an incoming request."""

    def __init__(
        self,
        subscription: WebhookSubscription,
        event_type: str | None = None,
        payload: Any = None,
        matched: bool = True,
        error: str | None = None,
    ):
        self.subscription = subscription
        self.event_type = event_type
        self.payload = payload
        self.matched = matched
        self.error = error

    @property
    def is_valid(self) -> bool:
        return self.matched and self.error is None


class WebhookRouter:
    """Routes incoming webhook requests to subscriptions.

    Handles path matching, event filtering, signature verification,
    and custom header validation.

    Attributes:
        subscriptions: Dict of name -> WebhookSubscription.
        _subscriptions_by_path: Path -> subscription lookup.
    """

    def __init__(self) -> None:
        self.subscriptions: dict[str, WebhookSubscription] = {}
        self._subscriptions_by_path: dict[str, WebhookSubscription] = {}

    def add_subscription(self, subscription: WebhookSubscription) -> WebhookSubscription:
        """Add or update a subscription.

        Args:
            subscription: The subscription to add.

        Returns:
            The subscription.
        """
        self.subscriptions[subscription.name] = subscription
        self._subscriptions_by_path[subscription.path] = subscription
        logger.info("Added webhook subscription: %s -> %s", subscription.name, subscription.path)
        return subscription

    def remove_subscription(self, name: str) -> bool:
        """Remove a subscription by name.

        Args:
            name: Subscription name.

        Returns:
            True if removed.
        """
        sub = self.subscriptions.pop(name, None)
        if sub:
            self._subscriptions_by_path.pop(sub.path, None)
            logger.info("Removed webhook subscription: %s", name)
            return True
        return False

    def get_subscription(self, name: str) -> WebhookSubscription | None:
        """Get a subscription by name.

        Args:
            name: Subscription name.

        Returns:
            The WebhookSubscription or None.
        """
        return self.subscriptions.get(name)

    def list_subscriptions(self) -> list[WebhookSubscription]:
        """List all subscriptions.

        Returns:
            List of WebhookSubscription instances.
        """
        return list(self.subscriptions.values())

    def match_request(
        self,
        path: str,
        method: str = "POST",
        headers: dict[str, str] | None = None,
        payload: bytes = b"",
        event_type: str | None = None,
    ) -> RouteMatch:
        """Match an incoming request to a subscription.

        Args:
            path: The URL path of the request.
            method: HTTP method.
            headers: Request headers.
            payload: Raw request body.
            event_type: Event type from the request.

        Returns:
            RouteMatch with the matched subscription or error details.
        """
        headers = headers or {}

        # Find matching subscription by path
        sub = self._find_subscription(path)
        if not sub:
            return RouteMatch(
                subscription=WebhookSubscription(name="unknown", path=path),
                matched=False,
                error=f"No subscription found for path: {path}",
            )

        # Check if enabled
        if not sub.enabled:
            return RouteMatch(
                subscription=sub,
                matched=False,
                error="Subscription is disabled",
            )

        # Check event type
        if event_type and not sub.matches_event(event_type):
            return RouteMatch(
                subscription=sub,
                event_type=event_type,
                matched=False,
                error=f"Event '{event_type}' not in subscription events: {sub.events}",
            )

        # Verify signature if secret is set
        if sub.secret:
            signature = headers.get("X-Hub-Signature-256") or headers.get("X-Signature")
            if signature:
                if not sub.verify_signature(signature, payload):
                    return RouteMatch(
                        subscription=sub,
                        event_type=event_type,
                        matched=False,
                        error="Signature verification failed",
                    )

        # Validate custom headers
        for header_name, expected_value in sub.headers.items():
            actual = headers.get(header_name)
            if actual and actual != expected_value:
                return RouteMatch(
                    subscription=sub,
                    event_type=event_type,
                    matched=False,
                    error=f"Header '{header_name}' mismatch: expected '{expected_value}', got '{actual}'",
                )

        return RouteMatch(
            subscription=sub,
            event_type=event_type,
            payload=payload,
            matched=True,
        )

    def _find_subscription(self, path: str) -> WebhookSubscription | None:
        """Find a subscription matching the given path.

        Supports exact match and prefix match.

        Args:
            path: The request path.

        Returns:
            The matching subscription or None.
        """
        # Exact match first
        if path in self._subscriptions_by_path:
            return self._subscriptions_by_path[path]

        # Prefix match (longest match wins)
        best_match: WebhookSubscription | None = None
        best_len = 0
        for sub_path, sub in self._subscriptions_by_path.items():
            if path.startswith(sub_path) and len(sub_path) > best_len:
                best_match = sub
                best_len = len(sub_path)

        return best_match

    async def process_request(
        self,
        path: str,
        method: str = "POST",
        headers: dict[str, str] | None = None,
        payload: bytes = b"",
        event_type: str | None = None,
    ) -> RouteMatch:
        """Process an incoming webhook request.

        Matches the request to a subscription and returns the match result.

        Args:
            path: The URL path.
            method: HTTP method.
            headers: Request headers.
            payload: Raw body.
            event_type: Event type.

        Returns:
            RouteMatch with the result.
        """
        match = self.match_request(path, method, headers, payload, event_type)

        if match.is_valid:
            # Update last_triggered timestamp
            match.subscription.last_triggered = datetime.now(tz=timezone.utc)
            logger.info(
                "Webhook matched: %s -> %s (event: %s)",
                path,
                match.subscription.name,
                event_type,
            )
        else:
            logger.warning(
                "Webhook rejected: %s -> %s (%s)",
                path,
                match.subscription.name,
                match.error,
            )

        return match

    def get_subscription_stats(self) -> dict[str, int]:
        """Get subscription statistics.

        Returns:
            Dict with counts of enabled, disabled, and total subscriptions.
        """
        enabled = sum(1 for s in self.subscriptions.values() if s.enabled)
        disabled = len(self.subscriptions) - enabled
        return {
            "total": len(self.subscriptions),
            "enabled": enabled,
            "disabled": disabled,
        }
