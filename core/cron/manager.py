"""CronManager: high-level interface for managing cron jobs.

Provides a programmatic and CLI-friendly API for creating,
listing, controlling, and monitoring cron jobs.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from core.cron.jobs import CronJob, JobStatus
from core.cron.scheduler import CronScheduler, SchedulerConfig, SchedulerState

logger = logging.getLogger(__name__)


class CronManager:
    """High-level manager for the noman-cli cron system.

    Wraps the CronScheduler and JobStorage with a simpler API
    for programmatic and CLI use.

    Args:
        scheduler: CronScheduler instance (created with defaults if not provided).
    """

    def __init__(self, scheduler: CronScheduler | None = None) -> None:
        self.scheduler = scheduler or CronScheduler()

    # -- Lifecycle --

    async def start(self) -> None:
        """Start the cron scheduler."""
        await self.scheduler.start()
        logger.info("CronManager started")

    async def stop(self) -> None:
        """Stop the cron scheduler."""
        await self.scheduler.stop()
        logger.info("CronManager stopped")

    @property
    def is_running(self) -> bool:
        """Check if the cron scheduler is running."""
        return self.scheduler.is_running

    def get_state(self) -> SchedulerState:
        """Get the scheduler state snapshot."""
        return self.scheduler.get_state()

    # -- Job creation --

    def create_job(
        self,
        name: str,
        schedule: str,
        prompt: str,
        delivery: str = "origin",
        skills: list[str] | None = None,
        model: dict[str, Any] | None = None,
        repeat: int | None = None,
        max_attempts: int = 0,
        enabled: bool = True,
    ) -> CronJob:
        """Create and save a new cron job.

        Args:
            name: Human-readable job name.
            schedule: Cron expression or interval string.
            prompt: Task description for the orchestrator.
            delivery: Delivery target ('origin', 'local', or 'gateway:chat_id').
            skills: Optional list of skill names to load.
            model: Optional model override config.
            repeat: Number of times to repeat (None = forever).
            max_attempts: Max retry attempts on failure (0 = use default).
            enabled: Whether the job is active.

        Returns:
            The created CronJob.

        Raises:
            ValueError: If required fields are empty.
        """
        job = CronJob(
            name=name,
            schedule=schedule,
            prompt=prompt,
            delivery=delivery,
            skills=skills or [],
            model=model or {},
            repeat=repeat,
            enabled=enabled,
            max_attempts=max_attempts,
        )
        return self.scheduler.add_job(job)

    def create_interval_job(
        self,
        name: str,
        interval: str,
        prompt: str,
        **kwargs: Any,
    ) -> CronJob:
        """Create a job with an interval schedule.

        Args:
            name: Job name.
            interval: Interval string (e.g., '30m', '2h', '1d').
            prompt: Task description.
            **kwargs: Additional arguments passed to create_job.

        Returns:
            The created CronJob.
        """
        return self.create_job(name=name, schedule=interval, prompt=prompt, **kwargs)

    def create_cron_job(
        self,
        name: str,
        cron_expr: str,
        prompt: str,
        **kwargs: Any,
    ) -> CronJob:
        """Create a job with a cron expression schedule.

        Args:
            name: Job name.
            cron_expr: 5-field cron expression.
            prompt: Task description.
            **kwargs: Additional arguments passed to create_job.

        Returns:
            The created CronJob.
        """
        return self.create_job(name=name, schedule=cron_expr, prompt=prompt, **kwargs)

    def create_once_job(
        self,
        name: str,
        prompt: str,
        at: datetime | None = None,
        **kwargs: Any,
    ) -> CronJob:
        """Create a one-shot job.

        Args:
            name: Job name.
            prompt: Task description.
            at: Optional specific time to fire (defaults to now).
            **kwargs: Additional arguments passed to create_job.

        Returns:
            The created CronJob.
        """
        schedule = f"once:{at.isoformat()}" if at else "once"
        return self.create_job(name=name, schedule=schedule, prompt=prompt, **kwargs)

    # -- Job control --

    def list_jobs(
        self,
        status: JobStatus | None = None,
        enabled_only: bool = False,
        limit: int = 100,
    ) -> list[CronJob]:
        """List jobs with optional filters.

        Args:
            status: Filter by JobStatus.
            enabled_only: Only enabled jobs.
            limit: Max results.

        Returns:
            List of CronJob instances.
        """
        return self.scheduler.list_jobs(
            status=status, enabled_only=enabled_only, limit=limit
        )

    def get_job(self, job_id: str) -> CronJob:
        """Get a job by ID.

        Args:
            job_id: The job UUID.

        Returns:
            The CronJob.
        """
        return self.scheduler.get_job(job_id)

    def update_job(
        self,
        job_id: str,
        **fields: Any,
    ) -> CronJob:
        """Update a job's fields.

        Args:
            job_id: The job UUID.
            **fields: Fields to update.

        Returns:
            The updated CronJob.
        """
        return self.scheduler.update_job(job_id, **fields)

    def pause_job(self, job_id: str) -> CronJob:
        """Pause a job.

        Args:
            job_id: The job UUID.

        Returns:
            The paused CronJob.
        """
        return self.scheduler.pause_job(job_id)

    def resume_job(self, job_id: str) -> CronJob:
        """Resume a paused job.

        Args:
            job_id: The job UUID.

        Returns:
            The resumed CronJob.
        """
        return self.scheduler.resume_job(job_id)

    def remove_job(self, job_id: str) -> bool:
        """Remove a job.

        Args:
            job_id: The job UUID.

        Returns:
            True if removed.
        """
        return self.scheduler.remove_job(job_id)

    async def run_job(self, job_id: str) -> str:
        """Manually run a job immediately.

        Args:
            job_id: The job UUID.

        Returns:
            The job result text.
        """
        return await self.scheduler.run_job_now(job_id)

    # -- Status --

    def format_status(self) -> str:
        """Format the scheduler state as a human-readable string."""
        state = self.get_state()
        lines = [
            "=== Cron Scheduler Status ===",
            f"  Running: {'Yes' if state.running else 'No'}",
            f"  Total jobs: {state.jobs_count}",
            f"  Enabled: {state.enabled_jobs}",
            f"  Pending: {state.pending_jobs}",
            f"  Running: {state.running_jobs}",
            f"  Failed: {state.failed_jobs}",
            f"  Uptime: {state.uptime_seconds:.0f}s",
        ]
        return "\n".join(lines)

    def format_job_list(self, jobs: list[CronJob]) -> str:
        """Format a list of jobs as a table string."""
        if not jobs:
            return "No jobs found."

        lines = [
            f"{'ID':<12} {'Name':<25} {'Schedule':<12} {'Status':<12} {'Enabled':>8} {'Next Run':>20}",
            "-" * 100,
        ]
        for job in jobs:
            next_run = ""
            if job.next_run:
                try:
                    delta = (job.next_run - datetime.now(tz=timezone.utc)).total_seconds()
                    if delta < 0:
                        next_run = "OVERDUE"
                    elif delta < 3600:
                        next_run = f"{delta/60:.0f}m"
                    elif delta < 86400:
                        next_run = f"{delta/3600:.1f}h"
                    else:
                        next_run = f"{delta/86400:.1f}d"
                except Exception:
                    next_run = job.next_run.strftime("%Y-%m-%d %H:%M")
            else:
                next_run = "—"

            lines.append(
                f"{job.id[:12]:<12} {job.name:<25} {job.schedule:<12} "
                f"{job.status.value:<12} {'Yes' if job.enabled else 'No':>8} "
                f"{next_run:>20}"
            )
        return "\n".join(lines)
