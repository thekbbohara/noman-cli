"""CronScheduler: async cron daemon for noman-cli.

The CronScheduler manages scheduled jobs, dispatching them
at their configured times. It handles:
- Cron expression evaluation (via croniter)
- Interval-based scheduling
- One-shot execution
- Repeat counts
- Timezone awareness
- Auto-retry with exponential backoff
- Clock drift and missed run detection
- SQLite persistence
"""

from __future__ import annotations

import asyncio
import logging
import signal
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from core.cron.delivery import DeliveryHandler, DeliveryResult, resolve_delivery
from core.cron.jobs import CronJob, JobStatus
from core.cron.storage import JobNotFoundError, JobStorage
from core.cron.triggers import CronTrigger, IntervalTrigger, OnceTrigger, Trigger, parse_schedule

logger = logging.getLogger(__name__)


class SchedulerConfig:
    """Configuration for the CronScheduler.

    Attributes:
        enabled: Whether the scheduler is active.
        port: Port for the webhook server (if enabled).
        timezone: Default timezone for scheduling (default 'UTC').
        max_jobs: Maximum number of jobs allowed.
        retry_max_attempts: Max retries on failure (default 3).
        retry_backoff_sec: Initial backoff in seconds (default 5.0).
        check_interval: How often to check for due jobs (default 30s).
        clock_drift_tolerance: Seconds of tolerance for clock drift.
        db_path: Path to the jobs SQLite database.
    """

    def __init__(self, **kwargs: Any) -> None:
        self.enabled: bool = kwargs.get("enabled", True)
        self.port: int = kwargs.get("port", 9090)
        self.timezone: str = kwargs.get("timezone", "UTC")
        self.max_jobs: int = kwargs.get("max_jobs", 100)
        self.retry_max_attempts: int = kwargs.get("retry_max_attempts", 3)
        self.retry_backoff_sec: float = kwargs.get("retry_backoff_sec", 5.0)
        self.check_interval: float = kwargs.get("check_interval", 30.0)
        self.clock_drift_tolerance: float = kwargs.get("clock_drift_tolerance", 60.0)
        self.db_path: str = kwargs.get("db_path", ".noman/cron_jobs.db")


class SchedulerError(Exception):
    """Base exception for scheduler operations."""


class SchedulerFullError(SchedulerError):
    """Raised when max jobs limit is reached."""


class SchedulerState:
    """Snapshot of the scheduler's current state."""

    def __init__(
        self,
        running: bool,
        jobs_count: int,
        enabled_jobs: int,
        pending_jobs: int,
        running_jobs: int,
        failed_jobs: int,
        uptime_seconds: float,
    ):
        self.running = running
        self.jobs_count = jobs_count
        self.enabled_jobs = enabled_jobs
        self.pending_jobs = pending_jobs
        self.running_jobs = running_jobs
        self.failed_jobs = failed_jobs
        self.uptime_seconds = uptime_seconds

    def to_dict(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "jobs_count": self.jobs_count,
            "enabled_jobs": self.enabled_jobs,
            "pending_jobs": self.pending_jobs,
            "running_jobs": self.running_jobs,
            "failed_jobs": self.failed_jobs,
            "uptime_seconds": round(self.uptime_seconds, 1),
        }


class CronScheduler:
    """Async cron daemon that manages scheduled jobs.

    The scheduler runs in its own asyncio task, periodically
    checking for due jobs and dispatching them. It supports
    cron expressions, interval-based scheduling, one-shot
    jobs, and repeat counts.

    Args:
        config: SchedulerConfig instance.
        storage: JobStorage instance (uses default if not provided).
        on_job_complete: Optional callback for job completion events.
        on_job_error: Optional callback for job error events.
    """

    def __init__(
        self,
        config: SchedulerConfig | None = None,
        storage: JobStorage | None = None,
        on_job_complete: Callable[[CronJob, str], Any] | None = None,
        on_job_error: Callable[[CronJob, Exception], Any] | None = None,
    ) -> None:
        self.config = config or SchedulerConfig()
        self.storage = storage or JobStorage(db_path=self.config.db_path)
        self._on_job_complete = on_job_complete
        self._on_job_error = on_job_error

        # Internal state
        self._running: bool = False
        self._task: asyncio.Task | None = None
        self._start_time: datetime | None = None
        self._trigger_cache: dict[str, Trigger] = {}  # job_id -> Trigger

        # Job execution tracking
        self._active_jobs: dict[str, asyncio.Task] = {}

        # Webhook server reference (set externally)
        self._webhook_server = None

    # -- Lifecycle --

    async def start(self) -> None:
        """Start the scheduler daemon.

        Loads enabled jobs from storage and begins the scheduling loop.
        """
        if self._running:
            logger.warning("Scheduler already running")
            return

        if not self.config.enabled:
            logger.info("Scheduler disabled by config")
            return

        self._running = True
        self._start_time = datetime.now(tz=timezone.utc)
        self._task = asyncio.create_task(self._run_loop())

        # Load enabled jobs into trigger cache
        jobs = self.storage.get_enabled_jobs()
        for job in jobs:
            try:
                trigger = parse_schedule(job.schedule)
                self._trigger_cache[job.id] = trigger
                # Set next_run if not set
                if job.next_run is None:
                    job.next_run = trigger.next_run()
                    job.updated_at = datetime.utcnow()
                    self.storage.save(job)
                logger.info(
                    "Loaded job: %s (%s, next: %s)",
                    job.name,
                    job.schedule,
                    job.next_run.isoformat() if job.next_run else "none",
                )
            except Exception as e:
                logger.error("Failed to load job %s: %s", job.name, e)

        logger.info("CronScheduler started")

    async def stop(self) -> None:
        """Stop the scheduler daemon gracefully.

        Waits for active jobs to complete before shutting down.
        """
        if not self._running:
            return

        self._running = False
        logger.info("Stopping scheduler...")

        # Cancel the main loop task
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        # Wait for active jobs with timeout
        if self._active_jobs:
            logger.info("Waiting for %d active jobs to complete...", len(self._active_jobs))
            await asyncio.wait_for(
                asyncio.gather(*self._active_jobs.values(), return_exceptions=True),
                timeout=30.0,
            )
            self._active_jobs.clear()

        logger.info("Scheduler stopped")

    @property
    def is_running(self) -> bool:
        """Check if the scheduler is running."""
        return self._running

    def get_state(self) -> SchedulerState:
        """Get a snapshot of the scheduler state."""
        jobs = self.storage.list_jobs()
        enabled = [j for j in jobs if j.enabled]
        pending = [j for j in jobs if j.status == JobStatus.PENDING]
        running = [j for j in jobs if j.status == JobStatus.RUNNING]
        failed = [j for j in jobs if j.status == JobStatus.FAILED]

        uptime = 0.0
        if self._start_time:
            uptime = (datetime.now(tz=timezone.utc) - self._start_time).total_seconds()

        return SchedulerState(
            running=self._running,
            jobs_count=len(jobs),
            enabled_jobs=len(enabled),
            pending_jobs=len(pending),
            running_jobs=len(running),
            failed_jobs=len(failed),
            uptime_seconds=uptime,
        )

    @property
    def job_count(self) -> int:
        """Return the total number of jobs."""
        return self.storage.count()

    # -- Job management --

    def add_job(self, job: CronJob) -> CronJob:
        """Add a new job to the scheduler.

        Args:
            job: The CronJob to add.

        Returns:
            The saved CronJob.

        Raises:
            SchedulerFullError: If max_jobs limit is reached.
        """
        if self.storage.count() >= self.config.max_jobs:
            raise SchedulerFullError(
                f"Maximum jobs limit ({self.config.max_jobs}) reached. "
                f"Remove existing jobs before adding new ones."
            )
        job.status = JobStatus.PENDING
        # Set initial next_run
        trigger = parse_schedule(job.schedule)
        job.next_run = trigger.next_run()
        self._trigger_cache[job.id] = trigger
        return self.storage.save(job)

    def update_job(self, job_id: str, **fields: Any) -> CronJob:
        """Update a job's fields and save it.

        Args:
            job_id: The job UUID.
            **fields: Fields to update (e.g., schedule='30m', prompt='new task').

        Returns:
            The updated CronJob.

        Raises:
            JobNotFoundError: If the job doesn't exist.
        """
        job = self.storage.get(job_id)

        # Apply updates
        for key, value in fields.items():
            if hasattr(job, key):
                setattr(job, key, value)

        # If schedule changed, recalculate next_run
        if "schedule" in fields:
            trigger = parse_schedule(fields["schedule"])
            job.next_run = trigger.next_run()
            self._trigger_cache[job.id] = trigger

        job.updated_at = datetime.utcnow()
        if "enabled" in fields and fields["enabled"]:
            job.status = JobStatus.PENDING
        return self.storage.save(job)

    def pause_job(self, job_id: str) -> CronJob:
        """Pause a job (disable without deleting).

        Args:
            job_id: The job UUID.

        Returns:
            The paused CronJob.
        """
        return self.update_job(job_id, enabled=False, status=JobStatus.PAUSED)

    def resume_job(self, job_id: str) -> CronJob:
        """Resume a paused job.

        Args:
            job_id: The job UUID.

        Returns:
            The resumed CronJob.
        """
        job = self.storage.get(job_id)
        job.enabled = True
        job.status = JobStatus.PENDING
        # Recalculate next_run
        trigger = self._trigger_cache.get(job.id)
        if trigger is None:
            trigger = parse_schedule(job.schedule)
            self._trigger_cache[job.id] = trigger
        job.next_run = trigger.next_run(job.last_run)
        job.updated_at = datetime.utcnow()
        return self.storage.save(job)

    def remove_job(self, job_id: str) -> bool:
        """Remove a job from the scheduler.

        Args:
            job_id: The job UUID.

        Returns:
            True if the job was removed.
        """
        # Remove from trigger cache
        self._trigger_cache.pop(job_id, None)
        return self.storage.delete(job_id)

    def get_job(self, job_id: str) -> CronJob:
        """Get a job by ID.

        Args:
            job_id: The job UUID.

        Returns:
            The CronJob.

        Raises:
            JobNotFoundError: If not found.
        """
        return self.storage.get(job_id)

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
        return self.storage.list_jobs(status=status, enabled_only=enabled_only, limit=limit)

    # -- Job execution --

    async def run_job_now(self, job_id: str) -> str:
        """Manually trigger a job immediately.

        Args:
            job_id: The job UUID.

        Returns:
            The job result text.

        Raises:
            JobNotFoundError: If job not found.
        """
        job = self.storage.get(job_id)
        job.status = JobStatus.RUNNING
        job.updated_at = datetime.utcnow()
        self.storage.save(job)

        # Dispatch the job
        result = await self._dispatch_job(job)

        # Update job state based on result
        job.last_run = datetime.utcnow()
        if result.get("success", False):
            job.status = JobStatus.COMPLETED
            # Handle repeat logic
            if job.repeat is not None:
                job.repeat = job.repeat - 1
                if job.repeat <= 0:
                    job.enabled = False
                    job.status = JobStatus.COMPLETED
                    job.next_run = None
                else:
                    # Calculate next run for next repeat
                    trigger = self._trigger_cache.get(job.id)
                    if trigger:
                        job.next_run = trigger.next_run(job.last_run)
            else:
                # Forever repeat: schedule next run
                trigger = self._trigger_cache.get(job.id)
                if trigger:
                    job.next_run = trigger.next_run(job.last_run)
            job.attempts = 0
        else:
            job.status = JobStatus.FAILED
            job.attempts += 1
            # Auto-retry
            if job.attempts < (job.max_attempts or self.config.retry_max_attempts):
                job.status = JobStatus.PENDING
                # Schedule retry with backoff
                backoff = self.config.retry_backoff_sec * (2 ** (job.attempts - 1))
                job.next_run = datetime.utcnow()
                job.next_run = job.next_run.replace(
                    microsecond=0
                )
                import datetime as dt
                from datetime import timedelta
                job.next_run = datetime.now(tz=timezone.utc) + timedelta(seconds=backoff)
                job.updated_at = datetime.utcnow()

        self.storage.save(job)
        return result.get("output", "")

    async def dispatch_job(self, job: CronJob) -> dict[str, Any]:
        """Dispatch a job for execution (internal).

        Args:
            job: The CronJob to dispatch.

        Returns:
            Result dict with 'success', 'output', and 'error' keys.
        """
        return await self._dispatch_job(job)

    async def _dispatch_job(self, job: CronJob) -> dict[str, Any]:
        """Execute a job and handle the result.

        Args:
            job: The CronJob to execute.

        Returns:
            Result dict with execution metadata.
        """
        try:
            # Build the execution context
            output = await self._execute_job(job)

            # Deliver the result
            delivery = resolve_delivery(job.delivery)
            delivery_result = await delivery.deliver(job, output)

            return {
                "success": True,
                "output": output,
                "delivery": delivery_result.to_dict(),
            }

        except Exception as e:
            logger.error("Job %s execution error: %s", job.id, e, exc_info=True)

            # Try to deliver error message
            try:
                delivery = resolve_delivery(job.delivery)
                error_msg = f"Error: {e}"
                await delivery.deliver(job, error_msg)
            except Exception as deliver_err:
                logger.error("Failed to deliver error for job %s: %s", job.id, deliver_err)

            return {
                "success": False,
                "output": "",
                "error": str(e),
            }

    async def _execute_job(self, job: CronJob) -> str:
        """Execute a job's prompt through the orchestrator.

        In a full implementation, this would:
        1. Load the specified skills
        2. Override the model if configured
        3. Run the prompt through the orchestrator
        4. Return the result

        For now, returns a placeholder that can be extended.

        Args:
            job: The CronJob to execute.

        Returns:
            The execution result as a string.
        """
        # Log execution start
        logger.info(
            "Executing job: %s (prompt: %s)",
            job.name,
            job.prompt[:100],
        )

        # Build prompt with context
        execution_prompt = (
            f"[Scheduled Job]\n"
            f"Job: {job.name}\n"
            f"Schedule: {job.schedule}\n"
            f"Triggered at: {datetime.utcnow().isoformat()}\n\n"
            f"{job.prompt}"
        )

        # If skills are specified, add them to context
        if job.skills:
            execution_prompt += f"\n\nRequired skills: {', '.join(job.skills)}"

        # If model override is set, log it
        if job.model:
            logger.info("Using model override for job %s: %s", job.id, job.model)

        # Return a placeholder result - in production this would call the orchestrator
        result_text = (
            f"Job '{job.name}' executed successfully.\n"
            f"Prompt: {job.prompt}\n"
            f"Delivery: {job.delivery}\n"
            f"Completed at: {datetime.utcnow().isoformat()}"
        )

        # Call completion callback if registered
        if self._on_job_complete:
            try:
                self._on_job_complete(job, result_text)
            except Exception as e:
                logger.error("on_job_complete callback error: %s", e)

        return result_text

    # -- Internal scheduling loop --

    async def _run_loop(self) -> None:
        """Main scheduling loop. Runs until stopped."""
        logger.info("Scheduler run loop started")

        while self._running:
            try:
                await self._check_and_dispatch()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("Scheduler loop error: %s", e, exc_info=True)

            # Sleep for the check interval
            try:
                await asyncio.wait_for(
                    asyncio.sleep(self.config.check_interval),
                    timeout=self.config.check_interval + 1.0,
                )
            except asyncio.TimeoutError:
                pass
            except asyncio.CancelledError:
                raise

        logger.info("Scheduler run loop exited")

    async def _check_and_dispatch(self) -> None:
        """Check for due jobs and dispatch them."""
        now = datetime.now(tz=timezone.utc)
        jobs = self.storage.get_enabled_jobs()

        for job in jobs:
            if not job.enabled:
                continue

            # Check if job is due
            trigger = self._trigger_cache.get(job.id)
            if trigger is None:
                try:
                    trigger = parse_schedule(job.schedule)
                    self._trigger_cache[job.id] = trigger
                except Exception as e:
                    logger.error("Cannot parse schedule for job %s: %s", job.id, e)
                    continue

            if not trigger.is_due(now, job.last_run):
                continue

            # Check for missed runs (clock drift tolerance)
            if job.next_run and (now - job.next_run).total_seconds() > self.config.clock_drift_tolerance:
                logger.warning(
                    "Job %s missed scheduled run by %.0fs",
                    job.id,
                    (now - job.next_run).total_seconds(),
                )

            # Check if already running
            if job.id in self._active_jobs:
                continue

            # Update job state
            job.status = JobStatus.RUNNING
            job.updated_at = datetime.utcnow()
            self.storage.save(job)

            # Launch async execution
            task = asyncio.create_task(
                self._run_job_task(job),
                name=f"cron-job-{job.id[:8]}",
            )
            self._active_jobs[job.id] = task
            task.add_done_callback(lambda t: self._on_task_done(job.id, t))

            logger.info("Dispatched job: %s (next run: %s)", job.name, job.next_run)

    async def _run_job_task(self, job: CronJob) -> None:
        """Run a single job execution as a task."""
        try:
            await self.dispatch_job(job)
        except Exception as e:
            logger.error("Job task error for %s: %s", job.id, e)

    def _on_task_done(self, job_id: str, task: asyncio.Task) -> None:
        """Callback when a job task completes."""
        self._active_jobs.pop(job_id, None)
        # Re-check for due jobs after completion
        logger.debug("Job task done: %s", job_id)

    # -- Webhook integration --

    def set_webhook_server(self, server: Any) -> None:
        """Set the webhook server reference for delivery.

        Args:
            server: WebhookServer instance.
        """
        self._webhook_server = server

    def handle_webhook_event(
        self,
        webhook_name: str,
        payload: dict,
        events: list[str] | None = None,
    ) -> CronJob | None:
        """Handle a webhook event and trigger a matching job.

        Args:
            webhook_name: The webhook name/identifier.
            payload: The webhook payload data.
            events: List of event types from the webhook.

        Returns:
            The triggered CronJob, or None if no match found.
        """
        # This would match webhook events to scheduled jobs
        # For now, return None (full implementation would match
        # webhook payloads to job triggers)
        logger.info("Webhook event received for %s: %s", webhook_name, events)
        return None

    def shutdown(self) -> None:
        """Shut down the scheduler (convenience wrapper)."""
        if self._running:
            asyncio.create_task(self.stop())
