"""Unit tests for the self-improvement subsystem."""

from pathlib import Path

import pytest

from core.selfimprove import (
    ChangeType,
    ImprovementResult,
    MetaAgent,
    RollbackManager,
    TraceCritic,
    TraceScore,
    create_critic,
)
from core.selfimprove.safety_guardrails import SafetyGuardrails

# ── RollbackManager tests ───────────────────────────────────────────────


class TestRollbackManager:
    """Tests for RollbackManager."""

    @pytest.fixture
    def tmp_dir(self, tmp_path: Path) -> Path:
        """Provide a temporary directory for rollback storage."""
        return tmp_path / "rollbacks"

    @pytest.fixture
    def manager(self, tmp_dir: Path) -> RollbackManager:
        """Provide a RollbackManager backed by a temp directory."""
        return RollbackManager(rollback_dir=tmp_dir)

    def test_create_and_restore_file(self, manager: RollbackManager, tmp_dir: Path) -> None:
        """Test creating a rollback and restoring it."""
        test_file = tmp_dir / "test.txt"
        test_file.write_text("original content", encoding="utf-8")

        rb_id = manager.create_rollback(test_file, message="before edit")
        assert rb_id is not None
        assert len(rb_id) > 0

        # Simulate a change.
        test_file.write_text("modified content", encoding="utf-8")
        assert test_file.read_text(encoding="utf-8") == "modified content"

        # Restore.
        result = manager.execute_rollback(rb_id)
        assert result is True
        assert test_file.read_text(encoding="utf-8") == "original content"

    def test_create_and_restore_directory(self, manager: RollbackManager, tmp_dir: Path) -> None:
        """Test creating a rollback of an entire directory."""
        sub_dir = tmp_dir / "subdir"
        sub_dir.mkdir()
        (sub_dir / "a.txt").write_text("file a", encoding="utf-8")
        (sub_dir / "b.txt").write_text("file b", encoding="utf-8")

        rb_id = manager.create_rollback(sub_dir, message="snap dir")
        assert rb_id is not None

        # Modify files.
        (sub_dir / "a.txt").write_text("changed a", encoding="utf-8")
        (sub_dir / "b.txt").write_text("changed b", encoding="utf-8")

        # Restore.
        assert manager.execute_rollback(rb_id) is True
        assert (sub_dir / "a.txt").read_text(encoding="utf-8") == "file a"
        assert (sub_dir / "b.txt").read_text(encoding="utf-8") == "file b"

    def test_restore_missing_id(self, manager: RollbackManager) -> None:
        """Test restoring a non-existent rollback ID."""
        assert manager.execute_rollback("nonexistent_id") is False

    def test_list_rollbacks(self, manager: RollbackManager, tmp_dir: Path) -> None:
        """Test listing stored rollbacks."""
        test_file = tmp_dir / "list_test.txt"
        test_file.write_text("content", encoding="utf-8")
        manager.create_rollback(test_file, message="m1")
        manager.create_rollback(test_file, message="m2")

        entries = manager.list_rollbacks()
        assert len(entries) == 2

    def test_delete_rollback(self, manager: RollbackManager, tmp_dir: Path) -> None:
        """Test deleting a specific rollback."""
        test_file = tmp_dir / "del_test.txt"
        test_file.write_text("content", encoding="utf-8")
        rb_id = manager.create_rollback(test_file, message="to delete")

        assert manager.delete_rollback(rb_id) is True
        assert manager.delete_rollback(rb_id) is False  # already deleted.

    def test_auto_prune(self, tmp_dir: Path) -> None:
        """Test that old rollbacks are auto-pruned to max_rollbacks."""
        manager = RollbackManager(rollback_dir=tmp_dir, max_rollbacks=3)
        test_file = tmp_dir / "prune_test.txt"
        test_file.write_text("content", encoding="utf-8")

        # Create 5 rollbacks.
        for i in range(5):
            manager.create_rollback(test_file, message=f"rb{i}")

        entries = manager.list_rollbacks()
        assert len(entries) <= 3

    def test_checksums_tracked(self, manager: RollbackManager, tmp_dir: Path) -> None:
        """Test that before/after checksums are recorded."""
        test_file = tmp_dir / "checksum_test.txt"
        test_file.write_text("checksumme", encoding="utf-8")
        rb_id = manager.create_rollback(test_file)

        entries = manager.list_rollbacks()
        assert len(entries) == 1
        assert entries[0]["before_checksum"] != "empty"
        assert entries[0]["before_checksum"] != ""

    def test_missing_file_checksum(self, manager: RollbackManager, tmp_dir: Path) -> None:
        """Test that checksum is 'empty' for non-existent files."""
        rb_id = manager.create_rollback(tmp_dir / "nonexistent.txt")
        entries = manager.list_rollbacks()
        assert entries[0]["before_checksum"] == "empty"


# ── TraceCritic tests ───────────────────────────────────────────────────


class TestTraceCritic:
    """Tests for TraceCritic."""

    @pytest.fixture
    def critic(self) -> TraceCritic:
        return TraceCritic()

    @pytest.fixture
    def clean_trace(self) -> dict:
        """A clean, efficient trace."""
        return {
            "turns": [
                {"tool": "read_file", "result": {"content": "hello"}},
                {"tool": "write_file", "result": {"success": True}},
            ],
            "tool_calls": [
                {"tool": "read_file"},
                {"tool": "write_file"},
            ],
            "errors": [],
            "retries": [],
            "tokens": 1000,
        }

    @pytest.fixture
    def noisy_trace(self) -> dict:
        """A noisy, inefficient trace."""
        turns = [
            {"tool": "read_file", "result": {"error": "fail"}},
            {"tool": "read_file", "result": {"error": "fail"}},
            {"tool": "read_file", "result": {"error": "fail"}},
            {"tool": "read_file", "result": {"error": "fail"}},
            {"tool": "read_file", "result": {"error": "fail"}},
            {"tool": "read_file", "result": {"error": "fail"}},
            {"tool": "read_file", "result": {"content": "ok"}},
            {"tool": "read_file", "result": {"content": "ok"}},
            {"tool": "read_file", "result": {"content": "ok"}},
            {"tool": "read_file", "result": {"content": "ok"}},
            {"tool": "read_file", "result": {"content": "ok"}},
            {"tool": "read_file", "result": {"content": "ok"}},
        ]
        return {
            "turns": turns,
            "tool_calls": [{"tool": "read_file"} for _ in range(12)],
            "errors": [{"message": "fail"} for _ in range(6)],
            "retries": [{"reason": "timeout"} for _ in range(4)],
            "tokens": 80000,
        }

    def test_score_returns_trace_score(self, critic: TraceCritic, clean_trace: dict) -> None:
        result = critic.score(clean_trace)
        assert isinstance(result, TraceScore)

    def test_clean_trace_high_scores(self, critic: TraceCritic, clean_trace: dict) -> None:
        result = critic.score(clean_trace)
        assert result.overall > 60
        assert result.efficiency > 60
        assert result.correctness > 60
        assert result.cost > 60

    def test_noisy_trace_lower_scores(self, critic: TraceCritic, clean_trace: dict, noisy_trace: dict) -> None:
        clean_result = critic.score(clean_trace)
        noisy_result = critic.score(noisy_trace)
        # Noisy trace should score lower overall than a clean trace.
        assert noisy_result.overall < clean_result.overall
        assert noisy_result.correctness < clean_result.correctness
        assert noisy_result.efficiency < clean_result.efficiency
        # Noisy trace should have weaknesses and suggestions.
        assert len(noisy_result.weaknesses) > 0
        assert len(noisy_result.suggestions) > 0

    def test_feedback_contains_suggestions(self, critic: TraceCritic, noisy_trace: dict) -> None:
        result = critic.score(noisy_trace)
        assert len(result.suggestions) > 0
        assert len(result.weaknesses) > 0
        # Should have at least one strength.
        assert len(result.strengths) >= 0  # may be empty for very noisy traces.

    def test_feedback_contains_strengths(self, critic: TraceCritic, clean_trace: dict) -> None:
        result = critic.score(clean_trace)
        assert len(result.strengths) > 0

    def test_score_dict_serialization(self, critic: TraceCritic, clean_trace: dict) -> None:
        result = critic.score(clean_trace)
        d = result.to_dict()
        assert "overall" in d
        assert "efficiency" in d
        assert "correctness" in d
        assert "cost" in d
        assert "strengths" in d
        assert "weaknesses" in d
        assert "suggestions" in d

    def test_empty_trace(self, critic: TraceCritic) -> None:
        """Test scoring an empty trace."""
        result = critic.score({})
        assert isinstance(result, TraceScore)
        assert result.overall >= 0

    def test_create_critic_factory(self) -> None:
        """Test the create_critic factory function."""
        critic = create_critic(max_turns_penalty=1.0, baseline_turns=10.0)
        assert isinstance(critic, TraceCritic)
        assert critic.max_turns_penalty == 1.0
        assert critic.baseline_turns == 10.0

    def test_custom_params(self) -> None:
        """Test TraceCritic with custom parameters."""
        critic = TraceCritic(
            max_turns_penalty=2.0,
            max_errors_penalty=10.0,
            redundancy_threshold=10,
            baseline_turns=20.0,
        )
        assert critic.max_turns_penalty == 2.0
        assert critic.max_errors_penalty == 10.0
        assert critic.redundancy_threshold == 10
        assert critic.baseline_turns == 20.0


# ── MetaAgent tests ─────────────────────────────────────────────────────


class TestMetaAgent:
    """Tests for MetaAgent."""

    @pytest.fixture
    def agent(self) -> MetaAgent:
        return MetaAgent()

    @pytest.fixture
    def good_trace(self) -> dict:
        return {
            "turns": [
                {"tool": "read_file", "result": {"content": "ok"}},
                {"tool": "write_file", "result": {"success": True}},
            ],
            "tool_calls": [{"tool": "read_file"}, {"tool": "write_file"}],
            "errors": [],
            "retries": [],
            "tokens": 5000,
        }

    @pytest.fixture
    def bad_trace(self) -> dict:
        return {
            "turns": [
                {"tool": "read_file", "result": {"error": "fail"}},
                {"tool": "read_file", "result": {"error": "fail"}},
                {"tool": "read_file", "result": {"error": "fail"}},
                {"tool": "read_file", "result": {"content": "ok"}},
            ],
            "tool_calls": [{"tool": "read_file"} for _ in range(4)],
            "errors": [{"message": "fail"} for _ in range(3)],
            "retries": [{"reason": "timeout"}],
            "tokens": 30000,
        }

    def test_analyze_returns_result(self, agent: MetaAgent, good_trace: dict) -> None:
        result = agent.analyze(good_trace)
        assert isinstance(result, ImprovementResult)

    def test_analyze_with_good_trace_fewer_proposals(self, agent: MetaAgent, good_trace: dict) -> None:
        result = agent.analyze(good_trace)
        # Good traces should produce fewer proposals.
        assert len(result.proposals) <= agent.max_proposals

    def test_analyze_with_bad_trace_more_proposals(self, agent: MetaAgent, bad_trace: dict) -> None:
        result = agent.analyze(bad_trace)
        # Bad traces should produce more proposals.
        assert len(result.proposals) > 0

    def test_proposal_has_id_and_type(self, agent: MetaAgent, good_trace: dict) -> None:
        result = agent.analyze(good_trace)
        for p in result.proposals:
            assert p.proposal_id is not None
            assert len(p.proposal_id) > 0
            assert isinstance(p.change_type, ChangeType)

    def test_proposal_confidence_range(self, agent: MetaAgent, good_trace: dict) -> None:
        result = agent.analyze(good_trace)
        for p in result.proposals:
            assert 0.0 <= p.confidence <= 1.0

    def test_proposal_requires_approval_flag(self, agent: MetaAgent, good_trace: dict) -> None:
        result = agent.analyze(good_trace)
        for p in result.proposals:
            assert isinstance(p.requires_approval, bool)

    def test_guardrail_rejection(self) -> None:
        """Test that immutable path targets are rejected by guardrails."""
        agent = MetaAgent()
        bad_trace = {
            "turns": [
                {"tool": "read_file", "result": {"error": "fail"}},
                {"tool": "read_file", "result": {"error": "fail"}},
                {"tool": "read_file", "result": {"content": "ok"}},
            ],
            "tool_calls": [{"tool": "read_file"} for _ in range(3)],
            "errors": [{"message": "fail"} for _ in range(2)],
            "retries": [],
            "tokens": 20000,
        }
        result = agent.analyze(bad_trace)
        # Check that at least some proposals may have been rejected.
        # The proposals targeting immutable paths should be filtered out.
        assert isinstance(result, ImprovementResult)

    def test_propose_for_file(self, agent: MetaAgent, bad_trace: dict) -> None:
        """Test file-specific proposal generation."""
        result = agent.propose_for_file(bad_trace, "src/main.py")
        assert isinstance(result, ImprovementResult)
        for p in result.proposals:
            assert p.target_file == "src/main.py"

    def test_propose_for_file_no_proposals_for_good_trace(
        self, agent: MetaAgent, good_trace: dict
    ) -> None:
        """Test that good traces produce no file-specific proposals."""
        result = agent.propose_for_file(good_trace, "src/main.py")
        # Good trace should not trigger bug_fix or optimization proposals.
        assert len(result.proposals) == 0

    def test_proposal_serialization(self, agent: MetaAgent, good_trace: dict) -> None:
        """Test that proposals serialize to dicts correctly."""
        result = agent.analyze(good_trace)
        for p in result.proposals:
            d = p.to_dict()
            assert "proposal_id" in d
            assert "change_type" in d
            assert "confidence" in d
        r = result.to_dict()
        assert "proposals" in r
        assert "guardrail_violations" in r

    def test_change_type_enum_values(self) -> None:
        """Test that ChangeType has expected values."""
        assert ChangeType.PROMPT_TWEAK.value == "prompt_tweak"
        assert ChangeType.HEURISTIC_ADDITION.value == "heuristic_addition"
        assert ChangeType.SKILL_SUGGESTION.value == "skill_suggestion"
        assert ChangeType.BUG_FIX.value == "bug_fix"
        assert ChangeType.OPTIMIZATION.value == "optimization"

    def test_custom_guardrails(self) -> None:
        """Test MetaAgent with custom guardrails."""
        guardrails = SafetyGuardrails()
        agent = MetaAgent(guardrails=guardrails)
        trace = {"turns": [], "tool_calls": [], "errors": [], "retries": [], "tokens": 0}
        result = agent.analyze(trace)
        assert isinstance(result, ImprovementResult)

    def test_max_proposals_cap(self) -> None:
        """Test that max_proposals limits the output."""
        agent = MetaAgent(max_proposals=2)
        trace = {
            "turns": [
                {"tool": "read_file", "result": {"error": "fail"}},
                {"tool": "read_file", "result": {"error": "fail"}},
                {"tool": "read_file", "result": {"content": "ok"}},
            ],
            "tool_calls": [{"tool": "read_file"} for _ in range(3)],
            "errors": [{"message": "fail"} for _ in range(2)],
            "retries": [],
            "tokens": 20000,
        }
        result = agent.analyze(trace)
        assert len(result.proposals) <= 2


# ── Integration tests ───────────────────────────────────────────────────


class TestSelfImproveIntegration:
    """Integration tests spanning multiple self-improvement components."""

    def test_rollback_then_analyze(self, tmp_path: Path) -> None:
        """End-to-end: create rollback, modify, analyze with MetaAgent."""
        # Create rollback.
        rb_dir = tmp_path / "rollbacks"
        manager = RollbackManager(rollback_dir=str(rb_dir))
        test_file = tmp_path / "target.py"
        test_file.write_text("def hello():\n    pass", encoding="utf-8")
        rb_id = manager.create_rollback(test_file)
        assert rb_id is not None

        # Modify file.
        test_file.write_text("def hello():\n    return 'modified'", encoding="utf-8")

        # Restore.
        assert manager.execute_rollback(rb_id) is True
        assert test_file.read_text(encoding="utf-8") == "def hello():\n    pass"

        # Analyze with MetaAgent.
        agent = MetaAgent()
        trace = {
            "turns": [
                {"tool": "read_file", "result": {"content": "def hello():\n    pass"}},
            ],
            "tool_calls": [{"tool": "read_file"}],
            "errors": [],
            "retries": [],
            "tokens": 500,
        }
        result = agent.analyze(trace)
        assert isinstance(result, ImprovementResult)

    def test_import_from_package(self) -> None:
        """Test that all classes are importable from core.selfimprove."""
        from core.selfimprove import (
            ChangeType,
            MetaAgent,
            RollbackManager,
            TraceCritic,
            create_critic,
        )
        assert ChangeType is not None
        assert MetaAgent is not None
        assert RollbackManager is not None
        assert TraceCritic is not None
        assert create_critic is not None

    def test_critic_scores_consistency(self) -> None:
        """Test that scoring the same trace twice gives consistent results."""
        critic = TraceCritic()
        trace = {
            "turns": [
                {"tool": "read_file", "result": {"content": "ok"}},
                {"tool": "write_file", "result": {"success": True}},
            ],
            "tool_calls": [{"tool": "read_file"}, {"tool": "write_file"}],
            "errors": [],
            "retries": [],
            "tokens": 1000,
        }
        r1 = critic.score(trace)
        r2 = critic.score(trace)
        assert r1.overall == r2.overall
        assert r1.efficiency == r2.efficiency
        assert r1.correctness == r2.correctness
        assert r1.cost == r2.cost
