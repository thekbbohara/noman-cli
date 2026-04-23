"""Tests for CLI argument parser."""

from cli.parser import parse_args


def test_task_mode():
    args = parse_args(["refactor auth module"])
    assert args.task == "refactor auth module"


def test_repl_mode():
    args = parse_args([])
    assert args.task is None


def test_doctor_command():
    args = parse_args(["doctor"])
    assert args.command == "doctor"


def test_emergency_stop():
    args = parse_args(["emergency", "stop"])
    assert args.command == "emergency"
    assert args.action == "stop"


def test_rollback_with_n():
    args = parse_args(["rollback", "--n", "3"])
    assert args.command == "rollback"
    assert args.n == 3
