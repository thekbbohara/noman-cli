"""RollbackManager — creates and restores rollback points for self-modifications."""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default location for rollback snapshots.
DEFAULT_ROLLBACK_DIR = ".noman/rollbacks"
MAX_ROLLBACKS = 50


@dataclass
class RollbackEntry:
    """A single rollback snapshot record."""

    rollback_id: str
    timestamp: float
    target_path: str
    before_checksum: str
    after_checksum: str
    files_snapshot: dict[str, str] = field(default_factory=dict)
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON storage."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RollbackEntry:
        """Deserialize from dict."""
        return cls(**data)


def _compute_checksum(filepath: str | Path) -> str:
    """
    Return SHA-256 hex digest of a file's contents, or 'empty' if missing.

    Directories return 'dir' as their checksum marker.
    """
    p = Path(filepath)
    if not p.exists():
        return "empty"
    if p.is_dir():
        return "dir"
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_file_content(filepath: str | Path) -> str:
    """Read a file's text content; return '' if missing."""
    p = Path(filepath)
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


class RollbackManager:
    """
    Manages rollback points before self-modifications.

    Creates snapshot checkpoints stored as JSON in a configurable directory
    (default: ``.noman/rollbacks/``).  Each checkpoint captures file contents,
    checksums, and metadata.  Old rollbacks are auto-pruned to keep at most
    ``max_rollbacks`` entries.

    Attributes:
        rollback_dir:  Directory where rollback JSON files are stored.
        max_rollbacks: Maximum number of rollback entries to retain.
    """

    def __init__(
        self,
        rollback_dir: str | Path = DEFAULT_ROLLBACK_DIR,
        max_rollbacks: int = MAX_ROLLBACKS,
    ) -> None:
        self.rollback_dir = Path(rollback_dir)
        self.max_rollbacks = max_rollbacks
        self._ensure_dir()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_dir(self) -> None:
        """Create the rollback directory if it does not exist."""
        self.rollback_dir.mkdir(parents=True, exist_ok=True)

    def _list_entries(self) -> list[RollbackEntry]:
        """Load all stored rollback entries, newest first."""
        entries: list[RollbackEntry] = []
        if not self.rollback_dir.exists():
            return entries
        for fname in sorted(self.rollback_dir.iterdir(), reverse=True):
            if fname.suffix != ".json":
                continue
            try:
                data = json.loads(fname.read_text(encoding="utf-8"))
                entries.append(RollbackEntry.from_dict(data))
            except (json.JSONDecodeError, TypeError) as exc:
                logger.warning("Corrupt rollback file %s: %s", fname.name, exc)
        return entries

    def _prune(self) -> None:
        """Remove oldest rollback entries if we exceed ``max_rollbacks``."""
        entries = self._list_entries()
        if len(entries) <= self.max_rollbacks:
            return
        to_remove = entries[self.max_rollbacks :]
        for entry in to_remove:
            path = self.rollback_dir / f"{entry.rollback_id}.json"
            if path.exists():
                path.unlink()
                logger.info("Pruned old rollback: %s", entry.rollback_id)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_rollback(
        self,
        target_path: str | Path,
        message: str = "",
    ) -> str:
        """
        Create a rollback point and return its ID.

        Args:
            target_path:  File or directory path to snapshot.
            message:      Human-readable description of the change.

        Returns:
            A unique rollback ID string.
        """
        target = Path(target_path)
        rollback_id = f"rb_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"

        # Snapshot file contents before modification.
        files_snapshot: dict[str, str] = {}
        if target.is_file():
            files_snapshot[str(target)] = _read_file_content(target)
        elif target.is_dir():
            for sub in target.rglob("*"):
                if sub.is_file():
                    files_snapshot[str(sub)] = _read_file_content(sub)

        before_checksum = _compute_checksum(target)

        entry = RollbackEntry(
            rollback_id=rollback_id,
            timestamp=time.time(),
            target_path=str(target),
            before_checksum=before_checksum,
            after_checksum="pending",
            files_snapshot=files_snapshot,
            message=message,
        )

        path = self.rollback_dir / f"{rollback_id}.json"
        path.write_text(json.dumps(entry.to_dict(), indent=2), encoding="utf-8")
        logger.info("Rollback created: %s (target=%s)", rollback_id, target_path)

        self._prune()
        return rollback_id

    def execute_rollback(self, rollback_id: str) -> bool:
        """
        Restore files from a rollback entry.

        Args:
            rollback_id:  The rollback identifier to restore.

        Returns:
            ``True`` if the rollback was applied successfully, ``False``
            if the rollback was not found or could not be applied.
        """
        path = self.rollback_dir / f"{rollback_id}.json"
        if not path.exists():
            logger.error("Rollback not found: %s", rollback_id)
            return False

        data = json.loads(path.read_text(encoding="utf-8"))
        entry = RollbackEntry.from_dict(data)

        # Restore each file from the snapshot.
        restored_files: list[str] = []
        for file_path, content in entry.files_snapshot.items():
            fp = Path(file_path)
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content, encoding="utf-8")
            restored_files.append(file_path)
            logger.info("Restored: %s", file_path)

        if not restored_files:
            logger.warning("Rollback %s had no file content to restore", rollback_id)
            return False

        # Update entry to reflect completion.
        entry.after_checksum = "restored"
        path.write_text(json.dumps(entry.to_dict(), indent=2), encoding="utf-8")
        logger.info(
            "Rollback applied: %s (restored %d files)",
            rollback_id,
            len(restored_files),
        )
        return True

    def list_rollbacks(self) -> list[dict[str, Any]]:
        """Return a list of all stored rollback summaries."""
        return [e.to_dict() for e in self._list_entries()]

    def delete_rollback(self, rollback_id: str) -> bool:
        """Delete a specific rollback entry."""
        path = self.rollback_dir / f"{rollback_id}.json"
        if not path.exists():
            return False
        path.unlink()
        logger.info("Deleted rollback: %s", rollback_id)
        return True
