"""Git safety: prevent destructive operations on protected branches."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import FrozenSet, List

from core.errors import SandboxViolation

logger = logging.getLogger(__name__)

_DEFAULT_PROTECTED: FrozenSet[str] = frozenset({"main", "master", "production"})


@dataclass(frozen=True)
class GitSafetyConfig:
    protected_branches: FrozenSet[str] = field(default_factory=lambda: _DEFAULT_PROTECTED)
    require_force_explicit: bool = True
    allow_delete_branch: bool = False


class SafeGitOperations:
    """Wrap git commands with safety checks."""

    def __init__(self, repo_path: str | Path, config: GitSafetyConfig | None = None) -> None:
        self.repo = Path(repo_path)
        self.config = config or GitSafetyConfig()

    def _run(self, cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
        logger.debug("git %s", " ".join(cmd))
        return subprocess.run(
            ["git", "-C", str(self.repo), *cmd],
            capture_output=True,
            text=True,
            check=check,
        )

    def current_branch(self) -> str:
        result = self._run(["branch", "--show-current"])
        return result.stdout.strip()

    def is_protected(self, branch: str | None = None) -> bool:
        branch = branch or self.current_branch()
        return branch in self.config.protected_branches

    def push(self, remote: str = "origin", branch: str | None = None, force: bool = False) -> None:
        branch = branch or self.current_branch()
        if force and self.is_protected(branch):
            raise SandboxViolation(
                f"Force push to protected branch '{branch}' is forbidden"
            )
        cmd = ["push", remote, branch]
        if force:
            cmd.insert(2, "--force-with-lease")
        self._run(cmd)

    def delete_branch(self, branch: str, force: bool = False) -> None:
        if not self.config.allow_delete_branch:
            raise SandboxViolation("Branch deletion is disabled")
        if self.is_protected(branch):
            raise SandboxViolation(
                f"Deletion of protected branch '{branch}' is forbidden"
            )
        flag = "-D" if force else "-d"
        self._run(["branch", flag, branch])

    def reset(self, target: str, hard: bool = False) -> None:
        if hard and self.is_protected():
            raise SandboxViolation(
                f"Hard reset on protected branch '{self.current_branch()}' is forbidden"
            )
        cmd = ["reset", "--hard" if hard else "--mixed", target]
        self._run(cmd)

    def status(self) -> str:
        return self._run(["status", "--short"]).stdout
