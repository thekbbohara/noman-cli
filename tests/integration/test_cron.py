"""Integration tests for cron system."""

import pytest
import asyncio


async def test_cron_scheduler():
    """Test CronScheduler."""
    from core.cron.scheduler import CronScheduler
    scheduler = CronScheduler()
    assert scheduler is not None


async def test_cron_jobs():
    """Test CronJob dataclass."""
    from core.cron.jobs import CronJob, JobStatus
    assert JobStatus.PENDING.value == "pending"
    assert JobStatus.RUNNING.value == "running"
    assert JobStatus.COMPLETED.value == "completed"
    assert JobStatus.FAILED.value == "failed"


async def test_cron_storage():
    """Test JobStorage."""
    from core.cron.storage import JobStorage
    storage = JobStorage()
    assert storage is not None


async def test_cron_manager():
    """Test CronManager."""
    from core.cron.manager import CronManager
    manager = CronManager()
    assert manager is not None


async def test_cron_triggers():
    """Test trigger types."""
    from core.cron.triggers import TriggerType
    assert TriggerType.CRON.value == "cron"
    assert TriggerType.INTERVAL.value == "interval"
    assert TriggerType.ONCE.value == "once"
    assert TriggerType.WEBHOOK.value == "webhook"
