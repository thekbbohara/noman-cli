"""NoMan CLI entrypoint."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

from cli.parser import parse_args
from core.adapters import create_adapter
from core.context import ContextManager
from core.memory import MemorySystem
from core.orchestrator import Orchestrator, OrchestratorConfig
from core.wiki import Wiki

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def _setup_debug_logging() -> None:
    """Enable DEBUG logging if --debug flag is set."""
    if os.environ.get("NOMAN_DEBUG"):
        logging.getLogger().setLevel(logging.DEBUG)
        logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s")


def _load_config() -> dict:
    """Load user config from file."""
    config_path = Path.home() / ".noman" / "config.toml"
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
        "model": {
            "max_tool_calls_per_turn": 10,
        },
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

    # Create wiki (global + per-project)
    noman_dir = _get_noman_dir()
    global_wiki = Wiki(noman_dir / "wiki" / "global")
    project_wiki_path = Path.cwd() / ".noman" / "wiki"
    project_wiki = Wiki(project_wiki_path)
    # Dual-write: ingest to global, query both
    from core.wiki import Wiki as DualWiki
    class DualWikiBridge:
        def __init__(self, global_wiki, project_wiki):
            self._global = global_wiki
            self._project = project_wiki
        @property
        def graph(self):
            return self._global.graph
        def get_entity(self, eid):
            e = self._global.graph.get_entity(eid)
            if e: return e
            return self._project.graph.get_entity(eid)
        def get_page(self, pid):
            p = self._global.get_page(pid)
            if p: return p
            return self._project.get_page(pid)
        def upsert_page(self, page):
            self._global.upsert_page(page)
            self._project.upsert_page(page)
        def remove_page(self, pid):
            self._global.remove_page(pid)
            self._project.remove_page(pid)
        def list_entities(self, entity_type=None, scope=None, limit=100):
            return self._global.graph.list_entities(entity_type, scope, limit)
        def search_pages(self, query, limit=20):
            g = self._global.search_pages(query, limit)
            p = self._project.search_pages(query, limit)
            seen = set()
            results = []
            for pg in g + p:
                if pg.id not in seen:
                    seen.add(pg.id)
                    results.append(pg)
            return results
        def list_pages(self, page_type=None, tag=None, limit=50):
            return self._global.list_pages(page_type, tag, limit)
        def search_pages(self, query, limit=20):
            g = self._global.search_pages(query, limit)
            p = self._project.search_pages(query, limit)
            seen = set()
            results = []
            for pg in g + p:
                if pg.id not in seen:
                    seen.add(pg.id)
                    results.append(pg)
            return results
        def get_index(self):
            return self._global.get_index()
        def get_log(self, last_n=20):
            return self._global.get_log(last_n)
        def log_event(self, event_type, detail, page_id=""):
            self._global.log_event(event_type, detail, page_id)
        def lint(self):
            return self._global.lint()
        def summary(self):
            return self._global.graph.summarize()
        def ingest_source(self, source_id, source_type, content, entities, relations):
            return self._global.ingest_source(source_id, source_type, content, entities, relations)
    wiki = DualWikiBridge(global_wiki, project_wiki)

    # Create orchestrator
    max_calls = getattr(args, 'max_calls', None)
    config_max_calls = config.get("model", {}).get("max_tool_calls_per_turn", 10)
    orch_config = OrchestratorConfig(
        max_turns=20,
        max_tokens_per_turn=8000,
        max_tool_calls_per_turn=max_calls if max_calls else config_max_calls,
    )

    orch = Orchestrator(
        adapter=adapter,
        tools=tool_bus,
        config=orch_config,
        context=context,
        memory=memory,
        wiki=wiki,
    )

    # Register wiki tools
    from core.wiki.tools import register_wiki_tools
    register_wiki_tools(tool_bus)
    tool_bus.wiki = wiki

    return orch


def _get_noman_dir() -> Path:
    """Get or create .noman directory in user home."""
    noman_dir = Path.home() / ".noman"
    noman_dir.mkdir(parents=True, exist_ok=True)
    return noman_dir


def _cmd_doctor() -> int:
    """Enhanced doctor: check providers, adapter connectivity, config, memory, disk."""
    checks_passed = 0
    checks_failed = 0
    checks_skipped = 0

    def ok(msg: str) -> None:
        nonlocal checks_passed
        print(f"  [OK] {msg}")
        checks_passed += 1

    def warn(msg: str) -> None:
        nonlocal checks_skipped
        print(f"  [WARN] {msg}")
        checks_skipped += 1

    def fail(msg: str) -> None:
        nonlocal checks_failed
        print(f"  [FAIL] {msg}")
        checks_failed += 1

    print("noman doctor: health check")

    # 1. Check config
    config_path = Path.home() / ".noman" / "config.toml"
    if config_path.exists():
        ok("Config file exists")
        try:
            import tomllib
            config = tomllib.loads(config_path.read_text())
            providers = config.get("providers", {})
            if isinstance(providers, list):
                ok(f"Config loaded: {len(providers)} provider(s)")
            else:
                ok(f"Config loaded: {len(providers)} provider(s)")
        except Exception as e:
            fail(f"Config parse error: {e}")
    else:
        warn("No config file found — using defaults")

    # 2. Check providers
    config = _load_config()
    providers = config.get("providers", {})
    if isinstance(providers, list):
        provider_list = providers
    else:
        provider_list = list(providers.values())

    for p in provider_list:
        ptype = p.get("type", "unknown")
        api_key = p.get("api_key", "")
        if api_key and len(api_key) > 10:
            ok(f"Provider '{p.get('id', ptype)}' ({ptype}) — API key configured")
        else:
            warn(f"Provider '{p.get('id', ptype)}' ({ptype}) — no API key")

    # 3. Test adapter connectivity (non-blocking probe)
    default_provider = config.get("default_provider", "default")
    if isinstance(providers, list):
        provider_config = next((p for p in providers if p.get("id") == default_provider), None)
    else:
        provider_config = providers.get(default_provider, {})

    if provider_config and provider_config.get("api_key"):
        try:
            adapter = create_adapter(provider_config)
            # Probe context window
            if hasattr(adapter, 'capabilities'):
                import asyncio
                caps = asyncio.run(adapter.capabilities())
                ok(f"Adapter connected — context window: {caps.max_context_tokens} tokens")
            else:
                ok("Adapter created (no capabilities probe available)")
        except Exception as e:
            fail(f"Adapter connectivity: {e}")
    else:
        warn("No active provider to test connectivity")

    # 4. Check memory system
    noman_dir = _get_noman_dir()
    try:
        from core.memory.store import MemoryConfig, MemoryStore
        mem_config = MemoryConfig(db_path=str(noman_dir / "memory.db"))
        mem_store = MemoryStore(mem_config)
        count = mem_store.count()
        ok(f"Memory system initialized ({count} memories)")
        mem_store.close()
    except Exception as e:
        fail(f"Memory system: {e}")

    # 5. Check disk space
    try:
        stat = os.statvfs(str(noman_dir))
        free_gb = (stat.f_bavail * stat.f_frsize) / (1024 ** 3)
        if free_gb > 1.0:
            ok(f"Disk space: {free_gb:.1f} GB available")
        else:
            warn(f"Disk space low: {free_gb:.1f} GB available")
    except Exception as e:
        warn(f"Could not check disk space: {e}")

    # Summary
    print(f"\nResults: {checks_passed} OK, {checks_failed} failed, {checks_skipped} skipped")
    return 0 if checks_failed == 0 else 1


def _cmd_review(file: str | None = None, n: int = 5) -> int:
    """Show a diff of recent changes."""
    try:
        if file:
            # Show git diff for specific file
            result = subprocess.run(
                ["git", "diff", "HEAD", "--", file],
                capture_output=True, text=True, cwd=Path.cwd(),
            )
            if result.returncode == 0 and result.stdout:
                print(result.stdout)
            else:
                print("No changes for the specified file.")
        else:
            # Show last N commits' diffs
            for i in range(n):
                try:
                    # Get commit hash
                    hash_result = subprocess.run(
                        ["git", "rev-parse", f"HEAD~{i}^"],
                        capture_output=True, text=True, cwd=Path.cwd(),
                    )
                    if hash_result.returncode != 0:
                        break

                    parent = hash_result.stdout.strip()

                    # Get the commit info
                    msg_result = subprocess.run(
                        ["git", "log", "-1", "--format=%H %s", f"HEAD~{i}"],
                        capture_output=True, text=True, cwd=Path.cwd(),
                    )
                    if msg_result.returncode != 0:
                        break

                    header = msg_result.stdout.strip()
                    print(f"\n{'=' * 60}")
                    print(f"Commit {i + 1}: {header}")
                    print(f"{'=' * 60}")

                    # Get diff
                    diff_result = subprocess.run(
                        ["git", "diff", f"{parent}", f"HEAD~{i}"],
                        capture_output=True, text=True, cwd=Path.cwd(),
                    )
                    if diff_result.returncode == 0 and diff_result.stdout:
                        print(diff_result.stdout)
                    else:
                        print("(empty commit)")
                except Exception:
                    break

    except Exception as e:
        print(f"Error: {e}")
        return 1
    return 0


def _cmd_rollback(n: int = 1, trace_id: str | None = None, list_rollbacks: bool = False) -> int:
    """Restore previous self-modification or list rollbacks."""
    noman_dir = _get_noman_dir()
    rollback_dir = noman_dir / "rollbacks"

    if list_rollbacks:
        if not rollback_dir.exists():
            print("No rollbacks found.")
            return 0
        rollbacks = sorted(rollback_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not rollbacks:
            print("No rollbacks found.")
            return 0
        print(f"{'ID':<20} {'Timestamp':<22} {'Description':<40} {'Files':>6}")
        print("-" * 90)
        for rb_path in rollbacks:
            try:
                data = json.loads(rb_path.read_text())
                ts = data.get("timestamp", "unknown")
                desc = data.get("description", "no description")
                files = data.get("files", [])
                print(f"{rb_path.stem:<20} {ts:<22} {desc:<40} {len(files):>6}")
            except (json.JSONDecodeError, KeyError):
                print(f"{rb_path.stem:<20} (invalid entry)")
        return 0

    if not rollback_dir.exists():
        print("No rollback metadata found. Run self-modification first to create rollbacks.")
        return 1

    rollbacks = sorted(rollback_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not rollbacks:
        print("No rollbacks found.")
        return 1

    # Get the N most recent rollbacks
    to_apply = rollbacks[:n]
    if trace_id:
        matching = [r for r in rollbacks if r.stem == trace_id]
        if not matching:
            print(f"No rollback found with ID '{trace_id}'.")
            return 1
        to_apply = [matching[0]]

    for rb_path in to_apply:
        try:
            data = json.loads(rb_path.read_text())
            files = data.get("files", [])
            desc = data.get("description", "no description")
            print(f"Applying rollback: {desc}")
            for finfo in files:
                fpath = finfo.get("path", "")
                content = finfo.get("content", "")
                if content is not None:
                    target = Path(fpath)
                    if target.exists():
                        target.write_text(content)
                        print(f"  Restored: {fpath}")
                    else:
                        print(f"  Skipped (not found): {fpath}")
                else:
                    # Deleted file marker
                    target = Path(fpath)
                    if target.exists():
                        target.unlink()
                        print(f"  Deleted: {fpath}")
        except (json.JSONDecodeError, KeyError) as e:
            print(f"  Error parsing rollback entry: {e}")
        except Exception as e:
            print(f"  Error applying rollback: {e}")

    return 0


def _cmd_memory_list(tier: str | None = None, scope: str | None = None) -> int:
    """List memory entries."""
    from core.memory.store import MemoryConfig, MemoryStore
    noman_dir = _get_noman_dir()
    store = MemoryStore(MemoryConfig(db_path=str(noman_dir / "memory.db")))

    entries = store.recall(tier=tier, scope=scope, limit=100)
    if not entries:
        print("No memories found.")
        store.close()
        return 0

    print(f"{'Tier':<14} {'Scope':<10} {'Key':<30} {'Value':<40}")
    print("-" * 94)
    for e in entries:
        value_preview = (e.value[:37] + "...") if len(e.value) > 40 else e.value
        print(f"{e.tier:<14} {e.scope:<10} {e.key:<30} {value_preview:<40}")

    print(f"\nTotal: {len(entries)} entries")
    store.close()
    return 0


def _cmd_memory_get(tier: str, scope: str, key: str) -> int:
    """Get a memory entry."""
    from core.memory.store import MemoryConfig, MemoryStore
    noman_dir = _get_noman_dir()
    store = MemoryStore(MemoryConfig(db_path=str(noman_dir / "memory.db")))

    entries = store.recall(tier=tier, scope=scope, limit=10)
    for e in entries:
        if e.key == key:
            print(f"tier: {e.tier}")
            print(f"scope: {e.scope}")
            print(f"key: {e.key}")
            print(f"value:\n{e.value}")
            if e.created_at:
                print(f"created: {e.created_at}")
            if e.updated_at:
                print(f"updated: {e.updated_at}")
            if e.expires_at:
                print(f"expires: {e.expires_at}")
            store.close()
            return 0

    print(f"Memory not found: {tier}/{scope}/{key}")
    store.close()
    return 1


def _cmd_memory_set(tier: str, scope: str, key: str, value: str) -> int:
    """Set a memory entry."""
    from core.memory.store import MemoryConfig, MemoryStore
    noman_dir = _get_noman_dir()
    store = MemoryStore(MemoryConfig(db_path=str(noman_dir / "memory.db")))

    eid = store.remember(tier, scope, key, value)
    print(f"Memory set: {tier}/{scope}/{key} -> {eid}")
    store.close()
    return 0


def _cmd_memory_delete(tier: str, scope: str, key: str) -> int:
    """Delete a memory entry."""
    from core.memory.store import MemoryConfig, MemoryStore
    noman_dir = _get_noman_dir()
    store = MemoryStore(MemoryConfig(db_path=str(noman_dir / "memory.db")))

    deleted = store.forget(tier, scope, key)
    if deleted:
        print(f"Memory deleted: {tier}/{scope}/{key}")
    else:
        print(f"Memory not found: {tier}/{scope}/{key}")
    store.close()
    return 0


def _cmd_skill_list() -> int:
    """List all skills."""
    from core.memory.store import MemoryConfig, MemoryStore
    noman_dir = _get_noman_dir()
    store = MemoryStore(MemoryConfig(db_path=str(noman_dir / "memory.db")))

    entries = store.recall(tier="procedural", scope="global", limit=100)
    if not entries:
        print("No skills found.")
        store.close()
        return 0

    print(f"{'Name':<30} {'Created':<22} {'Valid':>5}")
    print("-" * 60)
    for e in entries:
        created = e.created_at.strftime("%Y-%m-%d %H:%M") if e.created_at else "unknown"
        valid = "yes" if e.is_valid else "no"
        print(f"{e.key:<30} {created:<22} {valid:>5}")

    print(f"\nTotal: {len(entries)} skills")
    store.close()
    return 0


def _cmd_skill_get(name: str) -> int:
    """Get skill content."""
    from core.memory.store import MemoryConfig, MemoryStore
    noman_dir = _get_noman_dir()
    store = MemoryStore(MemoryConfig(db_path=str(noman_dir / "memory.db")))

    entries = store.recall(tier="procedural", scope="global", limit=10)
    for e in entries:
        if e.key == name:
            print(f"Skill: {name}")
            print(f"{'=' * len(name)}")
            print(e.value)
            store.close()
            return 0

    print(f"Skill not found: {name}")
    store.close()
    return 1


def _cmd_skill_set(name: str, content: str) -> int:
    """Set skill content."""
    from core.memory.store import MemoryConfig, MemoryStore
    noman_dir = _get_noman_dir()
    store = MemoryStore(MemoryConfig(db_path=str(noman_dir / "memory.db")))

    eid = store.remember("procedural", "global", name, content)
    print(f"Skill set: {name} -> {eid}")
    store.close()
    return 0


def _cmd_skill_add(name: str, file_path: str) -> int:
    """Add skill from file."""
    src = Path(file_path)
    if not src.exists():
        print(f"File not found: {file_path}")
        return 1

    skill_content = src.read_text()
    from core.memory.store import MemoryConfig, MemoryStore
    noman_dir = _get_noman_dir()
    store = MemoryStore(MemoryConfig(db_path=str(noman_dir / "memory.db")))

    eid = store.remember("procedural", "global", name, skill_content)
    print(f"Skill added: {name} from {file_path} -> {eid}")
    store.close()
    return 0


def _cmd_skill_review() -> int:
    """Review pending skill drafts."""
    from core.selfimprove.skill_queue import SkillQueue
    queue = SkillQueue()
    drafts = queue.list_pending()

    if not drafts:
        print("No pending skill drafts.")
        return 0

    print(f"=== Pending Skill Drafts ({len(drafts)}) ===\n")
    for i, draft in enumerate(drafts, 1):
        print(f"[{i}] {draft.name}")
        print(f"    Score: {draft.score:.2f}")
        print(f"    Reason: {draft.trigger_reason}")
        print(f"    Content:\n{draft.content}")
        print(f"    Draft ID: {draft.draft_id}")
        print()

    print("Commands: noman skill approve <draft_id> | noman skill discard <draft_id>")
    return 0


def _cmd_skill_approve(draft_id: str) -> int:
    """Approve a skill draft."""
    from core.selfimprove.skill_queue import SkillQueue
    queue = SkillQueue()
    success, msg = queue.approve(draft_id)
    print(msg)
    return 0 if success else 1


def _cmd_skill_discard(draft_id: str) -> int:
    """Discard a skill draft."""
    from core.selfimprove.skill_queue import SkillQueue
    queue = SkillQueue()
    success, msg = queue.discard(draft_id)
    print(msg)
    return 0 if success else 1


def _cmd_stats(noman_dir: Path | None = None) -> int:
    """Show execution stats."""
    if noman_dir is None:
        noman_dir = _get_noman_dir()

    # Session stats
    session_path = noman_dir / "sessions" / "active_session.json"
    turns = 0
    total_tokens = 0
    if session_path.exists():
        try:
            data = json.loads(session_path.read_text())
            turns = len(data.get("turns", []))
            total_tokens = data.get("total_tokens", 0)
        except Exception:
            pass

    # Memory count
    from core.memory.store import MemoryConfig, MemoryStore
    store = MemoryStore(MemoryConfig(db_path=str(noman_dir / "memory.db")))
    mem_count = store.count()

    # Semantic memories
    semantic_count = store.count(tier="semantic")
    procedural_count = store.count(tier="procedural")
    episodic_count = store.count(tier="episodic")

    store.close()

    # Cost estimate (rough: ~$0.002 per 1K tokens for gpt-4o-mini)
    cost_estimate = total_tokens * 0.002 / 1000

    # Rollback count
    rollback_dir = noman_dir / "rollbacks"
    rollback_count = sum(1 for _ in rollback_dir.glob("*.json")) if rollback_dir.exists() else 0

    # Wiki stats
    wiki_path = noman_dir / "wiki" / "global"
    if wiki_path.exists():
        try:
            import json
            edges_file = wiki_path / "edges.json"
            if edges_file.exists():
                edges_data = json.loads(edges_file.read_text())
                edge_count = len(edges_data)
            else:
                edge_count = 0
            pages_dir = wiki_path / "pages"
            page_count = sum(1 for _ in pages_dir.glob("*.md")) if pages_dir.exists() else 0
            wiki_exists = True
        except Exception:
            wiki_exists = False
            edge_count = 0
            page_count = 0
    else:
        wiki_exists = False

    print("noman stats")
    print(f"{'=' * 50}")
    print(f"  Turns:                    {turns}")
    print(f"  Total tokens used:        {total_tokens:,}")
    print(f"  Cost estimate (USD):      ${cost_estimate:.4f}")
    print(f"  Memory entries:           {mem_count}")
    print(f"    - semantic:             {semantic_count}")
    print(f"    - procedural:           {procedural_count}")
    print(f"    - episodic:             {episodic_count}")
    print(f"  Wiki:                     {'initialized' if wiki_exists else 'not initialized'}")
    if wiki_exists:
        print(f"    - entities:             {edge_count} edges")
        print(f"    - pages:                {page_count}")
    print(f"  Rollbacks:                {rollback_count}")
    print(f"  Config:                   {'exists' if (noman_dir / 'config.toml').exists() else 'not found'}")
    print(f"  Sessions dir:             {'exists' if (noman_dir / 'sessions').exists() else 'not found'}")
    print(f"  Debug dir:                {'exists' if (noman_dir / 'debug').exists() else 'not found'}")
    return 0


def _cmd_emergency(action: str) -> int:
    """Trigger emergency controls."""
    noman_dir = _get_noman_dir()
    noman_dir.mkdir(parents=True, exist_ok=True)

    if action == "stop":
        # Set environment variable + file flag
        flag_file = noman_dir / "emergency_stop.flag"
        flag_file.write_text(str(time.time()))
        os.environ["NOMAN_EMERGENCY_STOP"] = "1"
        print("Emergency stop triggered.")
        print("  - Flag written: .noman/emergency_stop.flag")
        print("  - NOMAN_EMERGENCY_STOP=1 set in environment")
        print("  - Circuit breakers on all adapters activated.")

    elif action == "disable-self-improve":
        flag_file = noman_dir / "disable_self_improve.flag"
        flag_file.write_text(str(time.time()))
        os.environ["NOMAN_DISABLE_SELF_IMPROVE"] = "1"
        print("Self-improvement disabled.")
        print("  - Flag written: .noman/disable_self_improve.flag")

    elif action == "read-only":
        flag_file = noman_dir / "read_only.flag"
        flag_file.write_text(str(time.time()))
        os.environ["NOMAN_READ_ONLY"] = "1"
        print("Read-only mode activated.")
        print("  - Flag written: .noman/read_only.flag")

    elif action == "lockdown":
        # All flags
        noman_dir.mkdir(parents=True, exist_ok=True)
        (noman_dir / "emergency_stop.flag").write_text(str(time.time()))
        (noman_dir / "disable_self_improve.flag").write_text(str(time.time()))
        (noman_dir / "read_only.flag").write_text(str(time.time()))
        os.environ["NOMAN_EMERGENCY_STOP"] = "1"
        os.environ["NOMAN_DISABLE_SELF_IMPROVE"] = "1"
        os.environ["NOMAN_READ_ONLY"] = "1"
        print("Lockdown mode activated.")
        print("  - All emergency flags set")
        print("  - All adapters circuit-broken")

    return 0


def _cmd_init() -> int:
    """Scaffold a new .noman/ directory."""
    noman_dir = Path.home() / ".noman"
    noman_dir.mkdir(parents=True, exist_ok=True)

    created = []

    # config.toml template
    config_path = noman_dir / "config.toml"
    if not config_path.exists():
        config_template = """# NoMan Configuration
# Copy this file to ~/.noman/config.toml

[providers.default]
type = "openai"
api_key = ""  # Set your API key here
model = "gpt-4o-mini"

[providers.anthropic]
type = "anthropic"
api_key = ""  # Set your API key here
model = "claude-3-5-sonnet-20241022"

[model]
default = "default"
max_tool_calls_per_turn = 10
token_budget = {max_tokens = 128000}

[logging]
level = "INFO"
"""
        config_path.write_text(config_template)
        created.append("config.toml")

    # Session directory
    sessions_dir = noman_dir / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    if not (noman_dir / "sessions" / ".gitkeep").exists():
        (noman_dir / "sessions" / ".gitkeep").touch()
    created.append("sessions/")

    # Rollback directory
    rollback_dir = noman_dir / "rollbacks"
    rollback_dir.mkdir(parents=True, exist_ok=True)
    if not (noman_dir / "rollbacks" / ".gitkeep").exists():
        (noman_dir / "rollbacks" / ".gitkeep").touch()
    created.append("rollbacks/")

    # Debug directory
    debug_dir = noman_dir / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    if not (noman_dir / "debug" / ".gitkeep").exists():
        (noman_dir / "debug" / ".gitkeep").touch()
    created.append("debug/")

    print("noman init: scaffolded .noman/ directory")
    for f in created:
        print(f"  Created: {noman_dir / f}")
    return 0


def _cmd_catalog(args) -> int:
    """List all Hermes agent tools and features."""
    from core.tools.tools_catalog import (
        SKILLS,
        TOOLS,
        TOTAL_SKILLS,
        TOTAL_TOOLS,
        format_skills_table,
        format_tools_table,
        get_skills_by_category,
        get_tool_count,
        get_tools_by_category,
    )

    show_tools = getattr(args, "tools", False)
    show_skills = getattr(args, "skills", False)
    summary_only = getattr(args, "summary", False)
    by_category = getattr(args, "by_category", False)

    if summary_only:
        counts = get_tool_count()
        print("=== Hermes Agent — Feature Catalog Summary ===\n")
        print(f"Total tools: {TOTAL_TOOLS}")
        print(f"Total skills: {TOTAL_SKILLS}")
        print("\nTools by category:")
        for cat, count in sorted(counts["tools_by_category"].items()):
            print(f"  {cat:<22} {count:>3} tools")
        print("\nSkills by category:")
        for cat, count in sorted(counts["skills_by_category"].items()):
            print(f"  {cat:<22} {count:>3} skills")
        return 0

    if not show_tools and not show_skills:
        show_tools = True
        show_skills = True

    if show_tools:
        print(f"=== Hermes Agent — Tools Catalog ({TOTAL_TOOLS} tools) ===\n")
        if by_category:
            groups = get_tools_by_category()
            for cat, tools in sorted(groups.items()):
                print(f"\n--- {cat} ({len(tools)} tools) ---")
                for t in tools:
                    params = ", ".join(t.params) if t.params else "—"
                    print(f"  {t.name:<42} [{params}]")
                    if t.notes:
                        print(f"    {t.notes}")
        else:
            print(format_tools_table(TOOLS))

    if show_skills:
        print(f"\n=== Hermes Agent — Skills Library ({TOTAL_SKILLS} skills) ===\n")
        if by_category:
            skill_groups = get_skills_by_category()
            for cat, skills in sorted(skill_groups.items()):
                print(f"\n--- {cat} ({len(skills)} skills) ---")
                for s in skills:
                    desc = s.description[:55] + "..." if len(s.description) > 55 else s.description
                    print(f"  {s.name:<40} {desc}")
        else:
            print(format_skills_table(SKILLS))

    print(f"\n=== Total: {TOTAL_TOOLS} tools + {TOTAL_SKILLS} skills ===")
    return 0


def main(argv=None):
    args = parse_args(argv)

    if args.debug:
        os.environ["NOMAN_DEBUG"] = "1"
        _setup_debug_logging()

    # --- CLI commands ---

    if args.command == "doctor":
        return _cmd_doctor()

    if args.command == "review":
        return _cmd_review(file=getattr(args, 'file', None), n=getattr(args, 'n', 5))

    if args.command == "rollback":
        list_flag = getattr(args, 'list_rollbacks', False)
        return _cmd_rollback(
            n=getattr(args, 'n', 1),
            trace_id=getattr(args, 'trace_id', None),
            list_rollbacks=list_flag,
        )

    if args.command == "memory":
        subcmd = getattr(args, 'subcmd', None)
        if subcmd == "list":
            tier_filter = getattr(args, 'tier_filter', None)
            scope_filter = getattr(args, 'scope_filter', None)
            return _cmd_memory_list(tier=tier_filter, scope=scope_filter)
        elif subcmd == "get":
            tier = getattr(args, 'tier', None)
            scope = getattr(args, 'scope', None)
            key = getattr(args, 'key', None)
            if not tier or not scope or not key:
                print("Usage: noman memory get <tier> <scope> <key>")
                return 1
            return _cmd_memory_get(tier, scope, key)
        elif subcmd == "set":
            tier = getattr(args, 'tier', None)
            scope = getattr(args, 'scope', None)
            key = getattr(args, 'key', None)
            value = getattr(args, 'value', None)
            if not tier or not scope or not key or not value:
                print("Usage: noman memory set <tier> <scope> <key> <value>")
                return 1
            return _cmd_memory_set(tier, scope, key, value)
        elif subcmd == "delete":
            tier = getattr(args, 'tier', None)
            scope = getattr(args, 'scope', None)
            key = getattr(args, 'key', None)
            if not tier or not scope or not key:
                print("Usage: noman memory delete <tier> <scope> <key>")
                return 1
            return _cmd_memory_delete(tier, scope, key)
        return 1

    if args.command == "skill":
        subcmd = getattr(args, 'subcmd', None)
        if subcmd == "list":
            return _cmd_skill_list()
        elif subcmd == "get":
            name = getattr(args, 'name', None)
            if not name:
                print("Usage: noman skill get <name>")
                return 1
            return _cmd_skill_get(name)
        elif subcmd == "set":
            name = getattr(args, 'name', None)
            content = getattr(args, 'content', None)
            if not name or content is None:
                print("Usage: noman skill set <name> <content>")
                return 1
            return _cmd_skill_set(name, content)
        elif subcmd == "add":
            name = getattr(args, 'name', None)
            file_path = getattr(args, 'content', None)  # parser puts 2nd positional into 'content'
            if not name or not file_path:
                print("Usage: noman skill add <name> <file>")
                return 1
            return _cmd_skill_add(name, file_path)
        elif subcmd == "review":
            return _cmd_skill_review()
        elif subcmd == "approve":
            draft_id = getattr(args, 'draft_id', None)
            if not draft_id:
                print("Usage: noman skill approve <draft_id>")
                return 1
            return _cmd_skill_approve(draft_id)
        elif subcmd == "discard":
            draft_id = getattr(args, 'draft_id', None)
            if not draft_id:
                print("Usage: noman skill discard <draft_id>")
                return 1
            return _cmd_skill_discard(draft_id)
        return 1

    if args.command == "stats":
        return _cmd_stats()

    if args.command == "emergency":
        action = getattr(args, 'action', None)
        if not action:
            print("Usage: noman emergency <stop|disable-self-improve|read-only|lockdown>")
            return 1
        return _cmd_emergency(action)

    if args.command == "init":
        return _cmd_init()

    if args.command == "catalog":
        return _cmd_catalog(args)

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
