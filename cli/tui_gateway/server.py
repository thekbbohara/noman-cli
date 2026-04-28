"""NoMan TUI Gateway - Minimal JSON-RPC server for TUI integration."""

import atexit
import json
import logging
import os
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .transport import (
    StdioTransport,
    Transport,
    bind_transport,
    current_transport,
    reset_transport,
)

logger = logging.getLogger(__name__)

_noman_home = os.path.expanduser("~/.noman")

_CRASH_LOG = os.path.join(_noman_home, "logs", "tui_gateway_crash.log")


def _panic_hook(exc_type, exc_value, exc_tb):
    import traceback

    trace = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    try:
        os.makedirs(os.path.dirname(_CRASH_LOG), exist_ok=True)
        with open(_CRASH_LOG, "a", encoding="utf-8") as f:
            f.write(
                f"\n=== unhandled exception · {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n"
            )
            f.write(trace)
    except Exception:
        pass
    first = (
        str(exc_value).strip().splitlines()[0]
        if str(exc_value).strip()
        else exc_type.__name__
    )
    print(f"[gateway-crash] {exc_type.__name__}: {first}", file=sys.stderr, flush=True)
    sys.__excepthook__(exc_type, exc_value, exc_tb)


sys.excepthook = _panic_hook


def _thread_panic_hook(args):
    import traceback

    trace = "".join(
        traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)
    )
    try:
        os.makedirs(os.path.dirname(_CRASH_LOG), exist_ok=True)
        with open(_CRASH_LOG, "a", encoding="utf-8") as f:
            f.write(
                f"\n=== thread exception · {time.strftime('%Y-%m-%d %H:%M:%S')} "
                f"· thread={args.thread.name} ===\n"
            )
            f.write(trace)
    except Exception:
        pass
    first_line = (
        str(args.exc_value).strip().splitlines()[0]
        if str(args.exc_value).strip()
        else args.exc_type.__name__
    )
    print(
        f"[gateway-crash] thread {args.thread.name} raised {args.exc_type.__name__}: {first_line}",
        file=sys.stderr,
        flush=True,
    )


threading.excepthook = _thread_panic_hook

_methods: dict[str, callable] = {}

_real_stdout = sys.stdout
sys.stdout = sys.stderr

_stdout_lock = threading.Lock()
_stdio_transport = StdioTransport(lambda: _real_stdout, _stdout_lock)

_sessions: dict[str, dict] = {}


def _ok(rid: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _err(rid: Any, code: int, msg: str) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": msg}}


def method(name: str):
    def dec(fn):
        _methods[name] = fn
        return fn

    return dec


def write_json(obj: dict) -> bool:
    """Emit one JSON frame."""
    return _stdio_transport.write(obj)


def handle_request(req: dict) -> dict | None:
    fn = _methods.get(req.get("method", ""))
    if not fn:
        return _err(req.get("id"), -32601, f"unknown method: {req.get('method')}")
    return fn(req.get("id"), req.get("params", {}))


def dispatch(req: dict, transport: Optional[Transport] = None) -> dict | None:
    """Route inbound RPCs."""
    t = transport or _stdio_transport
    token = bind_transport(t)
    try:
        return handle_request(req)
    finally:
        reset_transport(token)


def resolve_skin() -> dict:
    return {"name": "noman", "colors": {}, "branding": {}, "banner_logo": "", "banner_hero": "", "tool_prefix": "", "help_header": ""}


_orchestrator_instance = None


def _get_orchestrator():
    global _orchestrator_instance
    if _orchestrator_instance is not None:
        return _orchestrator_instance

    from core.orchestrator import Orchestrator, OrchestratorConfig
    from core.adapters import create_adapter
    from core.tools import create_toolbus
    from core.context import ContextManager
    from core.memory import MemorySystem
    from core.wiki import Wiki
    from pathlib import Path

    config = _load_config()

    provider_name = config.get("default_provider", "default")
    providers = config.get("providers", [])

    if isinstance(providers, list):
        provider_config = next((p for p in providers if p.get("id") == provider_name), None)
    else:
        provider_config = providers.get(provider_name, {})

    if not provider_config:
        provider_config = {"type": "openai", "api_key": os.environ.get("OPENAI_API_KEY", ""), "model": "gpt-4o-mini"}

    if not provider_config:
        raise RuntimeError("No provider configured")

    adapter = create_adapter(provider_config)
    tool_bus = create_toolbus(Path.cwd())
    context = ContextManager(Path.cwd())
    memory = MemorySystem()

    noman_dir = Path.home() / ".noman"
    wiki = Wiki(noman_dir / "wiki" / "global")

    orch_config = OrchestratorConfig(
        max_turns=20,
        max_tokens_per_turn=8000,
        max_tool_calls_per_turn=10,
    )

    _orchestrator_instance = Orchestrator(
        adapter=adapter,
        tools=tool_bus,
        context=context,
        memory=memory,
        wiki=wiki,
        config=orch_config,
    )

    return _orchestrator_instance


def _load_config() -> dict:
    config_path = Path.home() / ".noman" / "config.toml"
    if not config_path.exists():
        return _default_config()

    try:
        from importlib.util import find_spec

        if find_spec("tomllib"):
            import tomllib

            return tomllib.loads(config_path.read_text())
    except Exception:
        pass

    return _default_config()


def _default_config() -> dict:
    return {
        "providers": [
            {
                "id": "default",
                "type": "openai",
                "api_key": os.environ.get("OPENAI_API_KEY", ""),
                "model": "gpt-4o-mini",
            }
        ],
        "default_provider": "default",
    }


@method("chat")
def _chat(rid: Any, params: dict) -> dict:
    """Handle chat messages via the orchestrator."""
    message = params.get("message", "")

    if not message:
        return _ok(rid, {"response": "No message provided"})

    try:
        orch = _get_orchestrator()
    except Exception as e:
        return _err(rid, 5001, f"Failed to create orchestrator: {e}")

    try:
        import asyncio

        result = asyncio.run(orch.run(message))
    except Exception as e:
        return _err(rid, 5002, f"Orchestrator error: {e}")

    return _ok(rid, {"response": result})


@method("session.create")
def _session_create(rid: Any, params: dict) -> dict:
    """Create a new session."""
    sid = uuid.uuid4().hex[:8]
    key = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]

    _sessions[sid] = {
        "session_key": key,
        "history": [],
        "history_lock": threading.Lock(),
    }

    return _ok(rid, {"session_id": sid, "session_key": key})


@method("session.close")
def _session_close(rid: Any, params: dict) -> dict:
    """Close a session."""
    sid = params.get("session_id")
    if sid and sid in _sessions:
        del _sessions[sid]
    return _ok(rid, {"status": "closed"})