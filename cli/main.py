"""NoMan CLI entrypoint."""

from __future__ import annotations

import logging
import sys

from cli.parser import parse_args

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def main(argv=None):
    args = parse_args(argv)

    if args.command == "doctor":
        print("noman doctor: not yet implemented")
        return 0
    if args.command == "review":
        print("noman review: not yet implemented")
        return 0
    if args.command == "rollback":
        print(f"noman rollback: not yet implemented (n={args.n})")
        return 0
    if args.command == "memory":
        print(f"noman memory {args.subcmd}: not yet implemented")
        return 0
    if args.command == "skill":
        print(f"noman skill {args.subcmd}: not yet implemented")
        return 0
    if args.command == "stats":
        print("noman stats: not yet implemented")
        return 0
    if args.command == "emergency":
        print(f"noman emergency {args.action}: not yet implemented")
        return 0

    # Default: run task or REPL
    if args.task:
        print(f"Running: {args.task}")
        print("(task execution not yet implemented)")
    else:
        print("NoMan interactive REPL — not yet implemented")
    return 0


if __name__ == "__main__":
    sys.exit(main())
