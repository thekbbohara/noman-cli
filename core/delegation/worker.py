"""Worker process management."""

from __future__ import annotations

import logging
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class WorkerStatus:
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Worker:
    """Manages a worker process for delegation."""

    def __init__(self, worker_id: str, goal: str, context: str = ""):
        self._worker_id = worker_id
        self._goal = goal
        self._context = context
        self._status = WorkerStatus.PENDING
        self._result: str = ""

    @property
    def status(self) -> str:
        return self._status

    @property
    def result(self) -> str:
        return self._result

    async def start(self) -> str:
        """Start the worker."""
        self._status = WorkerStatus.RUNNING
        logger.info(f"Worker {self._worker_id} started")
        return self._worker_id

    async def cancel(self) -> bool:
        """Cancel the worker."""
        self._status = WorkerStatus.CANCELLED
        return True

    async def wait(self, timeout: int = 3600) -> str:
        """Wait for worker to complete."""
        self._status = WorkerStatus.COMPLETED
        return self._result

    def set_result(self, result: str) -> None:
        """Set the worker result."""
        self._result = result
        self._status = WorkerStatus.COMPLETED
