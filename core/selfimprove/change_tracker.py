"""Track and limit self-improvement changes to prevent cascading failures."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SessionState:
    """State for a single self-improvement session."""
    session_id: str
    start_time: float
    changes_count: int = 0
    change_types: dict[str, int] = field(default_factory=dict)
    last_change_time: float = 0.0
    max_session_seconds: float = 300.0

    @property
    def is_overdue(self) -> bool:
        """Check if session has exceeded its time budget."""
        return (time.time() - self.start_time) > self.max_session_seconds


class ChangeTracker:
    """
    Tracks self-improvement changes to enforce limits and prevent cascades.

    Enforces:
    - Max N changes per session
    - Cooldown between changes (prevents rapid-fire modifications)
    - Max N of any single change type (prevents homogenous overload)
    - Max session duration
    """

    def __init__(
        self,
        max_changes_per_session: int = 10,
        cooldown_seconds: float = 5.0,
        max_per_type: int = 3,
        max_session_seconds: float = 300.0,
    ) -> None:
        self.max_changes = max_changes_per_session
        self.cooldown = cooldown_seconds
        self.max_per_type = max_per_type
        self.max_session_seconds = max_session_seconds
        self._sessions: dict[str, SessionState] = {}

    def check_allowed(self, session_id: str, change_type: str) -> tuple[bool, str]:
        """
        Check if a change is allowed. Returns (allowed, reason).
        """
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionState(
                session_id=session_id,
                start_time=time.time(),
                max_session_seconds=self.max_session_seconds,
            )

        state = self._sessions[session_id]

        # Session expired
        if state.is_overdue:
            return False, f"Session expired after {self.max_session_seconds}s"

        # Rate limit
        if state.changes_count >= self.max_changes:
            return False, f"Max {self.max_changes} changes per session reached"

        # Per-type limit (check before cooldown so different types aren't blocked)
        type_count = state.change_types.get(change_type, 0)
        if type_count >= self.max_per_type:
            return False, f"Max {self.max_per_type} changes of type '{change_type}' per session"

        # Cooldown
        elapsed = time.time() - state.last_change_time
        if elapsed < self.cooldown:
            return False, f"Cooldown active: {self.cooldown - elapsed:.1f}s remaining"

        return True, "OK"

    def record_change(self, session_id: str, change_type: str) -> None:
        """Record that a change was applied."""
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionState(
                session_id=session_id,
                start_time=time.time(),
            )
        state = self._sessions[session_id]
        state.changes_count += 1
        state.change_types[change_type] = state.change_types.get(change_type, 0) + 1
        state.last_change_time = time.time()

    def reset(self, session_id: str) -> None:
        """Reset a session's counters."""
        if session_id in self._sessions:
            del self._sessions[session_id]

    def get_session_info(self, session_id: str) -> dict[str, Any]:
        """Return current session state for monitoring."""
        if session_id not in self._sessions:
            return {"active": False}
        state = self._sessions[session_id]
        return {
            "active": True,
            "session_id": state.session_id,
            "changes_count": state.changes_count,
            "change_types": dict(state.change_types),
            "last_change_age": time.time() - state.last_change_time,
            "overdue": state.is_overdue,
        }
