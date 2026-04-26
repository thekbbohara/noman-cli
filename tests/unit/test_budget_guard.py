"""Tests for core/utils/budget_guard.py — Budget guard."""

import pytest

from core.errors import QuotaExceeded
from core.utils.budget_guard import BudgetConfig, BudgetGuard

# ── BudgetConfig ─────────────────────────────────────────────────────

def test_budget_config_defaults():
    cfg = BudgetConfig()
    assert cfg.max_tokens == 128_000
    assert cfg.warning_threshold == 0.75
    assert cfg.hard_stop_threshold == 0.90
    assert cfg.max_turns == 50


# ── BudgetGuard ──────────────────────────────────────────────────────

def test_budget_guard_initial_state():
    guard = BudgetGuard()
    assert guard.used == 0
    assert guard.remaining == 128_000
    summary = guard.summarize()
    assert summary["used"] == 0
    assert summary["remaining"] == 128_000
    assert summary["max_tokens"] == 128_000
    assert summary["turns"] == 0


def test_budget_guard_consume():
    guard = BudgetGuard()
    guard.consume(1000)
    assert guard.used == 1000
    assert guard.remaining == 127_000


def test_budget_guard_check_under_threshold():
    guard = BudgetGuard()
    guard.check(1000)
    guard.consume(1000)
    assert guard.used == 1000


def test_budget_guard_check_warning_threshold():
    guard = BudgetGuard(config=BudgetConfig(max_tokens=10000, warning_threshold=0.5))
    # 4000 tokens -> 40% (below warning)
    guard.check(4000)
    guard.consume(4000)
    assert guard.used == 4000


def test_budget_guard_check_hard_stop():
    guard = BudgetGuard(config=BudgetConfig(max_tokens=10000, hard_stop_threshold=0.9))
    # 9500 tokens -> 95% > 90% -> should raise
    with pytest.raises(QuotaExceeded):
        guard.check(9500)


def test_budget_guard_check_turn_limit():
    guard = BudgetGuard(config=BudgetConfig(max_turns=3))
    guard.check(100)
    guard.consume(100)
    guard.check(100)
    guard.consume(100)
    guard.check(100)
    guard.consume(100)
    # Next check should exceed turn limit
    with pytest.raises(QuotaExceeded) as exc_info:
        guard.check(100)
    assert "Turn limit exceeded" in str(exc_info.value)


def test_budget_guard_summarize():
    guard = BudgetGuard(config=BudgetConfig(max_tokens=10000))
    guard.check(3000)
    guard.consume(3000)
    summary = guard.summarize()
    assert summary["used"] == 3000
    assert summary["remaining"] == 7000
    assert summary["turns"] == 1


def test_budget_guard_custom_config():
    cfg = BudgetConfig(max_tokens=50000, warning_threshold=0.8, hard_stop_threshold=0.95)
    guard = BudgetGuard(config=cfg)
    assert guard.remaining == 50000
    # 40000 -> 80% (warning)
    guard.check(40000)
    guard.consume(40000)
    # 12000 more -> 64000/50000 = 128% (should raise)
    with pytest.raises(QuotaExceeded):
        guard.check(12000)
