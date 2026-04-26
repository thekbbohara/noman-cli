"""Tests for core/utils/step_pruner.py — Step pruner."""


from core.utils.step_pruner import StepPruner


def test_should_execute_first_call():
    pruner = StepPruner()
    assert pruner.should_execute("read_file", args=("a.py",)) is True


def test_should_block_after_repeats():
    pruner = StepPruner(max_repeats=2)
    # First two calls should succeed (repeat_count 0 and 1)
    assert pruner.should_execute("read_file", args=("a.py",)) is True
    assert pruner.should_execute("read_file", args=("a.py",)) is True
    # Third call should be blocked (repeat_count >= max_repeats)
    assert pruner.should_execute("read_file", args=("a.py",)) is False


def test_should_allow_different_tool():
    pruner = StepPruner(max_repeats=2)
    pruner.should_execute("read_file", args=("a.py",))
    pruner.should_execute("read_file", args=("a.py",))
    # Different tool should still be allowed
    assert pruner.should_execute("edit_file", args=("a.py",)) is True


def test_should_allow_different_args():
    pruner = StepPruner(max_repeats=2)
    pruner.should_execute("read_file", args=("a.py",))
    pruner.should_execute("read_file", args=("a.py",))
    # Different args should still be allowed
    assert pruner.should_execute("read_file", args=("b.py",)) is True


def test_is_redundant():
    pruner = StepPruner()
    pruner.should_execute("read_file", args=("a.py",))
    assert pruner.is_redundant("read_file", args=("a.py",)) is True
    assert pruner.is_redundant("read_file", args=("b.py",)) is False


def test_is_redundant_no_history():
    pruner = StepPruner()
    assert pruner.is_redundant("read_file", args=("a.py",)) is False


def test_reset():
    pruner = StepPruner()
    pruner.should_execute("read_file", args=("a.py",))
    pruner.should_execute("read_file", args=("a.py",))
    pruner.reset()
    assert pruner.should_execute("read_file", args=("a.py",)) is True
    assert pruner.should_execute("read_file", args=("a.py",)) is True


def test_max_history_truncation():
    pruner = StepPruner(max_repeats=10, max_history=5)
    # Fill history beyond max
    for i in range(10):
        pruner.should_execute(f"tool_{i}", args=(f"file_{i}.py",))
    # History should be truncated
    assert len(pruner._history) <= 5


def test_should_execute_with_kwargs():
    pruner = StepPruner()
    assert pruner.should_execute("read_file", kwargs={"path": "a.py"}) is True
    assert pruner.is_redundant("read_file", kwargs={"path": "a.py"}) is True
