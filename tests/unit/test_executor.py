"""Tests for core/selfimprove/executor.py — ChangeExecutor with safety hooks."""

import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.selfimprove.change_tracker import ChangeTracker
from core.selfimprove.executor import ChangeExecutor, ExecutionResult
from core.selfimprove.meta_agent import ChangeType, ImprovementProposal
from core.selfimprove.rollback import RollbackManager


def _make_proposal(
    change_type: ChangeType = ChangeType.PROMPT_TWEAK,
    target_file: str = "test/target.py",
    old_content: str = "# old content\n",
    new_content: str = "# new content\n",
    confidence: float = 0.8,
    reasoning: str = "Test change",
) -> ImprovementProposal:
    """Helper to create test proposals."""
    return ImprovementProposal(
        proposal_id=f"test_{change_type.value}_{id(target_file)}",
        change_type=change_type,
        description=f"Test {change_type.value} in {target_file}",
        target_file=target_file,
        old_content=old_content,
        new_content=new_content,
        confidence=confidence,
        reasoning=reasoning,
    )


class TestExecutionResult:
    def test_summary_success(self):
        result = ExecutionResult(
            success=True,
            proposals_applied=["p1"],
            proposals_failed=[],
            rollback_triggered=False,
            rollback_id=None,
        )
        summary = result.summary()
        assert "OK" in summary
        assert "1 applied" in summary
        assert "0 failed" in summary

    def test_summary_failure(self):
        result = ExecutionResult(
            success=False,
            proposals_applied=[],
            proposals_failed=["p1"],
            rollback_triggered=True,
            rollback_id="rb_test",
            errors=["test error"],
        )
        summary = result.summary()
        assert "FAIL" in summary
        assert "rb_test" in summary
        assert "test error" in summary


class TestChangeExecutor:
    @pytest.fixture
    def tmp_project(self, tmp_path):
        """Create a temporary project directory."""
        root = tmp_path / "test_project"
        root.mkdir()
        # Create a git repo so snapshots work
        subprocess.run(["git", "init"], cwd=root, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=root, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=root, capture_output=True, check=True)
        return root

    @pytest.fixture
    def executor(self, tmp_project):
        return ChangeExecutor(
            project_root=tmp_project,
            rollback_mgr=RollbackManager(rollback_dir=str(tmp_project / "rollbacks")),
            require_git=True,
            max_changes_per_session=10,
        )

    def test_apply_single_file(self, tmp_project, executor):
        proposal = _make_proposal(
            target_file="hello.txt",
            old_content="old world",
            new_content="new world",
        )
        result = executor.execute([proposal])
        assert result.success is True
        assert len(result.proposals_applied) == 1
        assert (tmp_project / "hello.txt").read_text() == "new world"

    def test_multiple_proposals(self, tmp_project, executor):
        p1 = _make_proposal(
            target_file="a.txt",
            old_content="old a",
            new_content="new a",
        )
        p2 = _make_proposal(
            target_file="b.txt",
            old_content="old b",
            new_content="new b",
        )
        result = executor.execute([p1, p2])
        assert result.success is True
        assert len(result.proposals_applied) == 2
        assert (tmp_project / "a.txt").read_text() == "new a"
        assert (tmp_project / "b.txt").read_text() == "new b"

    def test_dry_run(self, tmp_project, executor):
        proposal = _make_proposal(
            target_file="dry.txt",
            old_content="old",
            new_content="new",
        )
        result = executor.execute([proposal], dry_run=True)
        assert result.success is True
        assert len(result.proposals_applied) == 0
        assert len(result.diffs) == 1
        assert "+new" in result.diffs[0]
        assert "-old" in result.diffs[0]
        # File should not be created
        assert not (tmp_project / "dry.txt").exists()

    def test_rate_limit(self, tmp_project):
        limited_executor = ChangeExecutor(
            project_root=tmp_project,
            rollback_mgr=RollbackManager(rollback_dir=str(tmp_project / "rollbacks")),
            max_changes_per_session=2,
        )
        proposals = [
            _make_proposal(target_file=f"ratelimit_{i}.txt", new_content=f"content{i}")
            for i in range(3)
        ]
        result = limited_executor.execute(proposals)
        assert result.success is False
        assert "exceeds limit" in result.errors[0]

    def test_reset_session_counter(self, tmp_project, executor):
        proposal = _make_proposal(target_file="reset.txt", new_content="reset")
        result = executor.execute([proposal])
        assert result.success is True
        executor.reset_session_counter()
        # Should be able to apply more
        result2 = executor.execute([proposal])
        assert result2.success is True

    def test_snapshot_exists_on_disk(self, tmp_project, executor):
        proposal = _make_proposal(target_file="snap.txt", new_content="snap content")
        executor.execute([proposal])
        # Check rollback dir has entries
        rb_dir = tmp_project / "rollbacks"
        json_files = list(rb_dir.glob("*.json"))
        assert len(json_files) > 0

    def test_create_snapshot_no_git(self, tmp_project):
        """Executor should work even without git (falls back to JSON)."""
        executor_no_git = ChangeExecutor(
            project_root=tmp_project,
            rollback_mgr=RollbackManager(rollback_dir=str(tmp_project / "rollbacks")),
            require_git=False,
        )
        proposal = _make_proposal(target_file="nogat.txt", new_content="no git needed")
        result = executor_no_git.execute([proposal])
        assert result.success is True
        assert (tmp_project / "nogat.txt").read_text() == "no git needed"

    def test_tracker_integration(self, tmp_project):
        """Test that executor works with ChangeTracker rate limiting."""
        tracker = ChangeTracker(
            max_changes_per_session=2,
            cooldown_seconds=0.0,
        )
        executor = ChangeExecutor(
            project_root=tmp_project,
            rollback_mgr=RollbackManager(rollback_dir=str(tmp_project / "rollbacks")),
        )

        # First two should work
        for i in range(2):
            result = executor.execute([_make_proposal(target_file=f"trk_{i}.txt", new_content="ok")])
            assert result.success is True
            tracker.record_change("test-sess", "prompt_tweak")

        # Third should be blocked by tracker
        allowed, reason = tracker.check_allowed("test-sess", "prompt_tweak")
        assert allowed is False
        assert "Max 2" in reason


class TestExecutionResultIntegration:
    def test_result_serialization(self):
        result = ExecutionResult(
            success=True,
            proposals_applied=["p1", "p2"],
            proposals_failed=["p3"],
            rollback_triggered=False,
            rollback_id=None,
            errors=["minor warning"],
        )
        assert result.success is True
        assert len(result.proposals_applied) == 2
        assert len(result.proposals_failed) == 1
        assert not result.rollback_triggered
        assert result.rollback_id is None
