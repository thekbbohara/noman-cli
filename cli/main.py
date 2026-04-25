"""NoMan CLI entrypoint."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from cli.parser import parse_args
from core.adapters import create_adapter
from core.context import ContextManager
from core.memory import MemorySystem
from core.orchestrator import Orchestrator, OrchestratorConfig

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def _setup_debug_logging() -> None:
    """Enable DEBUG logging if --debug flag is set."""
    if os.environ.get("NOMAN_DEBUG"):
        logging.getLogger().setLevel(logging.DEBUG)
        logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s")


def _load_config() -> dict:
    """Load user config from file."""
    config_path = Path(__file__).resolve().parents[1] / "user" / "config.toml"
    if not config_path.exists():
        return _default_config()

    try:
        from importlib.util import find_spec
        if find_spec("tomllib"):
            import tomllib  # noqa: F401
            return tomllib.loads(config_path.read_text())
    except Exception:
        pass

    return _default_config()


def _default_config() -> dict:
    """Default configuration."""
    return {
        "providers": {
            "default": {
                "type": "openai",
                "api_key": os.environ.get("OPENAI_API_KEY", ""),
                "model": "gpt-4o-mini",
            }
        },
        "default_provider": "default",
    }


def _create_orchestrator(args) -> Orchestrator | None:
    """Create and configure orchestrator."""
    config = _load_config()

    # Use --provider flag if provided, otherwise from model.default or default_provider
    provider_name = args.provider or config.get("model", {}).get("default") \
        or config.get("default_provider", "default")

    # Support both list and dict formats
    providers = config.get("providers", [])
    if isinstance(providers, list):
        provider_config = next((p for p in providers if p.get("id") == provider_name), None)
    else:
        provider_config = providers.get(provider_name, {})

    if not provider_config:
        logger.error(f"Provider '{provider_name}' not found")
        return None

    # Inject max_context_tokens from config if not set on provider
    if not provider_config.get("max_context_tokens"):
        token_budget = config.get("model", {}).get("token_budget", {})
        if token_budget.get("max_tokens"):
            provider_config = dict(provider_config, max_context_tokens=token_budget["max_tokens"])

    # Create adapter
    try:
        adapter = create_adapter(provider_config)
    except Exception as e:
        logger.error(f"Failed to create adapter: {e}")
        return None

    # Create tool bus
    from core.tools import create_toolbus
    tool_bus = create_toolbus(Path.cwd())

    # Create context manager
    context = ContextManager(Path.cwd())

    # Create memory
    memory = MemorySystem()

    # Create orchestrator
    max_calls = getattr(args, 'max_calls', None)
    orch_config = OrchestratorConfig(
        max_turns=20,
        max_tokens_per_turn=8000,
        max_tool_calls_per_turn=max_calls if max_calls else 10,
    )

    return Orchestrator(
        adapter=adapter,
        tools=tool_bus,
        config=orch_config,
        context=context,
        memory=memory,
    )


def main(argv=None):
    args = parse_args(argv)

    if args.debug:
        os.environ["NOMAN_DEBUG"] = "1"
        _setup_debug_logging()

    if args.command == "doctor":
        print("NoMan doctor: checking configuration...")
        config = _load_config()
        providers = config.get("providers", [])
        if isinstance(providers, list):
            print(f"✓ Config loaded: {len(providers)} provider(s)")
        else:
            print(f"✓ Config loaded: {len(providers)} provider(s)")

        # Check context
        context = ContextManager(Path.cwd())
        print("✓ Context manager initialized")

        # Check memory
        memory = MemorySystem()
        print(f"✓ Memory system initialized ({memory._store.count()} memories)")
        memory.close()

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

        # Create orchestrator
        orch = _create_orchestrator(args)
        if orch is None:
            logger.error("Failed to create orchestrator")
            return 1

        # Run task
        import asyncio
        try:
            result = asyncio.run(orch.run(args.task))
            print(f"\nResult: {result}")
        except KeyboardInterrupt:
            print("\nInterrupted")
            return 130
        except Exception as e:
            logger.error(f"Error: {e}")
            return 1

        return 0
    else:
        # Run TUI REPL
        from cli.tui import run_tui
        orch = _create_orchestrator(args)
        if orch is None:
            logger.error("Failed to create orchestrator")
            return 1
        run_tui(orch)
        return 0


if __name__ == "__main__":
    sys.exit(main())
