"""Filesystem sandbox: prevent path traversal and restrict writes."""

from __future__ import annotations

import logging
from pathlib import Path

from core.errors import PathTraversalError, SandboxViolation

logger = logging.getLogger(__name__)

# Paths that are NEVER allowed for read or write, even inside the sandbox.
_BLACKLIST: set[Path] = {
    Path("/etc/passwd"),
    Path("/etc/shadow"),
    Path("/etc/hosts"),
    Path.home() / ".ssh" / "id_rsa",
    Path.home() / ".ssh" / "id_ed25519",
}


class FilesystemSandbox:
    """Validate all file operations against a sandbox root."""

    def __init__(self, root: str | Path, allow_write: bool = True) -> None:
        self.root = Path(root).resolve()
        self.allow_write = allow_write

    def validate_path(self, path: str | Path, *, write: bool = False) -> Path:
        """
        Resolve *path* and ensure it stays within the sandbox.

        Raises:
            PathTraversalError: if resolved path escapes *root*.
            SandboxViolation: if write is requested but disallowed, or if
                the path is on the global blacklist.

        """
        target = Path(path).expanduser()
        resolved = (self.root / target).resolve() if not target.is_absolute() else target.resolve()

        # 1. Path-traversal guard
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise PathTraversalError(
                f"Path {resolved} escapes sandbox root {self.root}"
            ) from exc

        # 2. Blacklist guard
        if resolved in _BLACKLIST:
            raise SandboxViolation(f"Access to {resolved} is forbidden")

        # 3. Write guard
        if write and not self.allow_write:
            raise SandboxViolation(f"Write access denied for {resolved}")

        logger.debug("Sandbox OK: %s (write=%s)", resolved, write)
        return resolved
