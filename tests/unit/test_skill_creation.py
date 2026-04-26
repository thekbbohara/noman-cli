"""Tests for skill queue and auto-skill-creation."""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import sys
import os

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.selfimprove.skill_queue import SkillQueue, SkillDraft
from core.selfimprove.critic import TraceCritic, TraceScore
from core.selfimprove.meta_agent import MetaAgent, ChangeType


class TestSkillQueue:
    """Test SkillQueue functionality."""

    @pytest.fixture
    def queue(self, tmp_path):
        """Create a temporary skill queue."""
        path = tmp_path / "test_suggestions.json"
        return SkillQueue(path=path)

    def test_add_and_list_draft(self, queue):
        """Test adding a draft and listing it."""
        draft_id = queue.add_draft(
            name="test_skill",
            description="Test description",
            content="# Test skill\n\n## Steps\n1. Do something",
            trigger_reason="High friction score",
            score=0.85,
        )
        assert draft_id is not None

        pending = queue.list_pending()
        assert len(pending) == 1
        assert pending[0].name == "test_skill"
        assert pending[0].score == 0.85

    def test_approve_draft(self, queue, tmp_path):
        """Test approving a draft creates the skill file."""
        draft_id = queue.add_draft(
            name="approved_skill_test12345",
            description="Should be approved",
            content="# Approved skill",
            trigger_reason="Test",
            score=0.9,
        )
        assert draft_id is not None, "add_draft should have succeeded"

        success, msg = queue.approve(draft_id)
        assert success is True

        # Check file was created
        skill_file = Path.home() / ".hermes/skills/approved_skill_test12345/SKILL.md"
        assert skill_file.exists()
        assert skill_file.read_text() == "# Approved skill"

        # Clean up
        import shutil
        skill_dir = skill_file.parent
        if skill_dir.exists():
            shutil.rmtree(skill_dir)

    def test_discard_draft(self, queue):
        """Test discarding a draft removes it from pending."""
        draft_id = queue.add_draft(
            name="discarded_skill",
            description="Should be discarded",
            content="# Discarded",
            trigger_reason="Test",
            score=0.5,
        )

        success, msg = queue.discard(draft_id)
        assert success is True

        pending = queue.list_pending()
        assert len(pending) == 0

    def test_duplicate_detection(self, queue):
        """Test that duplicate skill names are detected."""
        queue.add_draft(
            name="my_skill",
            description="First",
            content="# First",
            trigger_reason="Test",
            score=0.7,
        )

        # Adding another with same name should not create a duplicate
        draft_id2 = queue.add_draft(
            name="my_skill",
            description="Second",
            content="# Second",
            trigger_reason="Test",
            score=0.8,
        )

        pending = queue.list_pending()
        assert len(pending) == 1  # Only first draft remains
        assert pending[0].description == "First"

    def test_edit_draft(self, queue):
        """Test editing draft content."""
        draft_id = queue.add_draft(
            name="edit_skill",
            description="Original",
            content="# Original",
            trigger_reason="Test",
            score=0.7,
        )

        success, msg = queue.edit(draft_id, "# Updated")
        assert success is True

        draft = queue.get_draft(draft_id)
        assert draft.content == "# Updated"


class TestSkillWorthinessScoring:
    """Test the skill_suggestion_score dimension."""

    def test_no_friction_low_score(self):
        """Straightforward tasks should score low."""
        critic = TraceCritic()
        trace = {
            "turns": [
                {"tool": "read_file", "result": "Success"},
                {"tool": "write_file", "result": "Done"},
            ],
            "tool_calls": [
                {"tool": "read_file", "args": {"path": "test.py"}},
                {"tool": "write_file", "args": {"path": "test.py"}},
            ],
            "errors": [],
            "retries": [],
            "tokens": 1000,
        }

        score = critic.score(trace)
        # Should be low - no friction signals
        assert score.skill_suggestion_score < 0.5

    def test_user_correction_high_score(self):
        """User corrections should trigger higher scores."""
        critic = TraceCritic()
        trace = {
            "turns": [
                {
                    "tool": "browser_click",
                    "result": "User: Try clicking the submit button instead",
                },
                {"tool": "browser_click", "result": "Success"},
            ],
            "tool_calls": [
                {"tool": "browser_click", "args": {"ref": "@e5"}},
                {"tool": "browser_click", "args": {"ref": "@e10"}},
            ],
            "errors": [],
            "retries": [],
            "tokens": 2000,
        }

        score = critic.score(trace)
        # Should be higher due to correction signal from turn result
        assert score.skill_suggestion_score >= 0.15

    def test_error_overcome_high_score(self):
        """Errors overcome should trigger higher scores."""
        critic = TraceCritic()
        trace = {
            "turns": [
                {"tool": "terminal", "result": "Error: permission denied"},
                {"tool": "terminal", "result": "Error: file not found"},
                {"tool": "terminal", "result": "Success - created directory first"},
            ],
            "tool_calls": [
                {"tool": "terminal", "args": {"command": "ls"}},
                {"tool": "terminal", "args": {"command": "mkdir"}},
                {"tool": "terminal", "args": {"command": "ls"}},
            ],
            "errors": [
                {"message": "Permission denied"},
                {"message": "File not found"},
            ],
            "retries": [1, 2],
            "tokens": 5000,
        }

        score = critic.score(trace)
        # Should be higher due to errors overcome + complexity signals
        assert score.skill_suggestion_score >= 0.2

    def test_complex_task_high_score(self):
        """Complex multi-step tasks should score higher."""
        critic = TraceCritic()
        turns = []
        tool_calls = []
        for i in range(15):
            turns.append({"tool": f"tool_{i}", "result": "Step done"})
            tool_calls.append({"tool": f"tool_{i}", "args": {"arg": "val"}})

        trace = {
            "turns": turns,
            "tool_calls": tool_calls,
            "errors": [],
            "retries": [],
            "tokens": 15000,
        }

        score = critic.score(trace)
        # Should score higher due to complexity and multi-step signals
        assert score.skill_suggestion_score >= 0.12


class TestMetaAgentSkillCreation:
    """Test MetaAgent skill proposal generation."""

    def test_meta_agent_proposes_skill_on_high_score(self):
        """MetaAgent should queue skill drafts when score >= 0.7."""
        critic = TraceCritic()
        meta = MetaAgent(critic=critic)

        # Create a trace that should score high for skill suggestion
        trace = {
            "turns": [
                {"tool": "browser_navigate", "result": "Navigated to site"},
                {"tool": "browser_snapshot", "result": "Found login form"},
                {"tool": "browser_type", "result": "Error: element not found"},
                {"tool": "browser_click", "result": "User: Try type on input instead"},
                {"tool": "browser_type", "result": "Success"},
            ],
            "tool_calls": [
                {"tool": "browser_navigate", "args": {"url": "https://example.com"}},
                {"tool": "browser_snapshot", "args": {}},
                {"tool": "browser_type", "args": {"ref": "@e5", "text": "user"}},
                {"tool": "browser_click", "args": {"ref": "@e10"}},
                {"tool": "browser_type", "args": {"ref": "@e11", "text": "pass"}},
            ],
            "errors": [{"message": "Element not found"}],
            "retries": [2],
            "tokens": 3000,
        }

        result = meta.analyze(trace)

        # Check that a skill draft was queued
        assert result is not None

    def test_skill_name_inference(self):
        """Test that skill names are inferred from trace."""
        critic = TraceCritic()
        meta = MetaAgent(critic=critic)

        trace = {
            "turns": [
                {"tool": "browser_navigate", "result": "Navigated to login page"},
            ],
            "tool_calls": [],
            "errors": [],
            "retries": [],
            "tokens": 500,
        }

        score = critic.score(trace)
        name = meta._infer_skill_name(trace, score)
        assert name is not None
        assert name.startswith("skill_")


class TestCLISkillCommands:
    """Test CLI skill commands."""

    def test_skill_review_no_drafts(self, tmp_path, monkeypatch):
        """Review with no drafts shows message."""
        # Create a temp queue path
        queue_path = tmp_path / "test_suggestions.json"
        from core.selfimprove import skill_queue
        original_default = skill_queue.DEFAULT_QUEST_PATH
        skill_queue.DEFAULT_QUEST_PATH = queue_path
        try:
            from cli.main import _cmd_skill_review
            result = _cmd_skill_review()
            assert result == 0
        finally:
            skill_queue.DEFAULT_QUEST_PATH = original_default

    def test_skill_approve_valid_draft(self, tmp_path, monkeypatch):
        """Approving a valid draft succeeds."""
        queue_path = tmp_path / "test_suggestions2.json"
        # Set path BEFORE importing cli.main (module-level default is cached)
        from core.selfimprove import skill_queue as sq_module
        original_default = sq_module.DEFAULT_QUEST_PATH
        sq_module.DEFAULT_QUEST_PATH = queue_path
        try:
            queue = SkillQueue(path=queue_path)
            draft_id = queue.add_draft(
                name="test_approve_skill_xyz",
                description="Test",
                content="# Test",
                trigger_reason="Test",
                score=0.9,
            )

            from cli.main import _cmd_skill_approve
            result = _cmd_skill_approve(draft_id)
            assert result == 0
        finally:
            sq_module.DEFAULT_QUEST_PATH = original_default

    def test_skill_discard_valid_draft(self, tmp_path, monkeypatch):
        """Discarding a valid draft succeeds."""
        queue_path = tmp_path / "test_suggestions3.json"
        from core.selfimprove import skill_queue as sq_module
        original_default = sq_module.DEFAULT_QUEST_PATH
        sq_module.DEFAULT_QUEST_PATH = queue_path
        try:
            queue = SkillQueue(path=queue_path)
            draft_id = queue.add_draft(
                name="test_discard",
                description="Test",
                content="# Test",
                trigger_reason="Test",
                score=0.5,
            )

            from cli.main import _cmd_skill_discard
            result = _cmd_skill_discard(draft_id)
            assert result == 0
        finally:
            sq_module.DEFAULT_QUEST_PATH = original_default
