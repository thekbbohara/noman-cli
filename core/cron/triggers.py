"""Trigger types for the noman-cli cron scheduler.

Defines the three scheduling mechanisms:
- CronTrigger: standard 5-field cron expressions
- IntervalTrigger: human-readable intervals (30m, 2h, 1d, etc.)
- OnceTrigger: one-shot execution
"""

from __future__ import annotations

import re
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import ClassVar

import croniter


class Trigger(ABC):
    """Abstract base for all trigger types."""

    kind: ClassVar[str]

    @abstractmethod
    def next_run(self, last_run: datetime | None = None) -> datetime:
        """Return the next scheduled datetime."""
        ...

    @abstractmethod
    def is_due(self, now: datetime, last_run: datetime | None = None) -> bool:
        """Check if the job is due to run now."""
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}>"


class CronTrigger(Trigger):
    """Standard 5-field cron expression trigger.

    Fields: minute hour day-of-month month day-of-week
    Supports: *, /, -, comma, and step values (e.g. */5, 1-30/2)
    """

    kind = "cron"

    def __init__(self, expression: str) -> None:
        """Initialize with a cron expression string.

        Args:
            expression: 5-field cron expression (e.g., '0 */6 * * *').
        """
        self.expression = expression
        self._iter = croniter.croniter(expression)

    def next_run(self, last_run: datetime | None = None) -> datetime:
        """Calculate the next run time from the cron expression.

        Args:
            last_run: Optional base time (defaults to now).

        Returns:
            Next scheduled datetime in UTC.
        """
        if last_run:
            self._iter.set_current(last_run)
        ts = self._iter.get_next(float)
        return datetime.fromtimestamp(ts, tz=timezone.utc)

    def is_due(self, now: datetime, last_run: datetime | None = None) -> bool:
        """Check if the job is due based on the cron schedule.

        Args:
            now: Current datetime.
            last_run: Last run time for context.

        Returns:
            True if the job should run now.
        """
        if last_run is None:
            # First run: always due if no last_run recorded
            return True
        # Check if the current time falls within the cron minute window
        return int(now.timestamp()) == int(self._iter.get_current(float))


class IntervalTrigger(Trigger):
    """Interval-based trigger supporting human-readable intervals.

    Formats: 30m (30 min), 2h (2 hours), 1d (1 day), 1w (1 week)
    """

    kind = "interval"

    # Regex to parse interval strings like '30m', '2h', '1d', '1w'
    _PATTERN: ClassVar[re.Pattern] = re.compile(
        r"^(?P<value>\d+)(?P<unit>[smhdw])$"
    )

    def __init__(self, interval: str) -> None:
        """Initialize with an interval string.

        Args:
            interval: Human-readable interval (e.g., '30m', '2h', '1d', '1w').
        """
        self.raw = interval
        match = self._PATTERN.match(interval)
        if not match:
            raise ValueError(
                f"Invalid interval format: '{interval}'. "
                "Expected format: <number><unit> where unit is s/m/h/d/w."
            )
        self._value = int(match.group("value"))
        self._unit = match.group("unit")

    @property
    def delta(self) -> timedelta:
        """Return the interval as a timedelta."""
        deltas = {
            "s": timedelta(seconds=self._value),
            "m": timedelta(minutes=self._value),
            "h": timedelta(hours=self._value),
            "d": timedelta(days=self._value),
            "w": timedelta(weeks=self._value),
        }
        return deltas[self._unit]

    def next_run(self, last_run: datetime | None = None) -> datetime:
        """Calculate the next run time from the last run or now.

        Args:
            last_run: Optional base time (defaults to now).

        Returns:
            Next scheduled datetime in UTC.
        """
        base = last_run or datetime.now(tz=timezone.utc)
        return base + self.delta

    def is_due(self, now: datetime, last_run: datetime | None = None) -> bool:
        """Check if the job is due based on the interval.

        Args:
            now: Current datetime.
            last_run: Last run time.

        Returns:
            True if the interval has elapsed.
        """
        if last_run is None:
            return True
        return now >= last_run + self.delta

    def __repr__(self) -> str:
        return f"<IntervalTrigger {self.raw}>"


class OnceTrigger(Trigger):
    """One-shot trigger that fires at a specific time.

    After firing once, it does not schedule further runs.
    """

    kind = "once"

    def __init__(self, at: datetime) -> None:
        """Initialize with a specific datetime.

        Args:
            at: The datetime to fire at.
        """
        self.at = at.replace(tzinfo=timezone.utc) if at.tzinfo is None else at

    def next_run(self, last_run: datetime | None = None) -> datetime:
        """Return the one-shot time.

        Args:
            last_run: Ignored for one-shot triggers.

        Returns:
            The scheduled datetime.
        """
        return self.at

    def is_due(self, now: datetime, last_run: datetime | None = None) -> bool:
        """Check if the scheduled time has passed.

        Args:
            now: Current datetime.
            last_run: Last run time.

        Returns:
            True if the scheduled time has passed and hasn't been run.
        """
        if last_run is not None:
            return False  # Already fired
        return now >= self.at

    def __repr__(self) -> str:
        return f"<OnceTrigger {self.at}>"


def parse_schedule(schedule: str) -> Trigger:
    """Parse a schedule string into the appropriate Trigger subclass.

    Supports:
    - Cron expressions: '0 */6 * * *', '30 2 * * *'
    - Interval strings: '30m', '2h', '1d', '1w'
    - Absolute datetime: ISO format or 'once:YYYY-MM-DDTHH:MM:SS'

    Args:
        schedule: Schedule expression string.

    Returns:
        A Trigger instance.

    Raises:
        ValueError: If the schedule format is not recognized.
    """
    # Check for one-shot syntax
    if schedule.startswith("once:") or schedule.lower() == "once":
        at_str = schedule.split(":", 1)[-1].strip()
        if at_str:
            try:
                at = datetime.fromisoformat(at_str)
                return OnceTrigger(at)
            except (ValueError, TypeError):
                pass
        # If no explicit time, just do it now
        return OnceTrigger(datetime.now(tz=timezone.utc))

    # Check for interval syntax (e.g., '30m', '2h', '1d')
    if IntervalTrigger._PATTERN.match(schedule):
        return IntervalTrigger(schedule)

    # Try as cron expression (5 fields)
    fields = schedule.strip().split()
    if len(fields) == 5:
        try:
            return CronTrigger(schedule)
        except (ValueError, croniter.CroniterBadCronError):
            pass

    raise ValueError(
        f"Cannot parse schedule: '{schedule}'. "
        "Use cron expression (5 fields), interval (e.g. '30m'), "
        "or 'once:YYYY-MM-DDTHH:MM:SS'."
    )
