"""WebhookSubscription: data model and management for webhook subscriptions.

A webhook subscription defines an HTTP endpoint that listens for
incoming webhook events and routes them to the appropriate jobs.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class WebhookSubscription:
    """A webhook subscription definition.

    Defines an HTTP endpoint, authentication, event filtering,
    and delivery target for incoming webhook events.

    Attributes:
        id: Unique subscription identifier (UUID4).
        name: Human-readable subscription name.
        path: URL path for the webhook endpoint (e.g., '/webhooks/github').
        secret: HMAC verification secret (auto-generated if not provided).
        events: Event types to trigger on (e.g., ['push', 'pull_request']).
                 Empty list means all events.
        delivery: Delivery target ('origin', 'local', or 'gateway:chat_id').
        headers: Custom headers to validate on incoming requests.
                 Format: {'X-Webhook-Signature': 'required'}.
        enabled: Whether the subscription is active.
        created_at: Timestamp of subscription creation.
        updated_at: Timestamp of last update.
        last_triggered: Timestamp of last successful trigger.
        payload_transform: Optional JSON path expression for payload extraction.
    """

    name: str
    path: str = "/webhooks/default"
    secret: str = ""
    events: list[str] = field(default_factory=list)
    delivery: str = "origin"
    headers: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.utcnow())
    updated_at: datetime = field(default_factory=lambda: datetime.utcnow())
    last_triggered: datetime | None = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    payload_transform: str | None = None

    def __post_init__(self) -> None:
        """Validate and auto-generate secret if empty."""
        if not self.name.strip():
            raise ValueError("Subscription name must not be empty.")
        if not self.path.startswith("/"):
            raise ValueError(f"Path must start with '/': {self.path}")
        if not self.secret:
            self.secret = secrets.token_hex(32)
        self.updated_at = datetime.utcnow()

    def to_dict(self) -> dict[str, Any]:
        """Serialize the subscription to a plain dict."""
        return {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "secret": self.secret,  # In production, hash this
            "events": self.events,
            "delivery": self.delivery,
            "headers": self.headers,
            "enabled": self.enabled,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "last_triggered": self.last_triggered.isoformat() if self.last_triggered else None,
            "payload_transform": self.payload_transform,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WebhookSubscription:
        """Deserialize a subscription from a plain dict."""

        def _parse_dt(val: str | None) -> datetime | None:
            if val is None:
                return None
            val = val.replace("Z", "+00:00")
            return datetime.fromisoformat(val)

        return cls(
            id=data.get("id", str(uuid.uuid4())),
            name=data["name"],
            path=data.get("path", "/webhooks/default"),
            secret=data.get("secret", ""),
            events=data.get("events", []),
            delivery=data.get("delivery", "origin"),
            headers=data.get("headers", {}),
            enabled=data.get("enabled", True),
            created_at=_parse_dt(data.get("created_at")) or datetime.utcnow(),
            updated_at=_parse_dt(data.get("updated_at")) or datetime.utcnow(),
            last_triggered=_parse_dt(data.get("last_triggered")),
            payload_transform=data.get("payload_transform"),
        )

    def verify_signature(self, signature: str, payload: bytes) -> bool:
        """Verify an HMAC signature against the subscription secret.

        Args:
            signature: The signature from the webhook header.
            payload: The raw request body bytes.

        Returns:
            True if the signature is valid.
        """
        import hashlib
        import hmac

        expected = hmac.new(
            self.secret.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    def matches_event(self, event_type: str) -> bool:
        """Check if an event type should trigger this subscription.

        Args:
            event_type: The webhook event type (e.g., 'push', 'pull_request').

        Returns:
            True if this event should be handled.
        """
        if not self.events:
            return True  # Empty list = all events
        return event_type in self.events

    def __repr__(self) -> str:
        return (
            f"<WebhookSubscription name={self.name!r} path={self.path!r} "
            f"enabled={self.enabled} events={self.events}>"
        )
