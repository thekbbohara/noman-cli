"""Obsidian vault integration."""

from __future__ import annotations

import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ObsidianConfig:
    """Obsidian configuration."""
    vault_path: str = str(Path.home() / "Obsidian" / "Vault")


class ObsidianClient:
    """Obsidian vault client."""

    def __init__(self, config: ObsidianConfig | None = None):
        self._config = config or ObsidianConfig()
        self._vault_path = Path(self._config.vault_path)

    async def search(self, query: str, max_results: int = 50) -> list[dict]:
        """Search vault contents."""
        if not self._vault_path.exists():
            return []
        results = []
        for file in self._vault_path.rglob("*.md"):
            try:
                content = file.read_text()
                if query.lower() in content.lower():
                    results.append({
                        "path": str(file.relative_to(self._vault_path)),
                        "content": content[:500],
                    })
                    if len(results) >= max_results:
                        break
            except Exception:
                continue
        return results

    async def get_page(self, path: str) -> dict | None:
        """Get a page by path."""
        file_path = self._vault_path / path
        if not file_path.exists():
            return None
        content = file_path.read_text()
        return {"path": path, "content": content}

    async def create_page(self, path: str, content: str) -> bool:
        """Create or update a page."""
        file_path = self._vault_path / path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)
        return True

    async def delete_page(self, path: str) -> bool:
        """Delete a page."""
        file_path = self._vault_path / path
        if file_path.exists():
            file_path.unlink()
            return True
        return False

    async def list_pages(self, folder: str = "") -> list[str]:
        """List all pages in a folder."""
        folder_path = self._vault_path / folder if folder else self._vault_path
        if not folder_path.exists():
            return []
        return [
            str(p.relative_to(self._vault_path))
            for p in folder_path.rglob("*.md")
        ]
