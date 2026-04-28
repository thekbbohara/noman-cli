"""Google Drive client."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class DriveFile:
    """A Google Drive file."""
    id: str
    name: str
    mime_type: str
    size: int = 0
    created_at: str = ""
    modified_at: str = ""
    parents: list[str] = None  # type: ignore
    web_link: str = ""


@dataclass
class DriveConfig:
    """Drive configuration."""
    client_id: str = ""
    client_secret: str = ""
    refresh_token: str = ""
    access_token: str = ""


class DriveClient:
    """Google Drive client."""

    def __init__(self, config: DriveConfig | None = None):
        self._config = config or DriveConfig()

    async def authenticate(self) -> bool:
        if not self._config.client_id:
            return False
        return True

    async def search(self, query: str, max_results: int = 50) -> list[DriveFile]:
        if not await self.authenticate():
            return []
        logger.info(f"Searching Drive: {query}")
        return []

    async def upload(self, name: str, content: bytes, mime_type: str = "text/plain") -> str:
        if not await self.authenticate():
            raise RuntimeError("Not authenticated")
        return f"file:{name}"

    async def download(self, file_id: str) -> bytes | None:
        if not await self.authenticate():
            return None
        return None

    async def delete(self, file_id: str) -> bool:
        if not await self.authenticate():
            return False
        return True

    async def close(self) -> None:
        pass
