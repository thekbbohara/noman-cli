"""JobStorage: SQLite-backed persistence for cron jobs.

Provides CRUD operations for CronJob objects with automatic
connection pooling and migration support.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from core.cron.jobs import CronJob, JobStatus

logger = logging.getLogger(__name__)


class StorageError(Exception):
    """Base exception for storage operations."""


class StorageInitError(StorageError):
    """Raised when storage initialization fails."""


class JobNotFoundError(StorageError):
    """Raised when a job is not found in storage."""


class JobStorage:
    """SQLite-backed persistence layer for cron jobs.

    Jobs are serialized to JSON and stored in a single table.
    Supports migration from earlier schema versions.

    Args:
        db_path: Path to the SQLite database file.
    """

    SCHEMA_VERSION = 2
    _INIT_STMTS = [
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            schedule TEXT NOT NULL,
            prompt TEXT NOT NULL,
            delivery TEXT NOT NULL DEFAULT 'origin',
            skills TEXT NOT NULL DEFAULT '[]',
            model TEXT NOT NULL DEFAULT '{}',
            repeat INTEGER,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_run TEXT,
            next_run TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 0
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_jobs_enabled ON jobs(enabled)",
        "CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)",
        "CREATE INDEX IF NOT EXISTS idx_jobs_next_run ON jobs(next_run)",
        "CREATE INDEX IF NOT EXISTS idx_jobs_updated ON jobs(updated_at)",
        # Migration table to track schema version
        """
        CREATE TABLE IF NOT EXISTS _meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """,
    ]

    def __init__(self, db_path: str | Path = ".noman/cron_jobs.db") -> None:
        """Initialize storage, creating tables if needed.

        Args:
            db_path: Path to the SQLite database file.
        """
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._init()

    def _init(self) -> None:
        """Initialize the database schema."""
        conn = sqlite3.connect(str(self._path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")

        for stmt in self._INIT_STMTS:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError as e:
                # Table may already exist; ignore
                logger.debug("Schema init note: %s", e)

        # Ensure schema version is set
        try:
            conn.execute(
                "INSERT OR IGNORE INTO _meta (key, value) VALUES (?, ?)",
                ("schema_version", str(self.SCHEMA_VERSION)),
            )
            conn.commit()
        except sqlite3.OperationalError:
            pass

        self._conn = conn
        logger.info("JobStorage initialized at %s", self._path)

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        """Provide a connection with auto-commit on success."""
        conn = self._conn
        if conn is None:
            raise StorageError("Storage not initialized")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    # -- CRUD --

    def save(self, job: CronJob) -> CronJob:
        """Save or update a job.

        Args:
            job: The job to save.

        Returns:
            The saved job with updated timestamps.
        """
        data = job.to_dict()
        with self._session() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    id, name, schedule, prompt, delivery, skills,
                    model, repeat, enabled, created_at, updated_at,
                    last_run, next_run, status, attempts, max_attempts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    schedule=excluded.schedule,
                    prompt=excluded.prompt,
                    delivery=excluded.delivery,
                    skills=excluded.skills,
                    model=excluded.model,
                    repeat=excluded.repeat,
                    enabled=excluded.enabled,
                    updated_at=excluded.updated_at,
                    last_run=excluded.last_run,
                    next_run=excluded.next_run,
                    status=excluded.status,
                    attempts=excluded.attempts,
                    max_attempts=excluded.max_attempts
                """,
                (
                    data["id"],
                    data["name"],
                    data["schedule"],
                    data["prompt"],
                    data["delivery"],
                    json.dumps(data["skills"]),
                    json.dumps(data["model"]),
                    data["repeat"],
                    int(data["enabled"]),
                    data["created_at"],
                    data["updated_at"],
                    data["last_run"],
                    data["next_run"],
                    data["status"],
                    data["attempts"],
                    data["max_attempts"],
                ),
            )
        return job

    def get(self, job_id: str) -> CronJob:
        """Retrieve a job by ID.

        Args:
            job_id: The job UUID.

        Returns:
            The CronJob instance.

        Raises:
            JobNotFoundError: If no job with that ID exists.
        """
        with self._session() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if row is None:
            raise JobNotFoundError(f"Job not found: {job_id}")
        return self._row_to_job(row)

    def list_jobs(
        self,
        status: JobStatus | None = None,
        enabled_only: bool = False,
        limit: int = 100,
    ) -> list[CronJob]:
        """List jobs with optional filters.

        Args:
            status: Filter by JobStatus.
            enabled_only: If True, only return enabled jobs.
            limit: Maximum number of results.

        Returns:
            List of CronJob instances.
        """
        conditions: list[str] = []
        params: list = []

        if status:
            conditions.append("status = ?")
            params.append(status.value)
        if enabled_only:
            conditions.append("enabled = 1")

        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        sql = f"SELECT * FROM jobs{where} ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)

        with self._session() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_job(row) for row in rows]

    def delete(self, job_id: str) -> bool:
        """Delete a job by ID.

        Args:
            job_id: The job UUID.

        Returns:
            True if a row was deleted.
        """
        with self._session() as conn:
            cursor = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        return cursor.rowcount > 0

    def get_enabled_jobs(self) -> list[CronJob]:
        """Get all enabled jobs that have a next_run time."""
        with self._session() as conn:
            rows = conn.execute(
                """
                SELECT * FROM jobs
                WHERE enabled = 1 AND next_run IS NOT NULL
                  AND (status = 'pending' OR status = 'failed')
                ORDER BY next_run ASC
                """,
            ).fetchall()
        return [self._row_to_job(row) for row in rows]

    def count(self) -> int:
        """Return the total number of jobs."""
        with self._session() as conn:
            row = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()
        return row[0] if row else 0

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    # -- Internal --

    @staticmethod
    def _row_to_job(row: sqlite3.Row | tuple) -> CronJob:
        """Convert a database row to a CronJob."""
        data = {
            "id": row[0],
            "name": row[1],
            "schedule": row[2],
            "prompt": row[3],
            "delivery": row[4],
            "skills": json.loads(row[5]),
            "model": json.loads(row[6]),
            "repeat": row[7],
            "enabled": bool(row[8]),
            "created_at": row[9],
            "updated_at": row[10],
            "last_run": row[11],
            "next_run": row[12],
            "status": row[13],
            "attempts": row[14],
            "max_attempts": row[15],
        }
        return CronJob.from_dict(data)
