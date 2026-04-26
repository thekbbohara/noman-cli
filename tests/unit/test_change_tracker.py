"""Tests for core/selfimprove/change_tracker.py."""

import time
import pytest

from core.selfimprove.change_tracker import ChangeTracker, SessionState


class TestSessionState:
    def test_defaults(self):
        state = SessionState(
            session_id="test-1",
            start_time=time.time(),
        )
        assert state.changes_count == 0
        assert state.change_types == {}
        assert state.last_change_time == 0.0
        assert state.max_session_seconds == 300

    def test_overdue(self):
        old_time = time.time() - 400
        state = SessionState(
            session_id="test-2",
            start_time=old_time,
        )
        assert state.is_overdue is True

    def test_not_overdue(self):
        state = SessionState(
            session_id="test-3",
            start_time=time.time(),
        )
        assert state.is_overdue is False


class TestChangeTracker:
    @pytest.fixture
    def tracker(self):
        return ChangeTracker(
            max_changes_per_session=5,
            cooldown_seconds=0.01,
            max_per_type=3,
            max_session_seconds=300,
        )

    def test_initial_allow(self, tracker):
        allowed, reason = tracker.check_allowed("sess-1", "prompt_tweak")
        assert allowed is True
        assert reason == "OK"

    def test_rate_limit_exceeded(self, tracker):
        for i in range(5):
            tracker.record_change("sess-2", "prompt_tweak")

        allowed, reason = tracker.check_allowed("sess-2", "prompt_tweak")
        assert allowed is False
        assert "Max 5" in reason

    def test_cooldown_enforced(self, tracker):
        tracker.record_change("sess-3", "prompt_tweak")
        # Immediately try again
        allowed, reason = tracker.check_allowed("sess-3", "prompt_tweak")
        assert allowed is False
        assert "Cooldown" in reason

    def test_cooldown_relaxes(self, tracker):
        tracker.record_change("sess-4", "prompt_tweak")
        time.sleep(0.05)  # Wait past 0.01s cooldown
        allowed, reason = tracker.check_allowed("sess-4", "prompt_tweak")
        assert allowed is True

    def test_per_type_limit(self, tracker):
        for i in range(3):
            tracker.record_change("sess-5", "prompt_tweak")

        allowed, reason = tracker.check_allowed("sess-5", "prompt_tweak")
        assert allowed is False
        assert "prompt_tweak" in reason

    def test_different_types_independent(self, tracker):
        for i in range(3):
            tracker.record_change("sess-6", "prompt_tweak")

        # Same type should be blocked
        allowed, _ = tracker.check_allowed("sess-6", "prompt_tweak")
        assert allowed is False

        # Wait for cooldown to expire
        time.sleep(0.05)

        # Different type should still be allowed
        allowed, reason = tracker.check_allowed("sess-6", "heuristic_addition")
        assert allowed is True
        assert reason == "OK"

    def test_record_change(self, tracker):
        tracker.record_change("sess-7", "prompt_tweak")
        info = tracker.get_session_info("sess-7")
        assert info["active"] is True
        assert info["changes_count"] == 1
        assert info["change_types"]["prompt_tweak"] == 1

    def test_reset(self, tracker):
        tracker.record_change("sess-8", "prompt_tweak")
        tracker.reset("sess-8")
        allowed, reason = tracker.check_allowed("sess-8", "prompt_tweak")
        assert allowed is True
        assert reason == "OK"

    def test_get_session_info_inactive(self, tracker):
        info = tracker.get_session_info("nonexistent")
        assert info["active"] is False

    def test_session_expiry(self):
        tracker = ChangeTracker(max_session_seconds=0.1)
        allowed, _ = tracker.check_allowed("sess-9", "prompt_tweak")
        assert allowed is True  # Fresh session

        time.sleep(0.15)
        allowed, reason = tracker.check_allowed("sess-9", "prompt_tweak")
        assert allowed is False
        assert "expired" in reason
