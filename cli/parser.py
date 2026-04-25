"""NoMan CLI argument parser."""

from __future__ import annotations

import argparse
import sys

_COMMANDS = {
    "doctor", "review", "rollback", "memory", "skill", "stats", "emergency",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="noman",
        description="NoMan — a model-agnostic agentic coding CLI",
        add_help=False,
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="Override the default model provider",
    )
    parser.add_argument(
        "--explain",
        action="store_true",
        help="Show reasoning before executing",
    )
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="Disable all write operations",
    )
    parser.add_argument(
        "--help", "-h",
        action="help",
        help="Show this help message and exit",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--max-calls",
        type=int,
        default=10,
        help="Max tool calls per turn (default: 10)",
    )
    return parser


def build_subparsers() -> argparse.ArgumentParser:
    parser = build_parser()
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("doctor", help="Run health checks")
    sub.add_parser("review", help="Review pending self-modifications")

    rollback = sub.add_parser("rollback", help="Revert agent changes")
    rollback.add_argument("--n", type=int, default=1, help="Number of changes to revert")
    rollback.add_argument("--to", dest="trace_id", help="Revert to specific trace ID")

    mem = sub.add_parser("memory", help="Memory operations")
    mem.add_argument("subcmd", choices=["ls", "search", "export", "import"])
    mem.add_argument("query", nargs="?")

    skill = sub.add_parser("skill", help="Skill operations")
    skill.add_argument("subcmd", choices=["ls", "show", "disable"])
    skill.add_argument("name", nargs="?")

    sub.add_parser("stats", help="Show token usage and success rates")

    emerg = sub.add_parser("emergency", help="Emergency controls")
    emerg.add_argument(
        "action",
        choices=["stop", "disable-self-improve", "read-only", "lockdown"],
    )

    return parser


def parse_args(argv: list[str] | None = None):
    argv = list(argv) if argv is not None else sys.argv[1:]

    # Parse global flags first
    global_parser = build_parser()
    global_ns, remainder = global_parser.parse_known_args(argv)

    # If no remainder → REPL mode
    if not remainder:
        global_ns.command = None
        global_ns.task = None
        return global_ns

    # If first remainder arg is a known command → subparser mode
    if remainder[0] in _COMMANDS:
        sub_parser = build_subparsers()
        ns = sub_parser.parse_args(argv)
        ns.task = None
        return ns

    # Otherwise → task mode (remainder is the task string)
    global_ns.command = None
    global_ns.task = " ".join(remainder)
    return global_ns
