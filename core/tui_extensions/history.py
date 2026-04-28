"""Command history for TUI."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class HistoryEntry:
    """A command history entry."""
    command: str
    timestamp: datetime
    result: str = ""
    success: bool = True


class CommandHistory:
    """Command history with search and navigation."""

    def __init__(self, max_entries: int = 1000):
        self._entries: list[HistoryEntry] = []
        self._max_entries = max_entries
        self._current_index: int = -1

    def add(self, command: str, result: str = "", success: bool = True) -> None:
        """Add a command to history."""
        self._entries.append(HistoryEntry(command, datetime.now(), result, success))
        if len(self._entries) > self._max_entries:
            self._entries.pop(0)
        self._current_index = len(self._entries)

    def get_previous(self, count: int = 1) -> str:
        """Get previous command."""
        self._current_index = max(0, self._current_index - count)
        if self._current_index < len(self._entries):
            return self._entries[self._current_index].command
        return ""

    def get_next(self, count: int = 1) -> str:
        """Get next command."""
        self._current_index = min(len(self._entries) - 1, self._current_index + count)
        if self._current_index >= 0:
            return self._entries[self._current_index].command
        return ""

    def search(self, query: str, max_results: int = 20) -> list[dict]:
        """Search history by query."""
        results = []
        query_lower = query.lower()
        for entry in self._entries:
            if query_lower in entry.command.lower():
                results.append({
                    "command": entry.command,
                    "timestamp": entry.timestamp.isoformat(),
                    "success": entry.success,
                })
                if len(results) >= max_results:
                    break
        return results

    def list_recent(self, count: int = 20) -> list[dict]:
        """List recent commands."""
        return [
            {
                "command": e.command,
                "timestamp": e.timestamp.isoformat(),
                "success": e.success,
            }
            for e in self._entries[-count:]
        ]

    def clear(self) -> None:
        """Clear history."""
        self._entries.clear()
        self._current_index = -1
