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
    """Default configuration with all supported provider types."""
    return {
        "providers": {
            "default": {
                "type": "openai",
                "api_key": os.environ.get("OPENAI_API_KEY", ""),
                "model": "gpt-4o-mini",
            },
            # Anthropic
            "anthropic": {
                "type": "anthropic",
                "api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
                "model": "claude-sonnet-4-20250514",
            },
            # Google Gemini
            "gemini": {
                "type": "gemini",
                "api_key": os.environ.get("GEMINI_API_KEY", ""),
                "model": "gemini-2.5-flash",
            },
            # DeepSeek
            "deepseek": {
                "type": "deepseek",
                "api_key": os.environ.get("DEEPSEEK_API_KEY", ""),
                "model": "deepseek-chat",
            },
            # xAI / Grok
            "xai": {
                "type": "xai",
                "api_key": os.environ.get("XAI_API_KEY", ""),
                "model": "grok-4",
            },
            # Mistral
            "mistral": {
                "type": "mistral",
                "api_key": os.environ.get("MISTRAL_API_KEY", ""),
                "model": "mistral-large-latest",
            },
            # Together AI
            "together": {
                "type": "together",
                "api_key": os.environ.get("TOGETHER_API_KEY", ""),
                "model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
            },
            # SambaNova
            "sambanova": {
                "type": "sambanova",
                "api_key": os.environ.get("SAMBANOVA_API_KEY", ""),
                "model": "Meta-Llama-3.1-70B-Instruct",
            },
            # NVIDIA NIM
            "nvidia": {
                "type": "nvidia",
                "api_key": os.environ.get("NVIDIA_API_KEY", ""),
                "model": "nvidia/llama-3.1-nemotron-70b-instruct",
            },
            # Perplexity
            "perplexity": {
                "type": "perplexity",
                "api_key": os.environ.get("PERPLEXITY_API_KEY", ""),
                "model": "sonar-pro",
            },
            # DashScope (Alibaba)
            "dashscope": {
                "type": "dashscope",
                "api_key": os.environ.get("DASHSCOPE_API_KEY", ""),
                "model": "qwen-max",
            },
            # Kimi / Moonshot
            "kimi": {
                "type": "kimi",
                "api_key": os.environ.get("KIMI_API_KEY", ""),
                "model": "moonshot-v1-128k",
            },
            # GLM (Z.AI)
            "glm": {
                "type": "glm",
                "api_key": os.environ.get("GLM_API_KEY", ""),
                "model": "glm-4-plus",
            },
            # MiniMax
            "minimax": {
                "type": "minimax",
                "api_key": os.environ.get("MINIMAX_API_KEY", ""),
                "model": "abab6.5",
            },
            # MiniMax CN
            "minimax_cn": {
                "type": "minimax_cn",
                "api_key": os.environ.get("MINIMAX_CN_API_KEY", ""),
                "model": "abab6.5",
            },
            # Voyage AI
            "voyage": {
                "type": "voyage",
                "api_key": os.environ.get("VOYAGE_API_KEY", ""),
                "model": "voyage-3",
            },
            # HuggingFace
            "huggingface": {
                "type": "huggingface",
                "api_key": os.environ.get("HUGGINGFACE_API_KEY", ""),
                "model": "",
                "base_url": os.environ.get("HUGGINGFACE_BASE_URL", ""),
            },
            # Ollama (local)
            "ollama": {
                "type": "ollama",
                "api_key": "",
                "base_url": os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
                "model": os.environ.get("OLLAMA_MODEL", "llama3.2"),
            },
            # Groq
            "groq": {
                "type": "groq",
                "api_key": os.environ.get("GROQ_API_KEY", ""),
                "model": "llama-3.3-70b-versatile",
            },
            # LiteLLM
            "lite_llm": {
                "type": "lite llm",
                "api_key": os.environ.get("LITELLM_API_KEY", ""),
                "model": "openai/gpt-4o-mini",
            },
        },
        "default_provider": "default",
        "model": {
            "max_tool_calls_per_turn": 10,
        },
        # --- Phase 4: Voice (STT/TTS) ---
        "stt": {
            "enabled": False,
            "provider": "faster_whisper",  # faster_whisper, groq, openai, mistral
            "local_model": "base",  # tiny, base, small, medium, large-v3
            "groq": {
                "api_key": os.environ.get("GROQ_API_KEY", ""),
            },
            "openai": {
                "api_key": os.environ.get("OPENAI_STT_API_KEY", ""),
            },
            "mistral": {
                "api_key": os.environ.get("MISTRAL_STT_API_KEY", ""),
            },
        },
        "tts": {
            "enabled": False,
            "provider": "edge",  # edge, elevenlabs, openai, minimax, mistral, neutts
            "edge": {
                "voice": "en-US-AvaMultilingualNeural",
                "speed": 1.0,
                "pitch": 0,
            },
            "elevenlabs": {
                "api_key": os.environ.get("ELEVENLABS_API_KEY", ""),
                "voice_id": "pNInz6obpgDQGcFmaJgB",
            },
            "openai": {
                "api_key": os.environ.get("OPENAI_TTS_API_KEY", ""),
                "model": "tts-1",
                "voice": "nova",
            },
            "minimax": {
                "api_key": os.environ.get("MINIMAX_TTS_API_KEY", ""),
                "voice_id": "female-1",
            },
            "mistral": {
                "api_key": os.environ.get("MISTRAL_TTS_API_KEY", ""),
            },
            "neutts": {
                "base_url": "http://localhost:8080",
            },
        },
        # --- Phase 4: Vision ---
        "vision": {
            "default_provider": "openai",  # openai, gemini, anthropic, ollama
            "providers": {
                "openai": {
                    "api_key": os.environ.get("OPENAI_API_KEY", ""),
                    "model": "gpt-4o",
                },
                "gemini": {
                    "api_key": os.environ.get("GEMINI_API_KEY", ""),
                    "model": "gemini-2.0-flash",
                },
                "anthropic": {
                    "api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
                    "model": "claude-3-5-sonnet-20241022",
                },
                "ollama": {
                    "base_url": os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
                    "model": "llava",
                },
            },
        },
        # --- Phase 4: Image Generation ---
        "image_gen": {
            "default_provider": "fal",  # fal, openai, stability, replicate
            "default_aspect": "square",  # landscape, square, portrait
            "enhance_prompts": True,
            "providers": {
                "fal": {
                    "api_key": os.environ.get("FAL_KEY", ""),
                    "model": "fal-ai/fast-sdxl",
                },
                "openai": {
                    "api_key": os.environ.get("OPENAI_API_KEY", ""),
                    "model": "dall-e-3",
                },
                "stability": {
                    "api_key": os.environ.get("STABILITY_API_KEY", ""),
                    "model": "stable-diffusion-xl-1024-v1-0",
                },
                "replicate": {
                    "api_key": os.environ.get("REPLICATE_API_KEY", ""),
                    "model": "stability-ai/sdxl",
                },
            },
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


def _cmd_skill_patterns(min_occurrences: int = 3) -> int:
    """Detect recurring patterns across recent sessions."""
    from core.selfimprove.cross_session import detect_cross_session_patterns, format_patterns
    patterns = detect_cross_session_patterns(min_occurrences=min_occurrences)
    print(format_patterns(patterns))
    return 0


def _cmd_skill_stats() -> int:
    """Show skill creation statistics, including domain-level approval rates."""
    from core.selfimprove.skill_queue import SkillQueue
    queue = SkillQueue()
    stats = queue.get_usage_stats()
    domain_stats = stats.pop("domain_stats", {})

    print("=== Skill Creation Statistics ===\n")
    print(f"  Total drafts:     {stats['total']}")
    print(f"  Pending:          {stats['pending']}")
    print(f"  Approved:         {stats['approved']}")
    print(f"  Discarded:        {stats['discarded']}")
    print(f"  Expired:          {stats['expired']}")

    if domain_stats:
        print(f"\n  === Domain Approval Rates ===")
        for domain, data in sorted(domain_stats.items()):
            total = data["approved"] + data["discarded"]
            rate = data["approved"] / total if total > 0 else 0.0
            threshold = queue.get_recommended_threshold(domain)
            bar = "#" * int(rate * 20) + "." * (20 - int(rate * 20))
            print(f"    {domain:<25} {rate:.0%} [{bar}] (threshold: {threshold:.2f})")
            print(f"      approved: {data['approved']}, discarded: {data['discarded']}")
    else:
        print("\n  No domain statistics yet. Data will appear after skill reviews.")
    return 0


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

# --- Phase 4: Voice (STT/TTS) ---

[stt]
enabled = false
provider = "faster_whisper"  # faster_whisper, groq, openai, mistral
local_model = "base"  # tiny, base, small, medium, large-v3

[stt.groq]
api_key = ""

[stt.openai]
api_key = ""

[stt.mistral]
api_key = ""

[tts]
enabled = false
provider = "edge"  # edge, elevenlabs, openai, minimax, mistral, neutts

[tts.edge]
voice = "en-US-AvaMultilingualNeural"
speed = 1.0
pitch = 0

[tts.elevenlabs]
api_key = ""
voice_id = "pNInz6obpgDQGcFmaJgB"

[tts.openai]
api_key = ""
model = "tts-1"
voice = "nova"

[tts.minimax]
api_key = ""
voice_id = "female-1"

[tts.mistral]
api_key = ""

[tts.neutts]
base_url = "http://localhost:8080"

# --- Phase 4: Vision ---

[vision]
default_provider = "openai"  # openai, gemini, anthropic, ollama

[vision.providers.openai]
api_key = ""
model = "gpt-4o"

[vision.providers.gemini]
api_key = ""
model = "gemini-2.0-flash"

[vision.providers.anthropic]
api_key = ""
model = "claude-3-5-sonnet-20241022"

[vision.providers.ollama]
base_url = "http://localhost:11434/v1"
model = "llava"

# --- Phase 4: Image Generation ---

[image_gen]
default_provider = "fal"  # fal, openai, stability, replicate
default_aspect = "square"  # landscape, square, portrait
enhance_prompts = true

[image_gen.providers.fal]
api_key = ""
model = "fal-ai/fast-sdxl"

[image_gen.providers.openai]
api_key = ""
model = "dall-e-3"

[image_gen.providers.stability]
api_key = ""
model = "stable-diffusion-xl-1024-v1-0"

[image_gen.providers.replicate]
api_key = ""
model = "stability-ai/sdxl"
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


def _launch_tui() -> int:
    import subprocess
    import os
    import sys
    import shutil
    
    tui_dir = Path(__file__).parent / "tui"
    src_entry = tui_dir / "src" / "entry.tsx"
    dist_entry = tui_dir / "dist" / "entry.js"
    
    if dist_entry.exists():
        entry = dist_entry
    elif src_entry.exists():
        entry = src_entry
    else:
        logger.error("TUI not found. Run 'cd cli/tui && pnpm build' first.")
        return 1
    
    env = {**os.environ, "NOMAN_GATEWAY": "1"}
    
    if sys.platform == "win32":
        return subprocess.call(
            ["node", str(entry)],
            env=env
        )
    else:
        if not shutil.which("script"):
            logger.error("'script' command not found. Install it or run TUI manually.")
            return 1
        return subprocess.call(
            ["script", "-q", "-e", "-c", f"node {entry}", "/dev/null"],
            env=env
        )


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
        elif subcmd == "patterns":
            min_occ = getattr(args, 'min_occurrences', 3)
            return _cmd_skill_patterns(min_occurrences=min_occ)
        elif subcmd == "stats":
            return _cmd_skill_stats()
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

    # --- Gateway commands ---

    if args.command == "gateway":
        subcmd = getattr(args, "gateway_subcmd", None)
        if subcmd == "run":
            return _cmd_gateway_run(args)
        elif subcmd == "status":
            return _cmd_gateway_status(args)
        elif subcmd == "setup":
            return _cmd_gateway_setup(args)
        elif subcmd == "install":
            return _cmd_gateway_install(args)
        elif subcmd == "start":
            return _cmd_gateway_start(args)
        elif subcmd == "stop":
            return _cmd_gateway_stop(args)
        elif subcmd == "restart":
            return _cmd_gateway_restart(args)
        elif subcmd == "list":
            return _cmd_gateway_list()
        else:
            print("Usage: noman gateway <run|status|setup|install|start|stop|restart|list>")
            return 1

    # --- Cron commands ---

    if args.command == "cron":
        subcmd = getattr(args, "cron_subcmd", None)
        if subcmd == "list":
            return _cmd_cron_list(args)
        elif subcmd == "create":
            return _cmd_cron_create(args)
        elif subcmd == "edit":
            return _cmd_cron_edit(args)
        elif subcmd == "pause":
            return _cmd_cron_pause(args)
        elif subcmd == "resume":
            return _cmd_cron_resume(args)
        elif subcmd == "remove":
            return _cmd_cron_remove(args)
        elif subcmd == "run":
            return _cmd_cron_run(args)
        elif subcmd == "status":
            return _cmd_cron_status()
        else:
            print("Usage: noman cron <list|create|edit|pause|resume|remove|run|status>")
            return 1

    # --- Webhook commands ---

    if args.command == "webhook":
        subcmd = getattr(args, "webhook_subcmd", None)
        if subcmd == "list":
            return _cmd_webhook_list(args)
        elif subcmd == "subscribe":
            return _cmd_webhook_subscribe(args)
        elif subcmd == "remove":
            return _cmd_webhook_remove(args)
        elif subcmd == "test":
            return _cmd_webhook_test(args)
        else:
            print("Usage: noman webhook <list|subscribe|remove|test>")
            return 1

    # --- Voice commands ---

    if args.command == "voice":
        return _cmd_voice(args)

    # --- Vision command ---

    if args.command == "vision":
        return _cmd_vision(args)

    # --- Image generation commands ---

    if args.command == "image":
        return _cmd_image(args)

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
        # Run TypeScript TUI REPL
        return _launch_tui()


# --- Voice command handlers ---

def _cmd_voice(args) -> int:
    """Handle voice (STT/TTS) CLI commands."""
    subcmd = getattr(args, "voice_subcmd", None)
    if not subcmd:
        print("Usage: noman voice <stt|tts|list>")
        return 1

    if subcmd == "stt":
        return _cmd_voice_stt(args)
    elif subcmd == "tts":
        return _cmd_voice_tts(args)
    elif subcmd == "list":
        return _cmd_voice_list(args)
    else:
        print("Usage: noman voice <stt|tts|list>")
        return 1


def _cmd_voice_stt(args) -> int:
    """Handle STT transcription command."""
    import asyncio

    audio_file = getattr(args, "audio_file", None)
    if not audio_file:
        print("Usage: noman voice stt --file audio.mp3")
        return 1

    from core.voice.stt import STTEngine

    config = _load_config()
    stt_config = config.get("stt", {})
    provider = getattr(args, "provider", None)
    language = getattr(args, "language", None)

    engine = STTEngine(
        provider=provider,
        config=stt_config,
    )

    async def _transcribe():
        return await engine.transcribe_file(audio_file, provider=provider)

    try:
        result = asyncio.run(_transcribe())
        print(f"Provider:   {result.provider}")
        print(f"Confidence: {result.confidence:.2f}")
        print(f"Duration:   {result.duration_seconds:.1f}s")
        print(f"Language:   {result.language or 'auto-detected'}")
        print(f"\nTranscript:\n{result.text}")
        return 0
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return 1
    except RuntimeError as e:
        print(f"Error: {e}")
        return 1
    except Exception as e:
        logger.error(f"STT error: {e}")
        return 1


def _cmd_voice_tts(args) -> int:
    """Handle TTS synthesis command."""
    import asyncio

    text = getattr(args, "text_input", None) or getattr(args, "text", None)
    if not text:
        print("Usage: noman voice tts --text 'hello world'")
        return 1

    from core.voice.tts import TTSEngine

    config = _load_config()
    tts_config = config.get("tts", {})
    provider = getattr(args, "provider", None)
    speed = getattr(args, "speed", 1.0)
    pitch = getattr(args, "pitch", 0)
    output = getattr(args, "output", None)

    engine = TTSEngine(
        provider=provider,
        config=tts_config,
    )

    async def _synthesize():
        return await engine.synthesize(
            text, provider=provider, speed=speed, pitch=pitch,
            output_dir=output,
        )

    try:
        result = asyncio.run(_synthesize())
        print(f"Provider:   {result.provider}")
        print(f"Duration:   {result.duration_seconds:.1f}s")
        print(f"Format:     {result.format}")
        print(f"Output:     {result.audio_path}")
        return 0
    except RuntimeError as e:
        print(f"Error: {e}")
        return 1
    except Exception as e:
        logger.error(f"TTS error: {e}")
        return 1


def _cmd_voice_list(args) -> int:
    """List available voice providers."""
    from core.voice.stt import STTEngine
    from core.voice.tts import TTSEngine

    config = _load_config()
    stt_config = config.get("stt", {})
    tts_config = config.get("tts", {})

    stt = STTEngine(config=stt_config)
    tts = TTSEngine(config=tts_config)

    print("=== STT Providers ===")
    print(f"  Default: {stt.provider}")
    for p in stt_config.get("providers", []):
        print(f"  - {p}")
    print()
    print("=== TTS Providers ===")
    print(f"  Default: {tts.provider}")
    for p in tts_config.get("providers", []):
        print(f"  - {p}")
    return 0


# --- Vision command handlers ---

def _cmd_vision(args) -> int:
    """Handle vision CLI commands."""
    import asyncio

    image = getattr(args, "image", None)
    if not image:
        print("Usage: noman vision --image image.png [--prompt 'describe this']")
        return 1

    from core.vision import VisionTask, VisionAnalyzer

    task_str = getattr(args, "task", "describe")
    prompt = getattr(args, "prompt", None)
    provider = getattr(args, "provider", None)

    # Map string task to VisionTask enum
    task_map = {
        "describe": VisionTask.DESCRIBE,
        "ocr": VisionTask.OCR,
        "object_detection": VisionTask.OBJECT_DETECTION,
        "analysis": VisionTask.ANALYSIS,
        "question_answer": VisionTask.QUESTION_ANSWER,
    }
    task = task_map.get(task_str, VisionTask.DESCRIBE)

    config = _load_config()
    vision_config = config.get("vision", {})

    analyzer = VisionAnalyzer(
        default_provider=getattr(args, "provider", None),
        config=vision_config,
    )

    async def _analyze():
        if task == VisionTask.QUESTION_ANSWER:
            return await analyzer.ask(image, question=prompt or "What is in this image?", provider=provider)
        elif task == VisionTask.ANALYSIS and prompt:
            return await analyzer.analyze(image, task=task, prompt=prompt, provider=provider)
        else:
            return await analyzer.analyze(image, task=task, provider=provider)

    try:
        result = asyncio.run(_analyze())
        print(f"Provider:   {result.provider}")
        print(f"Task:       {result.task}")
        print(f"Confidence: {result.confidence:.2f}")
        print(f"\nResult:\n{result.text}")
        if result.objects:
            print(f"\nObjects detected: {len(result.objects)}")
            for obj in result.objects:
                print(f"  - {obj}")
        return 0
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return 1
    except Exception as e:
        logger.error(f"Vision error: {e}")
        return 1


# --- Image generation command handlers ---

def _cmd_image(args) -> int:
    """Handle image generation CLI commands."""
    import asyncio

    subcmd = getattr(args, "image_subcmd", None)
    if not subcmd:
        print("Usage: noman image <generate|list>")
        return 1

    if subcmd == "generate":
        return _cmd_image_generate(args)
    elif subcmd == "list":
        return _cmd_image_list(args)
    else:
        print("Usage: noman image <generate|list>")
        return 1


def _cmd_image_generate(args) -> int:
    """Handle image generation command."""
    import asyncio

    prompt = getattr(args, "prompt", None)
    if not prompt:
        print("Usage: noman image generate --prompt 'a cat'")
        return 1

    from core.image_gen import ImageGenerator

    config = _load_config()
    img_config = config.get("image_gen", {})
    aspect = getattr(args, "aspect", "square")
    provider = getattr(args, "provider", None)
    model = getattr(args, "model", None)
    neg_prompt = getattr(args, "negative_prompt", None)
    count = getattr(args, "count", 1)
    output_dir = getattr(args, "output", None)

    generator = ImageGenerator(
        default_provider=provider,
        default_aspect=aspect,
        config=img_config,
        output_dir=output_dir,
    )

    async def _generate():
        results = await generator.generate_multiple(
            prompt, count=count, aspect=aspect,
            provider=provider, model=model,
            negative_prompt=neg_prompt,
            output_dir=output_dir,
        )
        return results

    try:
        results = asyncio.run(_generate())
        for i, result in enumerate(results, 1):
            print(f"\n--- Image {i} ---")
            print(f"  Provider:   {result.provider}")
            print(f"  Model:      {result.model}")
            print(f"  Aspect:     {result.aspect_ratio}")
            print(f"  Prompt:     {result.prompt[:80]}...")
            if result.image_path:
                print(f"  Saved:      {result.image_path}")
            if result.image_url:
                print(f"  URL:        {result.image_url}")
        return 0
    except ValueError as e:
        print(f"Error: {e}")
        return 1
    except RuntimeError as e:
        print(f"Error: {e}")
        return 1
    except Exception as e:
        logger.error(f"Image generation error: {e}")
        return 1


def _cmd_image_list(args) -> int:
    """List available image generation providers."""
    from core.image_gen import ImageGenerator

    config = _load_config()
    img_config = config.get("image_gen", {})
    generator = ImageGenerator(config=img_config)

    print("=== Image Generation Providers ===")
    for p in generator.VALID_PROVIDERS:
        print(f"  - {p}")
    return 0


def _cmd_gateway_run(args) -> int:
    """Start configured gateways."""
    import asyncio
    from core.gateway.scheduler import GatewayManager
    from core.gateway.base import GatewayConfig, PlatformType

    manager = GatewayManager()

    # Load config
    config = _load_config()
    gw_config = config.get("gateway", {})

    # Build gateway configs from TOML config
    for platform in PlatformType:
        platform_key = platform.value
        platform_cfg = gw_config.get(platform_key, {})
        if not platform_cfg or not platform_cfg.get("enabled", False):
            continue

        gw_config_obj = GatewayConfig(
            platform=platform,
            enabled=True,
            config=platform_cfg,
            rate_limit=platform_cfg.get("rate_limit", 1.0),
            max_message_length=platform_cfg.get("max_message_length", 4096),
            session_ttl_seconds=platform_cfg.get("session_ttl_seconds", 3600.0),
            auto_reconnect=platform_cfg.get("auto_reconnect", True),
            max_reconnect_attempts=platform_cfg.get("max_reconnect_attempts", 5),
            health_check_interval=platform_cfg.get("health_check_interval", 30.0),
            allowed_users=platform_cfg.get("allowed_users", []),
            admin_users=platform_cfg.get("admin_users", []),
        )
        manager.add_gateway(gw_config_obj)

    # Filter by --platforms if specified
    if args.platforms:
        for key in list(manager._instances.keys()):
            if key not in args.platforms:
                del manager._instances[key]

    if not manager._instances:
        print("No gateways configured. Use 'noman gateway setup' first.")
        return 1

    async def _run():
        await manager.start()
        print(f"GatewayManager started with {len(manager._instances)} gateway(s)")

        # Get status
        status = manager.get_status()
        for name, info in status.gateway_statuses.items():
            print(f"  [{info['status']}] {name}")

        # Wait for keyboard interrupt
        try:
            import signal
            loop = asyncio.get_event_loop()
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\nShutting down gateways...")
        finally:
            await manager.stop()
            print("Gateways stopped.")

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass
    return 0


def _cmd_gateway_status(args) -> int:
    """Show gateway status."""
    from core.gateway.scheduler import GatewayManager

    manager = GatewayManager()

    # Check for existing running gateways
    pid_file = Path.home() / ".noman" / "gateways.pid"
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            import os
            os.kill(pid, 0)  # Check if process exists
            is_running = True
        except (ProcessLookupError, ValueError):
            is_running = False
    else:
        is_running = False

    if not is_running:
        print("GatewayManager is not running.")
        return 1

    # Get status from manager
    status = manager.get_status()
    print(f"GatewayManager status: {'running' if status.running else 'stopped'}")
    print(f"Uptime: {status.uptime_seconds:.0f}s")
    print(f"Gateways: {status.running_gateways}/{status.total_gateways} running")

    if args.platform:
        info = manager.get_gateway_status(args.platform)
        if info:
            print(f"\n{args.platform}:")
            for k, v in info.items():
                print(f"  {k}: {v}")
        else:
            print(f"  No status for platform: {args.platform}")
    else:
        if args.json:
            import json
            print(json.dumps(status.gateway_statuses, indent=2))
        else:
            print("\nPlatform status:")
            for name, info in status.gateway_statuses.items():
                status_str = info.get("status", "unknown")
                enabled_str = "enabled" if info.get("enabled") else "disabled"
                msg = info.get("messages_processed", 0)
                errs = info.get("errors", 0)
                print(f"  [{status_str:>10}] {name:<15} ({enabled_str}) "
                      f"msgs={msg} err={errs}")

    return 0


def _cmd_gateway_setup(args) -> int:
    """Configure gateway platforms via interactive wizard."""
    from core.gateway.base import PlatformType

    config_path = Path.home() / ".noman" / "config.toml"
    config = _load_config() if config_path.exists() else {}

    platform_name = args.platform
    if platform_name:
        # Single platform setup
        return _setup_single_platform(platform_name, args)

    # Interactive wizard
    print("=== NoMan Gateway Setup Wizard ===\n")
    print("Configure which messaging platforms to enable.\n")

    platforms = [
        (PlatformType.TELEGRAM, "Telegram Bot"),
        (PlatformType.DISCORD, "Discord Bot"),
        (PlatformType.SLACK, "Slack Bot"),
        (PlatformType.WHATSAPP, "WhatsApp Cloud API"),
        (PlatformType.SIGNAL, "Signal CLI"),
        (PlatformType.MATRIX, "Matrix (Element)"),
        (PlatformType.WEBHOOK, "Generic Webhook Server"),
        (PlatformType.FEISHU, "Feishu/Lark"),
        (PlatformType.WECHAT, "WeChat Enterprise"),
        (PlatformType.HOMEASSISTANT, "Home Assistant"),
    ]

    # Ensure gateway section exists
    if "gateway" not in config:
        config["gateway"] = {}

    for plat, label in platforms:
        key = plat.value
        current = config["gateway"].get(key, {})
        enabled = current.get("enabled", False)
        enabled_str = "ON" if enabled else "OFF"

        print(f"[{enabled_str}] {label} ({key})")

        choice = input(f"  Enable {label}? [y/N]: ").strip().lower()
        if choice in ("y", "yes"):
            config["gateway"][key] = {"enabled": True}
            if key == "webhook":
                port = input(f"  Port [{current.get('port', 9090)}]: ").strip()
                config["gateway"][key]["port"] = int(port) if port else 9090
            else:
                token = input(f"  {label} token/key: ").strip()
                if token:
                    config["gateway"][key]["bot_token" if key != "whatsapp" else "phone_number_id"] = token

    # Save config
    try:
        import tomllib
        # Read existing config properly
        if config_path.exists():
            with open(config_path, "rb") as f:
                config = tomllib.load(f)
        else:
            config = _default_config()

        # Apply gateway config
        if "gateway" not in config:
            config["gateway"] = {}
        config["gateway"].update({
            key: val for key, val in config.get("_new_gateway", {}).items()
        })

        config_path.write_text(str(config))  # Will need toml dump
        print(f"\nConfig saved to {config_path}")
    except ImportError:
        print("\nNote: tomllib not available, config saved as dict.")
        config_path.write_text(str(config))

    print("\nDone! Use 'noman gateway run' to start the gateways.")
    return 0


def _setup_single_platform(platform_name: str, args) -> int:
    """Set up a single platform interactively."""
    config_path = Path.home() / ".noman" / "config.toml"
    config = _load_config() if config_path.exists() else {}

    if "gateway" not in config:
        config["gateway"] = {}

    platform_name = platform_name.lower()
    print(f"=== Setup {platform_name} ===")

    token = args.token or input("Enter token/key: ").strip()
    port = args.port
    if port is None:
        port = int(input("Port [default: 9090]: ") or "9090")

    config["gateway"][platform_name] = {
        "enabled": True,
    }
    if token:
        config["gateway"][platform_name]["bot_token" if platform_name not in ("whatsapp", "matrix") else "phone_number_id"] = token
    if port:
        config["gateway"][platform_name]["port"] = port

    config_path.write_text(str(config))
    print(f"Saved to {config_path}")
    return 0


def _cmd_gateway_install(args) -> int:
    """Install gateway manager as a system service."""
    import platform as plat_module
    system = plat_module.system()

    if args.systemd:
        service_file = Path.home() / ".noman" / "noman-gateway.service"
        service_content = f"""[Unit]
Description=NoMan Gateway Manager
After=network.target

[Service]
Type=simple
User={plat_module.getuser()}
WorkingDirectory={Path.cwd()}
ExecStart={sys.executable} -m noman_cli gateway run
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
"""
        service_file.write_text(service_content)
        print(f"Service file created: {service_file}")
        print("Install with: systemctl --user enable --now noman-gateway.service")

    elif args.launchd:
        plist = Path.home() / "Library" / "LaunchAgents" / "com.noman.gateway.plist"
        plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.noman.gateway</string>
    <key>ProgramArguments</key>
    <array>
        <string>{sys.executable}</string>
        <string>-m</string>
        <string>noman_cli</string>
        <string>gateway</string>
        <string>run</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{Path.cwd()}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
"""
        plist.parent.mkdir(parents=True, exist_ok=True)
        plist.write_text(plist_content)
        print(f"plist created: {plist}")
        print(f"Install with: launchctl load {plist}")

    else:
        print("NoMan Gateway can be installed as a service:")
        print("  --systemd  : Install as systemd service (Linux)")
        print("  --launchd  : Install as launchd service (macOS)")
        print("\nOr run manually:")
        print("  noman gateway run")

    return 0


def _cmd_gateway_start(args) -> int:
    """Start gateway manager."""
    pid_file = Path.home() / ".noman" / "gateways.pid"

    # Check if already running
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            import os
            os.kill(pid, 0)
            print(f"GatewayManager already running (PID {pid})")
            return 0
        except (ProcessLookupError, ValueError):
            pid_file.unlink(missing_ok=True)

    print("Starting GatewayManager...")
    print("Use 'noman gateway status' to check status.")
    print("Press Ctrl+C to stop.")

    import asyncio
    from cli.main import main as _main

    # Reuse 'run' logic
    return _cmd_gateway_run(args)


def _cmd_gateway_stop(args) -> int:
    """Stop gateway manager."""
    pid_file = Path.home() / ".noman" / "gateways.pid"

    if not pid_file.exists():
        print("GatewayManager is not running (no PID file).")
        return 0

    try:
        pid = int(pid_file.read_text().strip())
        import os
        os.kill(pid, 15)  # SIGTERM
        print(f"GatewayManager stopped (PID {pid}).")
        pid_file.unlink()
        return 0
    except (ProcessLookupError, ValueError) as e:
        print(f"Failed to stop: {e}")
        return 1


def _cmd_gateway_restart(args) -> int:
    """Restart gateway manager."""
    _cmd_gateway_stop(args)
    return _cmd_gateway_start(args)


def _cmd_gateway_list() -> int:
    """List all gateway configurations."""
    config_path = Path.home() / ".noman" / "config.toml"

    if not config_path.exists():
        print("No config file found. Run 'noman gateway setup' first.")
        return 1

    config = _load_config()
    gw_config = config.get("gateway", {})

    if not gw_config:
        print("No gateways configured.")
        return 0

    from core.gateway.base import PlatformType

    platform_names = {
        PlatformType.TELEGRAM: "Telegram",
        PlatformType.DISCORD: "Discord",
        PlatformType.SLACK: "Slack",
        PlatformType.WHATSAPP: "WhatsApp",
        PlatformType.SIGNAL: "Signal",
        PlatformType.MATRIX: "Matrix",
        PlatformType.WEBHOOK: "Webhook",
        PlatformType.FEISHU: "Feishu/Lark",
        PlatformType.WECHAT: "WeChat",
        PlatformType.HOMEASSISTANT: "Home Assistant",
    }

    print("=== Gateway Configurations ===\n")
    print(f"{'Platform':<20} {'Status':<10} {'Configured':<10}")
    print("-" * 42)

    for plat in PlatformType:
        key = plat.value
        enabled = gw_config.get(key, {}).get("enabled", False)
        has_config = key in gw_config
        status = "enabled" if enabled else "disabled"
        config_str = "yes" if has_config else "no"
        print(f"{platform_names.get(plat, plat.value):<20} {status:<10} {config_str:<10}")

    print(f"\nTotal: {sum(1 for p in gw_config.values() if p.get('enabled'))} enabled")
    return 0


# --- Cron command handlers ---

def _cmd_cron_list(args) -> int:
    """List all cron jobs."""
    from core.cron.manager import CronManager
    from core.cron.jobs import JobStatus

    manager = CronManager()
    status_str = getattr(args, "status", None)
    enabled_only = getattr(args, "enabled", False)
    json_out = getattr(args, "json", False)

    status_filter = None
    if status_str:
        try:
            status_filter = JobStatus(status_str)
        except ValueError:
            print(f"Invalid status: {status_str}. Valid: pending, running, completed, failed, paused")
            return 1

    jobs = manager.list_jobs(status=status_filter, enabled_only=enabled_only)

    if json_out:
        import json
        print(json.dumps([j.to_dict() for j in jobs], indent=2))
    else:
        print(manager.format_job_list(jobs))

    return 0


def _cmd_cron_create(args) -> int:
    """Create a new cron job."""
    from core.cron.manager import CronManager

    manager = CronManager()

    name = getattr(args, "name", None) or f"job-{args.schedule[:10].replace(' ', '-')}"
    schedule = args.schedule
    prompt = args.prompt
    delivery = getattr(args, "delivery", "origin")
    skills_str = getattr(args, "skills", None)
    repeat = getattr(args, "repeat", None)
    max_attempts = getattr(args, "max_attempts", 0)

    skills = [s.strip() for s in skills_str.split(",") if s.strip()] if skills_str else []

    job = manager.create_job(
        name=name,
        schedule=schedule,
        prompt=prompt,
        delivery=delivery,
        skills=skills,
        repeat=repeat,
        max_attempts=max_attempts,
    )

    print(f"Job created: {job.name}")
    print(f"  ID:     {job.id}")
    print(f"  Schedule: {job.schedule}")
    print(f"  Prompt:   {job.prompt[:80]}")
    print(f"  Delivery: {job.delivery}")
    print(f"  Next run: {job.next_run.isoformat() if job.next_run else 'N/A'}")
    return 0


def _cmd_cron_edit(args) -> int:
    """Edit a cron job."""
    from core.cron.manager import CronManager

    manager = CronManager()
    job_id = args.job_id

    fields = {}
    if hasattr(args, "name") and args.name:
        fields["name"] = args.name
    if hasattr(args, "schedule") and args.schedule:
        fields["schedule"] = args.schedule
    if hasattr(args, "prompt") and args.prompt:
        fields["prompt"] = args.prompt
    if hasattr(args, "delivery") and args.delivery:
        fields["delivery"] = args.delivery
    skills_str = getattr(args, "skills", None)
    if skills_str:
        fields["skills"] = [s.strip() for s in skills_str.split(",") if s.strip()]
    if hasattr(args, "repeat") and args.repeat is not None:
        fields["repeat"] = args.repeat
    if hasattr(args, "enable") and args.enable:
        fields["enabled"] = True
    if hasattr(args, "disable") and args.disable:
        fields["enabled"] = False

    try:
        job = manager.update_job(job_id, **fields)
        print(f"Job updated: {job.name}")
        print(f"  Schedule: {job.schedule}")
        print(f"  Prompt:   {job.prompt[:80]}")
        print(f"  Enabled:  {job.enabled}")
        print(f"  Next run: {job.next_run.isoformat() if job.next_run else 'N/A'}")
        return 0
    except Exception as e:
        print(f"Error updating job: {e}")
        return 1


def _cmd_cron_pause(args) -> int:
    """Pause a cron job."""
    from core.cron.manager import CronManager

    manager = CronManager()
    job = manager.pause_job(args.job_id)
    print(f"Job paused: {job.name} ({job.id})")
    return 0


def _cmd_cron_resume(args) -> int:
    """Resume a paused cron job."""
    from core.cron.manager import CronManager

    manager = CronManager()
    job = manager.resume_job(args.job_id)
    print(f"Job resumed: {job.name} ({job.id})")
    print(f"  Next run: {job.next_run.isoformat() if job.next_run else 'N/A'}")
    return 0


def _cmd_cron_remove(args) -> int:
    """Remove a cron job."""
    from core.cron.manager import CronManager

    manager = CronManager()
    if manager.remove_job(args.job_id):
        print(f"Job removed: {args.job_id}")
        return 0
    else:
        print(f"Job not found: {args.job_id}")
        return 1


def _cmd_cron_run(args) -> int:
    """Run a job immediately."""
    import asyncio
    from core.cron.manager import CronManager

    manager = CronManager()
    try:
        result = asyncio.run(manager.run_job(args.job_id))
        print("Job executed successfully.")
        print(result)
        return 0
    except Exception as e:
        print(f"Error running job: {e}")
        return 1


def _cmd_cron_status() -> int:
    """Show scheduler status."""
    from core.cron.scheduler import CronScheduler, SchedulerConfig

    config = SchedulerConfig()
    scheduler = CronScheduler(config=config)
    state = scheduler.get_state()

    print(f"Scheduler: {'running' if state.running else 'stopped'}")
    print(f"  Total jobs:   {state.jobs_count}")
    print(f"  Enabled:      {state.enabled_jobs}")
    print(f"  Pending:      {state.pending_jobs}")
    print(f"  Running:      {state.running_jobs}")
    print(f"  Failed:       {state.failed_jobs}")
    print(f"  Uptime:       {state.uptime_seconds:.0f}s")
    scheduler.shutdown()
    return 0


# --- Webhook command handlers ---

def _cmd_webhook_list(args) -> int:
    """List all webhook subscriptions."""
    from core.webhooks.router import WebhookRouter
    import json

    router = WebhookRouter()
    subs = router.list_subscriptions()

    if getattr(args, "json", False):
        print(json.dumps([s.to_dict() for s in subs], indent=2))
    else:
        if not subs:
            print("No webhook subscriptions.")
            return 0
        print(f"{'Name':<25} {'Path':<25} {'Events':<30} {'Enabled':>8}")
        print("-" * 90)
        for s in subs:
            events = ",".join(s.events) if s.events else "all"
            print(f"{s.name:<25} {s.path:<25} {events:<30} {'Yes' if s.enabled else 'No':>8}")
        print(f"\nTotal: {len(subs)} subscriptions")
    return 0


def _cmd_webhook_subscribe(args) -> int:
    """Create a webhook subscription."""
    from core.webhooks.router import WebhookRouter
    from core.webhooks.subscriptions import WebhookSubscription

    router = WebhookRouter()
    name = args.name

    # Check if subscription already exists
    existing = router.get_subscription(name)
    if existing:
        print(f"Subscription '{name}' already exists.")
        return 1

    path = getattr(args, "path", "/webhooks/default")
    events_str = getattr(args, "events", None)
    events = [e.strip() for e in events_str.split(",") if e.strip()] if events_str else []
    delivery = getattr(args, "delivery", "origin")
    headers_str = getattr(args, "headers", None)
    headers = {}
    if headers_str:
        for pair in headers_str.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                headers[k.strip()] = v.strip()

    sub = WebhookSubscription(
        name=name,
        path=path,
        events=events,
        delivery=delivery,
        headers=headers,
    )
    router.add_subscription(sub)

    print(f"Subscription created: {sub.name}")
    print(f"  Path:     {sub.path}")
    print(f"  Events:   {','.join(sub.events) if sub.events else 'all'}")
    print(f"  Delivery: {sub.delivery}")
    print(f"  Secret:   {sub.secret[:16]}...")
    return 0


def _cmd_webhook_remove(args) -> int:
    """Remove a webhook subscription."""
    from core.webhooks.router import WebhookRouter

    router = WebhookRouter()
    if router.remove_subscription(args.name):
        print(f"Subscription removed: {args.name}")
        return 0
    else:
        print(f"Subscription not found: {args.name}")
        return 1


def _cmd_webhook_test(args) -> int:
    """Test a webhook subscription."""
    import asyncio
    from core.webhooks.router import WebhookRouter

    router = WebhookRouter()
    sub = router.get_subscription(args.name)
    if not sub:
        print(f"Subscription not found: {args.name}")
        return 1

    print(f"Testing subscription: {sub.name}")
    print(f"  Path: {sub.path}")
    print(f"  Events: {','.join(sub.events) if sub.events else 'all'}")
    print(f"  Secret: {sub.secret[:16]}...")
    print(f"  Delivery: {sub.delivery}")

    # Try to connect and test via the server
    try:
        from core.webhooks.server import WebhookServer
        server = WebhookServer(router=router)
        asyncio.run(server.start())
        import urllib.request
        url = f"{server.url}/webhooks/test/{args.name}"
        req = urllib.request.Request(url, method="POST", data=b"{}")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=5) as resp:
            result = resp.read().decode()
            print(f"\nTest result: {result}")
        asyncio.run(server.stop())
    except Exception as e:
        print(f"Test failed (server not available): {e}")
        print("  Manual test: POST to http://localhost:9090/webhooks/test/{name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
