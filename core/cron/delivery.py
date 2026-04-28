"""Delivery handlers for noman-cli cron scheduler.

Defines how job results are delivered after execution:
- OriginDelivery: return result to CLI caller
- FileDelivery: save result to a local file
- GatewayDelivery: forward result to a messaging gateway
"""

from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

from core.cron.jobs import CronJob

logger = logging.getLogger(__name__)


class DeliveryResult:
    """Standard result from a delivery handler."""

    def __init__(
        self,
        status: str = "success",
        message: str = "",
        data: dict[str, Any] | None = None,
    ):
        self.status = status
        self.message = message
        self.data = data or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "message": self.message,
            "data": self.data,
        }


class DeliveryHandler(ABC):
    """Abstract base for delivery handlers."""

    kind: str

    @abstractmethod
    async def deliver(self, job: CronJob, result: str) -> DeliveryResult:
        """Deliver the job result to the configured destination.

        Args:
            job: The completed CronJob.
            result: The text result from job execution.

        Returns:
            DeliveryResult with status and metadata.
        """
        ...

    def format_output(self, job: CronJob, result: str, max_length: int = 200) -> str:
        """Format a result for display/output.

        Args:
            job: The CronJob that produced the result.
            result: The raw result text.
            max_length: Truncate length for display.

        Returns:
            Formatted string ready for display.
        """
        lines = result.split("\n")
        truncated = False
        total = 0
        output_lines: list[str] = []

        for line in lines:
            if total + len(line) > max_length:
                output_lines.append(line[: max_length - total] + "...")
                truncated = True
                break
            output_lines.append(line)
            total += len(line) + 1  # +1 for newline

        header = f"[{job.id[:8]}] {job.name} - {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}"
        body = "\n".join(output_lines)
        if truncated:
            body += "\n...(truncated)"
        return f"{header}\n{body}"


class OriginDelivery(DeliveryHandler):
    """Deliver results back to the CLI caller (stdout/stderr)."""

    kind = "origin"

    async def deliver(self, job: CronJob, result: str) -> DeliveryResult:
        """Print result to stdout and return success.

        Args:
            job: The completed CronJob.
            result: The text result.

        Returns:
            DeliveryResult indicating success.
        """
        formatted = self.format_output(job, result)
        print(formatted)
        return DeliveryResult(status="success", message="Result delivered to origin")


class FileDelivery(DeliveryHandler):
    """Deliver results to a local file."""

    kind = "local"

    def __init__(self, output_dir: str | Path = ".noman/cron_output") -> None:
        """Initialize with output directory path.

        Args:
            output_dir: Directory to save output files.
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def deliver(self, job: CronJob, result: str) -> DeliveryResult:
        """Save result to a timestamped file.

        Args:
            job: The completed CronJob.
            result: The text result.

        Returns:
            DeliveryResult with the saved file path.
        """
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(
            c if c.isalnum() or c in "-_." else "_" for c in job.name
        )[:50]
        file_path = self.output_dir / f"{safe_name}_{ts}.txt"
        file_path.write_text(result, encoding="utf-8")

        # Also save a JSON metadata file alongside
        meta = {
            "job_id": job.id,
            "job_name": job.name,
            "timestamp": datetime.utcnow().isoformat(),
            "result_length": len(result),
        }
        (self.output_dir / f"{safe_name}_{ts}.meta.json").write_text(
            json.dumps(meta, indent=2)
        )

        logger.info("File delivery: saved %s", file_path)
        return DeliveryResult(
            status="success",
            message=f"Result saved to {file_path}",
            data={"path": str(file_path)},
        )


class GatewayDelivery(DeliveryHandler):
    """Deliver results to a messaging gateway channel.

    Supports 'gateway:chat_id' delivery format where chat_id
    identifies the target channel/user in the gateway system.
    """

    kind = "gateway"

    def __init__(self) -> None:
        """Initialize with lazy gateway reference."""
        self._gateway = None  # Set at runtime

    @property
    def gateway(self):
        """Lazily get the gateway manager."""
        if self._gateway is None:
            try:
                from core.gateway.scheduler import GatewayManager
                self._gateway = GatewayManager()
            except ImportError:
                logger.warning("Gateway module not available; delivery skipped")
                return None
        return self._gateway

    async def deliver(self, job: CronJob, result: str) -> DeliveryResult:
        """Forward result to the specified gateway channel.

        Args:
            job: The completed CronJob.
            result: The text result.

        Returns:
            DeliveryResult with delivery status.
        """
        # Parse delivery target from job.delivery field
        # Format: 'gateway:chat_id'
        parts = job.delivery.split(":", 1)
        if len(parts) != 2 or parts[0] != "gateway":
            return DeliveryResult(
                status="error",
                message=f"Invalid gateway delivery target: {job.delivery}",
            )

        chat_id = parts[1]

        gateway = self.gateway
        if gateway is None:
            return DeliveryResult(
                status="error",
                message="Gateway not available",
            )

        # Check if gateway is running
        status = gateway.get_status()
        if not status.running:
            logger.warning("Gateway not running; result queued for later delivery")
            return DeliveryResult(
                status="queued",
                message="Gateway not running; result queued",
                data={"job_id": job.id, "chat_id": chat_id},
            )

        try:
            # Send via the gateway's message interface
            # This uses the gateway's built-in messaging abstraction
            message = self.format_output(job, result, max_length=4096)
            sent = await gateway.send_message(chat_id, message)
            if sent:
                return DeliveryResult(
                    status="success",
                    message=f"Delivered to gateway channel {chat_id}",
                    data={"chat_id": chat_id},
                )
            else:
                return DeliveryResult(
                    status="error",
                    message=f"Failed to deliver to gateway channel {chat_id}",
                    data={"chat_id": chat_id},
                )
        except Exception as e:
            logger.error("Gateway delivery failed: %s", e)
            return DeliveryResult(
                status="error",
                message=f"Gateway delivery error: {e}",
                data={"chat_id": chat_id},
            )


def resolve_delivery(delivery: str) -> DeliveryHandler:
    """Create the appropriate DeliveryHandler for a delivery target.

    Args:
        delivery: Delivery target string:
            - 'origin': return to CLI caller
            - 'local': save to file
            - 'gateway:chat_id': forward to gateway

    Returns:
        A DeliveryHandler instance.
    """
    if delivery.startswith("gateway:"):
        return GatewayDelivery()
    elif delivery == "local":
        return FileDelivery()
    else:
        return OriginDelivery()
