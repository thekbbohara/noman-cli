"""Context propagation for delegation."""

from __future__ import annotations

import logging
import json
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


class ContextPropagator:
    """Propagates context between parent and worker sessions."""

    def __init__(self):
        self._contexts: dict[str, dict] = {}

    def capture(self, session_id: str, context: dict) -> None:
        """Capture context from a session."""
        self._contexts[session_id] = context

    def propagate(self, session_id: str) -> dict:
        """Get context for a session."""
        return self._contexts.get(session_id, {})

    def merge(self, base: dict, override: dict) -> dict:
        """Merge two contexts."""
        result = dict(base)
        result.update(override)
        return result

    def serialize(self, context: dict) -> str:
        """Serialize context to JSON."""
        return json.dumps(context)

    def deserialize(self, data: str) -> dict:
        """Deserialize context from JSON."""
        return json.loads(data)
