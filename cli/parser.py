"""NoMan CLI argument parser."""

from __future__ import annotations

import argparse
import sys

_COMMANDS = {
    "doctor", "review", "rollback", "memory", "skill", "stats", "emergency",
    "init", "catalog",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="noman",
        description="NoMan -- a model-agnostic agentic coding CLI",
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

    # -- doctor --
    sub.add_parser("doctor", help="Run health checks on providers, config, memory, disk")

    # -- review --
    rev = sub.add_parser("review", help="Show diff of recent changes")
    rev.add_argument("file", nargs="?", default=None, help="Optional file to diff")
    rev.add_argument("--n", type=int, default=5, help="Number of recent commits to show (default: 5)")

    # -- rollback --
    rollback = sub.add_parser("rollback", help="Revert agent self-modifications")
    rollback.add_argument("--n", type=int, default=1, help="Number of changes to revert")
    rollback.add_argument("--to", dest="trace_id", help="Revert to specific trace ID")
    rollback.add_argument("-l", "--list", dest="list_rollbacks", action="store_true",
                          help="List available rollbacks instead of reverting")

    # -- memory --
    mem = sub.add_parser("memory", help="Memory operations")
    mem.add_argument("subcmd", choices=["list", "get", "set", "delete"],
                     help="Memory subcommand")
    mem.add_argument("tier", nargs="?", default=None, help="Memory tier: episodic|semantic|procedural")
    mem.add_argument("scope", nargs="?", default=None, help="Memory scope: project|global")
    mem.add_argument("key", nargs="?", default=None, help="Memory key")
    mem.add_argument("value", nargs="?", default=None, help="Memory value (for set)")
    mem.add_argument("--tier", dest="tier_filter", default=None,
                     help="Filter by tier (for list)")
    mem.add_argument("--scope", dest="scope_filter", default=None,
                     help="Filter by scope (for list)")

    # -- skill --
    skill = sub.add_parser("skill", help="Skill operations")
    skill.add_argument("subcmd", choices=["list", "get", "set", "add", "review", "approve", "discard", "patterns", "stats"],
                       help="Skill subcommand")
    skill.add_argument("name", nargs="?", default=None, help="Skill name")
    skill.add_argument("content", nargs="?", default=None, help="Skill content (for set/add)")
    skill.add_argument("file", nargs="?", default=None, help="Source file (for add)")
    skill.add_argument("draft_id", nargs="?", default=None, help="Draft ID (for approve/discard)")
    skill.add_argument("--min-occurrences", "-m", type=int, default=3, help="Min occurrences for pattern detection (for 'patterns')")

    # -- stats --
    sub.add_parser("stats", help="Show execution stats")

    # -- emergency --
    emerg = sub.add_parser("emergency", help="Emergency controls")
    emerg.add_argument("action", choices=["stop", "disable-self-improve", "read-only", "lockdown"],
                       help="Emergency action")

    # -- init --
    sub.add_parser("init", help="Scaffold .noman/ directory")

    # -- catalog --
    cat = sub.add_parser("catalog", help="List all Hermes agent tools and features")
    cat.add_argument("--tools", "-t", action="store_true", help="Show tools only")
    cat.add_argument("--skills", "-s", action="store_true", help="Show skills only")
    cat.add_argument("--summary", action="store_true", help="Show summary counts only")
    cat.add_argument("--by-category", "-c", action="store_true", help="Group by category")

    return parser


def parse_args(argv: list[str] | None = None):
    argv = list(argv) if argv is not None else sys.argv[1:]

    # Parse global flags first
    global_parser = build_parser()
    global_ns, remainder = global_parser.parse_known_args(argv)

    # If no remainder -> REPL mode
    if not remainder:
        global_ns.command = None
        global_ns.task = None
        return global_ns

    # If first remainder arg is a known command -> subparser mode
    if remainder[0] in _COMMANDS:
        sub_parser = build_subparsers()
        ns = sub_parser.parse_args(argv)
        ns.task = None
        return ns

    # Otherwise -> task mode (remainder is the task string)
    global_ns.command = None
    global_ns.task = " ".join(remainder)
    return global_ns
