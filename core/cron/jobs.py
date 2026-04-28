"""CronJob dataclass and JobStatus enum for noman-cli cron system."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class JobStatus(Enum):
    """Lifecycle states for a scheduled job."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    CANCELLED = "cancelled"


@dataclass
class CronJob:
    """A scheduled task definition for the noman-cli cron system.

    Attributes:
        id: Unique job identifier (UUID4).
        name: Human-readable job name.
        schedule: Cron expression (5-field standard) or interval string
                  (e.g. '30m', '2h', '1d').
        prompt: Task description passed to the orchestrator.
        delivery: Delivery target: 'origin' (CLI), 'local' (file), or
                  'gateway:<chat_id>' (messaging gateway).
        skills: Optional list of skill names to load before execution.
        model: Optional model override dict (provider/model config).
        repeat: Number of times to repeat (None = forever).
        enabled: Whether the job is active in the scheduler.
        created_at: Timestamp of job creation.
        updated_at: Timestamp of last update.
        last_run: Timestamp of most recent execution.
        next_run: Timestamp of next scheduled execution.
        status: Current job status.
        attempts: Number of execution attempts made.
        max_attempts: Maximum retry attempts on failure (0 = no retry).
    """

    name: str
    schedule: str
    prompt: str
    delivery: str = "origin"
    skills: list[str] = field(default_factory=list)
    model: dict = field(default_factory=dict)
    repeat: int | None = None  # None = repeat forever
    enabled: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    last_run: datetime | None = None
    next_run: datetime | None = None
    status: JobStatus = JobStatus.PENDING
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    attempts: int = 0
    max_attempts: int = 0  # 0 means use global default

    def __post_init__(self) -> None:
        """Validate and normalize fields after dataclass init."""
        if not self.name.strip():
            raise ValueError("Job name must not be empty.")
        if not self.schedule.strip():
            raise ValueError("Schedule expression must not be empty.")
        if not self.prompt.strip():
            raise ValueError("Prompt must not be empty.")
        self.updated_at = datetime.utcnow()

    def to_dict(self) -> dict:
        """Serialize the job to a plain dict for storage."""
        return {
            "id": self.id,
            "name": self.name,
            "schedule": self.schedule,
            "prompt": self.prompt,
            "delivery": self.delivery,
            "skills": self.skills,
            "model": self.model,
            "repeat": self.repeat,
            "enabled": self.enabled,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "next_run": self.next_run.isoformat() if self.next_run else None,
            "status": self.status.value,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CronJob:
        """Deserialize a job from a plain dict."""
        def _parse_dt(val: str | None) -> datetime | None:
            if val is None:
                return None
            # Handle both with and without timezone suffix
            val = val.replace("Z", "+00:00")
            return datetime.fromisoformat(val)

        return cls(
            id=data.get("id", str(uuid.uuid4())),
            name=data["name"],
            schedule=data["schedule"],
            prompt=data["prompt"],
            delivery=data.get("delivery", "origin"),
            skills=data.get("skills", []),
            model=data.get("model", {}),
            repeat=data.get("repeat"),
            enabled=data.get("enabled", True),
            created_at=_parse_dt(data.get("created_at")) or datetime.utcnow(),
            updated_at=_parse_dt(data.get("updated_at")) or datetime.utcnow(),
            last_run=_parse_dt(data.get("last_run")),
            next_run=_parse_dt(data.get("next_run")),
            status=JobStatus(data.get("status", "pending")),
            attempts=data.get("attempts", 0),
            max_attempts=data.get("max_attempts", 0),
        )
