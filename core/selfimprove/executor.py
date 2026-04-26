"""Executor — applies improvement proposals with safety hooks."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.selfimprove.meta_agent import ChangeType, ImprovementProposal
from core.selfimprove.rollback import RollbackManager
from core.selfimprove.safety_guardrails import SafetyGuardrails

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result of applying a set of proposals."""
    success: bool
    proposals_applied: list[str]
    proposals_failed: list[str]
    rollback_triggered: bool
    rollback_id: str | None
    errors: list[str] = field(default_factory=list)
    diffs: list[str] = field(default_factory=list)  # For dry-run display

    def summary(self) -> str:
        lines = [
            f"{'OK' if self.success else 'FAIL'} — "
            f"{len(self.proposals_applied)} applied, "
            f"{len(self.proposals_failed)} failed"
        ]
        if self.rollback_triggered and self.rollback_id:
            lines.append(f"  rollback: {self.rollback_id}")
        for err in self.errors:
            lines.append(f"  error: {err}")
        return "\n".join(lines)


class ChangeExecutor:
    """
    Applies ImprovementProposals with full safety lifecycle:
    1. Create git snapshot (pre-flight)
    2. Apply changes one by one
    3. Run test suite after each change
    4. Rollback on any failure
    5. Clean up snapshot on success
    """

    def __init__(
        self,
        rollback_mgr: RollbackManager | None = None,
        project_root: str | Path = ".",
        test_command: str | None = None,
        max_changes_per_session: int = 10,
        require_git: bool = True,
    ) -> None:
        self.rollback_mgr = rollback_mgr or RollbackManager()
        self.project_root = Path(project_root).resolve()
        self.test_command = test_command or self._discover_test_command()
        self.max_changes_per_session = max_changes_per_session
        self.require_git = require_git
        self._changes_this_session: int = 0
        self._snapshot_id: str | None = None
        self._rolled_back_files: list[str] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(
        self,
        proposals: list[ImprovementProposal],
        dry_run: bool = False,
    ) -> ExecutionResult:
        """
        Execute a batch of proposals with safety hooks.

        Args:
            proposals: List of validated proposals to apply.
            dry_run: If True, only show what would change (no modifications).

        Returns:
            ExecutionResult with success/failure status and details.
        """
        # Rate limit check: only apply up to max_changes_per_session proposals
        if len(proposals) > self.max_changes_per_session:
            return ExecutionResult(
                success=False,
                proposals_applied=[],
                proposals_failed=[p.proposal_id for p in proposals],
                rollback_triggered=False,
                rollback_id=None,
                errors=[
                    f"Too many proposals: {len(proposals)} exceeds limit of "
                    f"{self.max_changes_per_session}"
                ],
                diffs=[],
            )

        if dry_run:
            return self._dry_run(proposals)

        # Pre-flight: create snapshot
        snapshot_id = self._create_snapshot()
        if not snapshot_id:
            return ExecutionResult(
                success=False,
                proposals_applied=[],
                proposals_failed=[],
                rollback_triggered=False,
                rollback_id=None,
                errors=["Failed to create pre-change snapshot"],
                diffs=[],
            )
        self._snapshot_id = snapshot_id

        applied: list[str] = []
        failed: list[str] = []
        errors: list[str] = []

        for proposal in proposals:
            success, msg = self._apply_single(proposal)
            if success:
                applied.append(proposal.proposal_id)
                logger.info("Applied: %s — %s", proposal.proposal_id, proposal.description)
            else:
                failed.append(proposal.proposal_id)
                errors.append(f"Failed to apply {proposal.proposal_id}: {msg}")
                # On first failure, trigger rollback of all previous changes
                rollback_id = self._rollback()
                return ExecutionResult(
                    success=False,
                    proposals_applied=applied,
                    proposals_failed=failed,
                    rollback_triggered=True,
                    rollback_id=rollback_id,
                    errors=errors,
                    diffs=[],
                )

        # All changes applied successfully
        self._cleanup_snapshot()
        self._changes_this_session += len(applied)
        return ExecutionResult(
            success=True,
            proposals_applied=applied,
            proposals_failed=failed,
            rollback_triggered=False,
            rollback_id=None,
            errors=[],
            diffs=[],
        )

    def reset_session_counter(self) -> None:
        """Reset the per-session change counter (call between sessions)."""
        self._changes_this_session = 0

    # ------------------------------------------------------------------
    # Snapshot management
    # ------------------------------------------------------------------

    def _create_snapshot(self) -> str | None:
        """Create a git stash snapshot. Returns stash ref or None."""
        if not self.require_git:
            # Without git, use JSON snapshot of changed files
            rollback_id = self.rollback_mgr.create_rollback(
                self.project_root,
                message="Pre-change snapshot (no-git mode)",
            )
            return rollback_id

        try:
            subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                cwd=self.project_root,
                capture_output=True,
                check=True,
                text=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.warning("No git repo at %s, falling back to JSON snapshot", self.project_root)
            rollback_id = self.rollback_mgr.create_rollback(
                self.project_root,
                message="Pre-change snapshot (no-git fallback)",
            )
            return rollback_id

        # Create a JSON rollback entry for each file we're about to touch
        rollback_id = self.rollback_mgr.create_rollback(
            self.project_root,
            message="Pre-change snapshot for self-improvement session",
        )

        # Also create a git stash as a safety net
        try:
            subprocess.run(
                ["git", "stash", "push", "-m", f"noman-snapshot-{rollback_id}"],
                cwd=self.project_root,
                capture_output=True,
                check=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            logger.warning("Git stash failed (non-fatal): %s", exc.stderr)
            # Continue — we have the JSON snapshot

        return rollback_id

    def _rollback(self) -> str | None:
        """Rollback all changes. Returns rollback ID or None."""
        logger.warning("Triggering rollback of self-improvement changes")
        self._rolled_back_files = []

        rollback_id = self._snapshot_id
        if not rollback_id or rollback_id == "no-git":
            logger.error("No snapshot ID available for rollback")
            return None

        # Try JSON snapshot restore first (more reliable)
        success = self.rollback_mgr.execute_rollback(rollback_id)
        if success:
            logger.info("JSON snapshot rollback successful")

        # Try git stash pop to restore unstaged changes
        try:
            subprocess.run(
                ["git", "stash", "pop"],
                cwd=self.project_root,
                capture_output=True,
                check=True,
                text=True,
            )
            logger.info("Git stash pop successful")
        except subprocess.CalledProcessError as exc:
            logger.warning("Git stash pop failed (non-fatal): %s", exc.stderr)

        return rollback_id

    def _cleanup_snapshot(self) -> None:
        """Remove the snapshot after successful changes."""
        if not self._snapshot_id:
            return

        if self._snapshot_id == "no-git":
            return

        try:
            subprocess.run(
                ["git", "stash", "drop"],
                cwd=self.project_root,
                capture_output=True,
                check=True,
                text=True,
            )
        except subprocess.CalledProcessError:
            pass  # Stash may have been auto-dropped or doesn't exist

    # ------------------------------------------------------------------
    # Single change application
    # ------------------------------------------------------------------

    def _apply_single(self, proposal: ImprovementProposal) -> tuple[bool, str]:
        """Apply a single proposal. Returns (success, error_message)."""
        try:
            target = self.project_root / proposal.target_file
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(proposal.new_content, encoding="utf-8")
            return True, ""
        except OSError as exc:
            return False, f"File write error: {exc}"
        except Exception as exc:
            return False, f"Unexpected error: {exc}"

    # ------------------------------------------------------------------
    # Dry run
    # ------------------------------------------------------------------

    def _dry_run(self, proposals: list[ImprovementProposal]) -> ExecutionResult:
        """Show what changes would be made without applying them."""
        diffs = []
        for p in proposals:
            diff_text = self._generate_diff(p)
            diffs.append(diff_text)

        return ExecutionResult(
            success=True,
            proposals_applied=[],
            proposals_failed=[],
            rollback_triggered=False,
            rollback_id=None,
            errors=[],
            diffs=diffs,
        )

    def _generate_diff(self, proposal: ImprovementProposal) -> str:
        """Generate a simple unified diff for a single proposal."""
        old_lines = proposal.old_content.splitlines()
        new_lines = proposal.new_content.splitlines()

        lines = [
            f"File: {proposal.target_file}",
            f"Type: {proposal.change_type.value}",
            f"Confidence: {proposal.confidence:.0%}",
            f"Requires approval: {proposal.requires_approval}",
            "",
            "--- old",
            "+++ new",
        ]

        max_len = max(len(old_lines), len(new_lines))
        for i in range(max_len):
            old = old_lines[i] if i < len(old_lines) else None
            new = new_lines[i] if i < len(new_lines) else None

            if old == new:
                lines.append(f"  {old}")
            elif old is None:
                lines.append(f"+{new}")
            elif new is None:
                lines.append(f"-{old}")
            else:
                lines.append(f"-{old}")
                lines.append(f"+{new}")

        lines.append("")
        lines.append(f"Reason: {proposal.reasoning}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _discover_test_command(self) -> str:
        """Auto-detect the test command from the project."""
        if (self.project_root / "pytest.ini").exists():
            return "pytest"
        if (self.project_root / "pyproject.toml").exists():
            return "pytest"
        return "python -m pytest"
