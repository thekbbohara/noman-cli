"""Enhanced command palette for TUI."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class PaletteEntry:
    """A command palette entry."""
    command: str
    description: str
    category: str = "general"
    shortcut: str = ""


class CommandPalette:
    """Enhanced command palette with search and categorization."""

    def __init__(self):
        self._entries: list[PaletteEntry] = []
        self._registered: dict[str, callable] = {}

    def register(self, command: str, description: str, category: str = "general", shortcut: str = "") -> None:
        """Register a command in the palette."""
        self._entries.append(PaletteEntry(command, description, category, shortcut))
        self._registered[command] = None

    def search(self, query: str, limit: int = 20) -> list[dict]:
        """Search commands by query."""
        if not query:
            return [{"command": e.command, "description": e.description, "category": e.category} for e in self._entries[:limit]]
        results = []
        query_lower = query.lower()
        for entry in self._entries:
            if (query_lower in entry.command.lower() or
                query_lower in entry.description.lower() or
                query_lower in entry.category.lower()):
                results.append({
                    "command": entry.command,
                    "description": entry.description,
                    "category": entry.category,
                    "shortcut": entry.shortcut,
                })
        return results[:limit]

    def list_categories(self) -> list[str]:
        """List all categories."""
        return list(set(e.category for e in self._entries))

    def list_by_category(self, category: str) -> list[dict]:
        """List commands by category."""
        return [
            {"command": e.command, "description": e.description, "shortcut": e.shortcut}
            for e in self._entries
            if e.category == category
        ]
