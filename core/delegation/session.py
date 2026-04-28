"""Worker session management."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class WorkerSession:
    """Manages a worker session with its own context."""

    def __init__(self, session_id: str):
        self._session_id = session_id
        self._started_at = datetime.now()
        self._tools: list[str] = []
        self._files: list[str] = []
        self._env: dict[str, str] = {}

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def started_at(self) -> datetime:
        return self._started_at

    def add_tool(self, tool: str) -> None:
        """Add a tool to the session."""
        if tool not in self._tools:
            self._tools.append(tool)

    def add_file(self, path: str) -> None:
        """Add a file to the session."""
        if path not in self._files:
            self._files.append(path)

    def set_env(self, key: str, value: str) -> None:
        """Set an environment variable."""
        self._env[key] = value

    def get_context(self) -> dict:
        """Get the session context."""
        return {
            "session_id": self._session_id,
            "started_at": self._started_at.isoformat(),
            "tools": self._tools,
            "files": self._files,
            "env": self._env,
        }
