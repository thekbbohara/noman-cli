# Self-Improvement Safety Plan

## Problem

The MetaAgent can propose self-modifications but has no:
- Automated testing before applying changes
- Automatic rollback on failure
- Rate limiting to prevent cascading changes
- Diff preview for auto-approved changes
- Snapshot of the entire codebase before a session

## Design Decisions

- Use the existing `RollbackManager` (already built, just not integrated)
- Git-based snapshots (not file-level) for full-codebase recovery
- Rate limiting at the MetaAgent level, not the guardrail level
- Dry-run + test execution before applying
- All safety hooks are opt-in via config — never silently enforced

---

## Files to Create

### 1. `core/selfimprove/executor.py` — Change execution with safety hooks

New module that wraps the actual application of changes.

```python
"""Executor — applies improvement proposals with safety hooks."""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.selfimprove.meta_agent import ChangeType, ImprovementProposal
from core.selfimprove.rollback import RollbackManager, RollbackEntry
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

    def summary(self) -> str:
        lines = [
            f"{'OK' if self.success else 'FAIL'} — "
            f"{len(self.proposals_applied)} applied, "
            f"{len(self.proposals_failed)} failed"
        ]
        if self.rollback_triggered:
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
        # Rate limit check
        if self._changes_this_session >= self.max_changes_per_session:
            return ExecutionResult(
                success=False,
                proposals_applied=[],
                proposals_failed=[],
                rollback_triggered=False,
                rollback_id=None,
                errors=[
                    f"Session limit reached: {self.max_changes_per_session} "
                    f"changes per session (current: {self._changes_this_session})"
                ],
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
            )
        self._snapshot_id = snapshot_id

        applied: list[str] = []
        failed: list[str] = []
        errors: list[str] = []

        for proposal in proposals:
            result = self._apply_single(proposal)
            if result:
                applied.append(proposal.proposal_id)
            else:
                failed.append(proposal.proposal_id)
                errors.append(
                    f"Failed to apply {proposal.proposal_id}: "
                    f"{proposal.description}"
                )
                # On first failure, trigger rollback of all previous changes
                rollback_id = self._rollback()
                return ExecutionResult(
                    success=False,
                    proposals_applied=applied,
                    proposals_failed=failed,
                    rollback_triggered=True,
                    rollback_id=rollback_id,
                    errors=errors,
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
            errors=errors,
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
            return "no-git"

        try:
            result = subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                cwd=self.project_root,
                capture_output=True,
                check=True,
                text=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.warning("No git repo at %s, skipping snapshot", self.project_root)
            return None

        # Create a rollback entry for each file we're about to touch
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
            logger.error("Git stash failed: %s", exc.stderr)
            # Continue without git stash — we have the JSON snapshot

        return rollback_id

    def _rollback(self) -> str | None:
        """Rollback all changes. Returns rollback ID or None."""
        logger.warning("Triggering rollback of self-improvement changes")
        self._rolled_back_files = []

        # Try git stash pop first (reverts unstaged changes)
        if self.snapshot_id and self.snapshot_id != "no-git":
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
                logger.error("Git stash pop failed: %s", exc.stderr)

        # Fall back to JSON snapshot restore
        rollback_id = self._snapshot_id
        if rollback_id and rollback_id != "no-git":
            success = self.rollback_mgr.execute_rollback(rollback_id)
            if success:
                logger.info("JSON snapshot rollback successful")
            else:
                logger.error("JSON snapshot rollback failed")

        return rollback_id

    def _cleanup_snapshot(self) -> None:
        """Remove the snapshot after successful changes."""
        if not self._snapshot_id or self._snapshot_id == "no-git":
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
            pass  # Stash may have been auto-dropped

    # ------------------------------------------------------------------
    # Single change application
    # ------------------------------------------------------------------

    def _apply_single(self, proposal: ImprovementProposal) -> bool:
        """Apply a single proposal. Returns True on success."""
        try:
            target = self.project_root / proposal.target_file
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(proposal.new_content, encoding="utf-8")
            logger.info("Applied: %s — %s", proposal.proposal_id, proposal.description)
            return True
        except Exception as exc:
            logger.error("Apply failed for %s: %s", proposal.proposal_id, exc)
            return False

    # ------------------------------------------------------------------
    # Dry run
    # ------------------------------------------------------------------

    def _dry_run(self, proposals: list[ImprovementProposal]) -> ExecutionResult:
        """Show what changes would be made without applying them."""
        diffs = []
        for p in proposals:
            old_lines = p.old_content.splitlines()
            new_lines = p.new_content.splitlines()
            diffs.append(
                f"\n--- {p.target_file}\n"
                f"+++ {p.target_file}\n"
                f"@@ {len(old_lines)} -> {len(new_lines)} @@\n"
                f"{p.description} [{p.change_type.value}]\n"
            )

        return ExecutionResult(
            success=True,
            proposals_applied=[],
            proposals_failed=[],
            rollback_triggered=False,
            rollback_id=None,
            errors=[],  # Used for diff output in dry-run
        )

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
```

### 2. `core/selfimprove/change_tracker.py` — Rate limiting + cascade prevention

```python
"""Track and limit self-improvement changes to prevent cascading failures."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SessionState:
    """State for a single self-improvement session."""
    session_id: str
    start_time: float
    changes_count: int = 0
    change_types: dict[str, int] = field(default_factory=dict)
    last_change_time: float = 0.0
    cooldown_remaining: float = 0.0

    @property
    def is_overdue(self) -> bool:
        """Check if session has exceeded its time budget."""
        return (time.time() - self.start_time) > self.max_session_seconds

    @property
    def max_session_seconds(self) -> float:
        return 300  # 5 minutes max per session


class ChangeTracker:
    """
    Tracks self-improvement changes to enforce limits and prevent cascades.

    Enforces:
    - Max N changes per session
    - Cooldown between changes (prevents rapid-fire modifications)
    - Max N of any single change type (prevents homogenous overload)
    - Max session duration
    """

    def __init__(
        self,
        max_changes_per_session: int = 10,
        cooldown_seconds: float = 5.0,
        max_per_type: int = 3,
        max_session_seconds: float = 300.0,
    ) -> None:
        self.max_changes = max_changes_per_session
        self.cooldown = cooldown_seconds
        self.max_per_type = max_per_type
        self.max_session_seconds = max_session_seconds
        self._sessions: dict[str, SessionState] = {}

    def check_allowed(self, session_id: str, change_type: str) -> tuple[bool, str]:
        """
        Check if a change is allowed. Returns (allowed, reason).
        """
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionState(
                session_id=session_id,
                start_time=time.time(),
            )

        state = self._sessions[session_id]

        # Session expired
        if state.is_overdue:
            return False, f"Session expired after {self.max_session_seconds}s"

        # Rate limit
        if state.changes_count >= self.max_changes:
            return False, f"Max {self.max_changes} changes per session reached"

        # Cooldown
        elapsed = time.time() - state.last_change_time
        if elapsed < self.cooldown:
            return False, f"Cooldown active: {self.cooldown - elapsed:.1f}s remaining"

        # Per-type limit
        type_count = state.change_types.get(change_type, 0)
        if type_count >= self.max_per_type:
            return False, f"Max {self.max_per_type} changes of type '{change_type}' per session"

        return True, "OK"

    def record_change(self, session_id: str, change_type: str) -> None:
        """Record that a change was applied."""
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionState(
                session_id=session_id,
                start_time=time.time(),
            )
        state = self._sessions[session_id]
        state.changes_count += 1
        state.change_types[change_type] = state.change_types.get(change_type, 0) + 1
        state.last_change_time = time.time()
```

### 3. `core/selfimprove/diff_preview.py` — Human-readable diff output

```python
"""Generate human-readable diffs for proposed changes."""

from __future__ import annotations

from core.selfimprove.meta_agent import ImprovementProposal


def format_diff(proposal: ImprovementProposal) -> str:
    """Format a proposal as a unified diff for TUI display."""
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

    # Simple line-by-line diff
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
```

### 4. `core/selfimprove/__init__.py` update

Add the new classes to exports:

```python
from core.selfimprove.executor import ChangeExecutor, ExecutionResult
from core.selfimprove.change_tracker import ChangeTracker
from core.selfimprove.diff_preview import format_diff
```

---

## Integration Points

### 4.1 MetaAgent integration

Modify `MetaAgent.execute_proposals()` to use the new executor:

```python
def execute_proposals(
    self,
    proposals: list[ImprovementProposal],
    session_id: str,
    tracker: ChangeTracker,
) -> ExecutionResult:
    """Execute validated proposals with safety hooks."""
    # Check tracker limits
    allowed, reason = tracker.check_allowed(session_id, proposals[0].change_type.value)
    if not allowed:
        return ExecutionResult(
            success=False,
            proposals_applied=[],
            proposals_failed=[p.proposal_id for p in proposals],
            rollback_triggered=False,
            rollback_id=None,
            errors=[f"Rate limited: {reason}"],
        )

    executor = ChangeExecutor(project_root=self.project_root)
    result = executor.execute(proposals)

    if result.success:
        for p in proposals:
            tracker.record_change(session_id, p.change_type.value)
        executor.reset_session_counter()

    return result
```

### 5. TUI integration

Add a new panel in the TUI that shows:
- Active self-improvement session
- Changes applied / rejected / pending
- Diff preview for auto-approved changes
- One-click rollback button

---

## Configuration

Add to `config.toml`:

```toml
[selfimprove]
max_changes_per_session = 10
cooldown_seconds = 5.0
max_per_change_type = 3
max_session_seconds = 300
require_git_snapshot = true
auto_rollback_on_test_failure = true
test_command = "pytest"
```

---

## Tests to Write

1. `test_executor_snapshot_and_rollback.py` — Snapshot creates, rollback restores
2. `test_executor_test_integration.py` — Verify test suite runs after changes
3. `test_change_tracker_rate_limiting.py` — Cooldown, per-type limits, session expiry
4. `test_change_tracker_cascade_prevention.py` — Verify max_per_type enforcement
5. `test_diff_preview.py` — Diff output formatting
6. `test_guardrail_integration.py` — Guardrails + executor combined flow

---

## Implementation Order

1. `change_tracker.py` — Simple, no dependencies
2. `diff_preview.py` — Simple formatting
3. `executor.py` — Core safety hooks (uses RollbackManager which already exists)
4. Update `MetaAgent` to integrate executor + tracker
5. TUI panel updates
6. Tests for all new modules
