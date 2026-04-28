"""Google Sheets integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SheetsConfig:
    """Sheets configuration."""
    client_id: str = ""
    client_secret: str = ""
    refresh_token: str = ""
    access_token: str = ""


class SheetsClient:
    """Google Sheets client."""

    def __init__(self, config: SheetsConfig | None = None):
        self._config = config or SheetsConfig()

    async def authenticate(self) -> bool:
        return bool(self._config.client_id)

    async def read(self, spreadsheet_id: str, range_name: str = "A1:Z100") -> list[list]:
        if not await self.authenticate():
            return []
        return []

    async def write(
        self,
        spreadsheet_id: str,
        range_name: str,
        values: list[list],
    ) -> dict:
        if not await self.authenticate():
            raise RuntimeError("Not authenticated")
        return {"updated": True}

    async def close(self) -> None:
        pass
