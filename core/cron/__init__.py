"""Cron scheduling system for noman-cli.

Provides async cron daemon with support for:
- Cron expression scheduling (standard 5-field format)
- Interval-based scheduling (30m, 2h, 1d, etc.)
- One-shot jobs
- Repeat counts
- Timezone awareness
- Auto-retry with exponential backoff
- SQLite-backed persistence
- Multiple delivery targets (origin, file, gateway)

Usage:
    from core.cron.manager import CronManager

    manager = CronManager()
    manager.create_job(
        name="daily-report",
        schedule="0 9 * * *",  # Every day at 9am
        prompt="Generate daily status report",
        delivery="gateway:chat123",
    )
    await manager.start()
"""

from __future__ import annotations

from core.cron.jobs import CronJob, JobStatus
from core.cron.scheduler import CronScheduler, SchedulerConfig, SchedulerState, SchedulerFullError
from core.cron.storage import JobNotFoundError, JobStorage, StorageError, StorageInitError
from core.cron.triggers import CronTrigger, IntervalTrigger, OnceTrigger, Trigger, parse_schedule
from core.cron.manager import CronManager

__all__ = [
    # Jobs
    "CronJob",
    "JobStatus",
    # Scheduler
    "CronScheduler",
    "SchedulerConfig",
    "SchedulerState",
    "SchedulerFullError",
    # Storage
    "JobStorage",
    "JobNotFoundError",
    "StorageError",
    "StorageInitError",
    # Triggers
    "CronTrigger",
    "IntervalTrigger",
    "OnceTrigger",
    "Trigger",
    "parse_schedule",
    # Manager
    "CronManager",
]
