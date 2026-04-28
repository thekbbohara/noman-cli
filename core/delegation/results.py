"""Result aggregation for delegation."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class ResultAggregator:
    """Aggregates results from multiple workers."""

    def __init__(self):
        self._results: dict[str, dict] = {}

    def add(self, worker_id: str, result: dict) -> None:
        """Add a result from a worker."""
        self._results[worker_id] = {
            "worker_id": worker_id,
            "result": result,
            "timestamp": datetime.now().isoformat(),
        }

    def get_all(self) -> list[dict]:
        """Get all results."""
        return list(self._results.values())

    def get_successful(self) -> list[dict]:
        """Get only successful results."""
        return [
            r for r in self._results.values()
            if r.get("result", {}).get("success", False)
        ]

    def get_failed(self) -> list[dict]:
        """Get only failed results."""
        return [
            r for r in self._results.values()
            if not r.get("result", {}).get("success", True)
        ]

    def get_summary(self) -> dict:
        """Get a summary of all results."""
        total = len(self._results)
        successful = len(self.get_successful())
        failed = total - successful
        return {
            "total": total,
            "successful": successful,
            "failed": failed,
        }
