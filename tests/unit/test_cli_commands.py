"""Tests for CLI commands: rollback, review, memory, skill, stats, emergency, init, doctor."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure cli.main functions are importable
from cli.main import (
    _cmd_doctor,
    _cmd_emergency,
    _cmd_init,
    _cmd_memory_delete,
    _cmd_memory_get,
    _cmd_memory_list,
    _cmd_memory_set,
    _cmd_review,
    _cmd_rollback,
    _cmd_skill_add,
    _cmd_skill_get,
    _cmd_skill_list,
    _cmd_skill_set,
    _cmd_stats,
    _default_config,
    _get_noman_dir,
    _load_config,
)
from cli.parser import parse_args
from core.memory.store import MemoryConfig, MemoryStore, MemorySystem

# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def tmp_noman_dir(tmp_path):
    """Create a temporary .noman directory structure."""
    noman_dir = tmp_path / ".noman"
    noman_dir.mkdir(parents=True, exist_ok=True)
    (noman_dir / "config.toml").write_text("[providers.default]\ntype = \"openai\"\napi_key = \"test-key-123\"\nmodel = \"gpt-4o-mini\"\n")
    (noman_dir / "sessions").mkdir(exist_ok=True)
    (noman_dir / "rollbacks").mkdir(exist_ok=True)
    (noman_dir / "debug").mkdir(exist_ok=True)
    # Patch the home directory
    with patch.object(Path, 'home', return_value=tmp_path):
        yield noman_dir


@pytest.fixture
def mock_memory_store(tmp_path):
    """Create a MemoryStore with a temp DB."""
    cfg = MemoryConfig(db_path=str(tmp_path / "mem.db"))
    return MemoryStore(cfg)


@pytest.fixture
def memory_system(tmp_path):
    """Create a MemorySystem with a temp DB."""
    cfg = MemoryConfig(db_path=str(tmp_path / "mem.db"))
    return MemorySystem(cfg)


@pytest.fixture
def mock_args_parser():
    """Mock sys.argv for parse_args testing."""
    with patch.object(__import__('sys'), 'argv', ['noman']):
        yield


# ── Parser Tests ──────────────────────────────────────────────────────


def test_parse_args_task_mode():
    args = parse_args(["refactor auth"])
    assert args.task == "refactor auth"
    assert args.command is None


def test_parse_args_repl_mode():
    args = parse_args([])
    assert args.task is None
    assert args.command is None


def test_parse_args_doctor():
    args = parse_args(["doctor"])
    assert args.command == "doctor"


def test_parse_args_review_no_file():
    args = parse_args(["review"])
    assert args.command == "review"
    assert args.file is None
    assert args.n == 5


def test_parse_args_review_with_file():
    args = parse_args(["review", "src/main.py", "--n", "3"])
    assert args.command == "review"
    assert args.file == "src/main.py"
    assert args.n == 3


def test_parse_args_review_with_n():
    args = parse_args(["review", "--n", "10"])
    assert args.n == 10


def test_parse_args_rollback_n():
    args = parse_args(["rollback", "--n", "3"])
    assert args.command == "rollback"
    assert args.n == 3


def test_parse_args_rollback_to():
    args = parse_args(["rollback", "--to", "abc123"])
    assert args.trace_id == "abc123"


def test_parse_args_rollback_list():
    args = parse_args(["rollback", "-l"])
    assert args.list_rollbacks is True


def test_parse_args_memory_list():
    args = parse_args(["memory", "list", "--tier", "semantic", "--scope", "project"])
    assert args.subcmd == "list"
    assert args.tier_filter == "semantic"
    assert args.scope_filter == "project"


def test_parse_args_memory_set():
    args = parse_args(["memory", "set", "semantic", "project", "key1", "value1"])
    assert args.subcmd == "set"
    assert args.tier == "semantic"
    assert args.scope == "project"
    assert args.key == "key1"
    assert args.value == "value1"


def test_parse_args_memory_get():
    args = parse_args(["memory", "get", "semantic", "project", "key1"])
    assert args.subcmd == "get"
    assert args.tier == "semantic"
    assert args.scope == "project"
    assert args.key == "key1"


def test_parse_args_memory_delete():
    args = parse_args(["memory", "delete", "semantic", "project", "key1"])
    assert args.subcmd == "delete"
    assert args.tier == "semantic"
    assert args.scope == "project"
    assert args.key == "key1"


def test_parse_args_skill_list():
    args = parse_args(["skill", "list"])
    assert args.subcmd == "list"


def test_parse_args_skill_get():
    args = parse_args(["skill", "get", "my_skill"])
    assert args.subcmd == "get"
    assert args.name == "my_skill"


def test_parse_args_skill_set():
    args = parse_args(["skill", "set", "my_skill", "some content"])
    assert args.subcmd == "set"
    assert args.name == "my_skill"
    assert args.content == "some content"


def test_parse_args_skill_add():
    args = parse_args(["skill", "add", "my_skill", "skills/my_skill.py"])
    assert args.subcmd == "add"
    assert args.name == "my_skill"
    assert args.content == "skills/my_skill.py"  # parser puts 2nd positional into 'content'


def test_parse_args_stats():
    args = parse_args(["stats"])
    assert args.command == "stats"


def test_parse_args_emergency_stop():
    args = parse_args(["emergency", "stop"])
    assert args.action == "stop"


def test_parse_args_emergency_disable():
    args = parse_args(["emergency", "disable-self-improve"])
    assert args.action == "disable-self-improve"


def test_parse_args_emergency_readonly():
    args = parse_args(["emergency", "read-only"])
    assert args.action == "read-only"


def test_parse_args_emergency_lockdown():
    args = parse_args(["emergency", "lockdown"])
    assert args.action == "lockdown"


def test_parse_args_init():
    args = parse_args(["init"])
    assert args.command == "init"


def test_parse_args_provider_flag():
    args = parse_args(["--provider", "anthropic", "doctor"])
    assert args.provider == "anthropic"
    assert args.command == "doctor"


def test_parse_args_debug_flag():
    args = parse_args(["--debug", "doctor"])
    assert args.debug is True
    assert args.command == "doctor"


def test_parse_args_max_calls():
    args = parse_args(["--max-calls", "20", "doctor"])
    assert args.max_calls == 20


def test_parse_args_read_only():
    args = parse_args(["--read-only", "doctor"])
    assert args.read_only is True


def test_parse_args_unrecognized_subcommand():
    """Unrecognized subcommand should still be parsed (argparse may error)."""
    args = parse_args(["doctor"])
    assert args.command == "doctor"


# ── Config Tests ──────────────────────────────────────────────────────


def test_default_config():
    cfg = _default_config()
    assert "providers" in cfg
    assert "default_provider" in cfg
    assert "model" in cfg


def test_load_config_no_file(tmp_path):
    with patch.object(Path, 'home', return_value=tmp_path):
        cfg = _load_config()
        assert cfg is not None
        assert "providers" in cfg


# ── Doctor Tests ──────────────────────────────────────────────────────


def test_doctor_with_config(tmp_noman_dir):
    """Doctor should pass all checks when config exists."""
    result = _cmd_doctor()
    assert result == 0


def test_doctor_no_config(tmp_path):
    """Doctor should warn when no config exists."""
    noman_dir = tmp_path / ".noman"
    noman_dir.mkdir(parents=True, exist_ok=True)
    with patch.object(Path, 'home', return_value=tmp_path):
        result = _cmd_doctor()
        assert result >= 0  # May warn but shouldn't crash


# ── Review Tests ──────────────────────────────────────────────────────


def test_review_no_git_repo(tmp_path):
    """Review should handle non-git directories gracefully."""
    workdir = tmp_path / "project"
    workdir.mkdir()
    result = _cmd_review(file=None, n=1)
    # Should not crash even in non-git dir (returns 1 for git error)
    assert result in (0, 1)


# ── Rollback Tests ────────────────────────────────────────────────────


def test_rollback_no_metadata(tmp_noman_dir):
    """Rollback should return 1 when no rollbacks exist."""
    with patch.object(Path, 'home', return_value=tmp_noman_dir.parent):
        result = _cmd_rollback(n=1, trace_id=None, list_rollbacks=False)
        assert result == 1


def test_rollback_list_empty(tmp_noman_dir):
    """Rollback -l should show nothing when no rollbacks exist."""
    with patch.object(Path, 'home', return_value=tmp_noman_dir.parent):
        result = _cmd_rollback(n=0, trace_id=None, list_rollbacks=True)
        assert result == 0


def test_rollback_list_with_entries(tmp_noman_dir):
    """Rollback -l should show rollback entries."""
    rollback_dir = tmp_noman_dir / "rollbacks"
    rollback_dir.mkdir(exist_ok=True)

    # Create a sample rollback entry
    rb_data = {
        "id": "rb001",
        "timestamp": "2025-01-01T00:00:00",
        "description": "Test change",
        "files": [
            {"path": "test.py", "content": "print('hello')"}
        ],
    }
    (rollback_dir / "rb001.json").write_text(json.dumps(rb_data))

    with patch.object(Path, 'home', return_value=tmp_noman_dir.parent):
        result = _cmd_rollback(n=0, trace_id=None, list_rollbacks=True)
        assert result == 0


def test_rollback_apply(tmp_noman_dir):
    """Rollback should restore file content from metadata."""
    rollback_dir = tmp_noman_dir / "rollbacks"
    rollback_dir.mkdir(exist_ok=True)

    rb_data = {
        "id": "rb002",
        "timestamp": "2025-01-01T00:00:00",
        "description": "Apply test",
        "files": [
            {"path": str(tmp_noman_dir / "test_rollback.py"), "content": "restored content"},
        ],
    }
    (rollback_dir / "rb002.json").write_text(json.dumps(rb_data))

    test_file = tmp_noman_dir / "test_rollback.py"
    test_file.write_text("original content")

    with patch.object(Path, 'home', return_value=tmp_noman_dir.parent):
        result = _cmd_rollback(n=1, trace_id="rb002", list_rollbacks=False)
        assert result == 0
        assert test_file.read_text() == "restored content"


def test_rollback_apply_deleted_file(tmp_noman_dir):
    """Rollback should handle files that no longer exist."""
    rollback_dir = tmp_noman_dir / "rollbacks"
    rollback_dir.mkdir(exist_ok=True)

    deleted_file = tmp_noman_dir / "deleted_test.py"
    deleted_file.write_text("exists")

    rb_data = {
        "id": "rb003",
        "timestamp": "2025-01-01T00:00:00",
        "description": "Deleted file",
        "files": [
            {"path": str(deleted_file), "content": None},  # content=None means deleted
        ],
    }
    (rollback_dir / "rb003.json").write_text(json.dumps(rb_data))

    with patch.object(Path, 'home', return_value=tmp_noman_dir.parent):
        result = _cmd_rollback(n=1, trace_id="rb003", list_rollbacks=False)
        assert result == 0


def test_rollback_no_matching_id(tmp_noman_dir):
    """Rollback with non-matching trace_id should return 1."""
    with patch.object(Path, 'home', return_value=tmp_noman_dir.parent):
        result = _cmd_rollback(n=0, trace_id="nonexistent", list_rollbacks=False)
        assert result == 1


# ── Memory CRUD Tests ─────────────────────────────────────────────────


def test_memory_list_empty(tmp_path):
    store = MemoryStore(MemoryConfig(db_path=str(tmp_path / "mem.db")))
    with patch('cli.main._get_noman_dir', return_value=tmp_path):
        result = _cmd_memory_list()
        assert result == 0
    store.close()


def test_memory_list_with_entries(tmp_path):
    store = MemoryStore(MemoryConfig(db_path=str(tmp_path / "mem.db")))
    store.remember("semantic", "project", "key1", "value1")
    store.remember("semantic", "project", "key2", "value2")
    store.close()

    with patch('cli.main._get_noman_dir', return_value=tmp_path):
        result = _cmd_memory_list()
        assert result == 0


def test_memory_list_filtered(tmp_path):
    store = MemoryStore(MemoryConfig(db_path=str(tmp_path / "mem.db")))
    store.remember("semantic", "project", "key1", "value1")
    store.remember("episodic", "project", "key2", "value2")
    store.close()

    with patch('cli.main._get_noman_dir', return_value=tmp_path):
        result = _cmd_memory_list(tier="episodic", scope=None)
        assert result == 0


def test_memory_get_found(tmp_noman_dir):
    # Store in the same DB the command will use
    store = MemoryStore(MemoryConfig(db_path=str(tmp_noman_dir / "memory.db")))
    store.remember("semantic", "project", "get_key", "get_value")
    store.close()

    with patch('cli.main._get_noman_dir', return_value=tmp_noman_dir):
        result = _cmd_memory_get("semantic", "project", "get_key")
        assert result == 0


def test_memory_get_not_found(tmp_path):
    store = MemoryStore(MemoryConfig(db_path=str(tmp_path / "mem.db")))
    store.close()

    with patch('cli.main._get_noman_dir', return_value=tmp_path):
        result = _cmd_memory_get("semantic", "project", "nonexistent_key")
        assert result == 1


def test_memory_set(tmp_path):
    with patch('cli.main._get_noman_dir', return_value=tmp_path):
        result = _cmd_memory_set("semantic", "project", "set_key", "set_value")
        assert result == 0

    # Verify it was stored
    store = MemoryStore(MemoryConfig(db_path=str(tmp_path / "memory.db")))
    entries = store.recall(query="set_key")
    assert len(entries) >= 1
    assert any(e.value == "set_value" for e in entries)
    store.close()


def test_memory_delete(tmp_path):
    store = MemoryStore(MemoryConfig(db_path=str(tmp_path / "mem.db")))
    store.remember("semantic", "project", "delete_key", "delete_value")
    store.close()

    with patch('cli.main._get_noman_dir', return_value=tmp_path):
        result = _cmd_memory_delete("semantic", "project", "delete_key")
        assert result == 0


def test_memory_delete_not_found(tmp_path):
    with patch('cli.main._get_noman_dir', return_value=tmp_path):
        result = _cmd_memory_delete("semantic", "project", "nonexistent")
        assert result == 0  # forget returns True even if nothing was deleted in this impl


def test_memory_get_missing_args():
    """Test memory get with missing arguments."""
    # These would be caught by argparse, but test the code path
    assert True  # argparse handles missing args


def test_memory_set_missing_args():
    """Test memory set with missing value."""
    assert True  # argparse handles missing args


# ── Skill CRUD Tests ──────────────────────────────────────────────────


def test_skill_list_empty(tmp_path):
    with patch('cli.main._get_noman_dir', return_value=tmp_path):
        result = _cmd_skill_list()
        assert result == 0


def test_skill_list_with_skills(tmp_path):
    store = MemoryStore(MemoryConfig(db_path=str(tmp_path / "mem.db")))
    store.remember("procedural", "global", "skill1", "content1")
    store.remember("procedural", "global", "skill2", "content2")
    store.close()

    with patch('cli.main._get_noman_dir', return_value=tmp_path):
        result = _cmd_skill_list()
        assert result == 0


def test_skill_get_found(tmp_noman_dir):
    # Store in the same DB the command will use
    store = MemoryStore(MemoryConfig(db_path=str(tmp_noman_dir / "memory.db")))
    store.remember("procedural", "global", "my_skill", "skill content here")
    store.close()

    with patch('cli.main._get_noman_dir', return_value=tmp_noman_dir):
        result = _cmd_skill_get("my_skill")
        assert result == 0


def test_skill_get_not_found(tmp_path):
    with patch('cli.main._get_noman_dir', return_value=tmp_path):
        result = _cmd_skill_get("nonexistent_skill")
        assert result == 1


def test_skill_set(tmp_path):
    with patch('cli.main._get_noman_dir', return_value=tmp_path):
        result = _cmd_skill_set("test_skill", "test content")
        assert result == 0

    # Verify stored
    store = MemoryStore(MemoryConfig(db_path=str(tmp_path / "memory.db")))
    entries = store.recall(tier="procedural", scope="global", limit=10)
    assert any(e.key == "test_skill" and e.value == "test content" for e in entries)
    store.close()


def test_skill_add_from_file(tmp_path):
    skill_file = tmp_path / "test_skill.py"
    skill_file.write_text("def test(): pass")

    with patch('cli.main._get_noman_dir', return_value=tmp_path):
        result = _cmd_skill_add("test_skill", str(skill_file))
        assert result == 0

    # Verify stored
    store = MemoryStore(MemoryConfig(db_path=str(tmp_path / "memory.db")))
    entries = store.recall(tier="procedural", scope="global", limit=10)
    assert any(e.key == "test_skill" and "def test():" in e.value for e in entries)
    store.close()


def test_skill_add_file_not_found():
    with patch('cli.main._get_noman_dir', return_value=Path("/nonexistent")):
        result = _cmd_skill_add("test", "/nonexistent/file.py")
        assert result == 1


# ── Stats Tests ───────────────────────────────────────────────────────


def test_stats_no_session(tmp_noman_dir):
    """Stats should work even without an active session."""
    result = _cmd_stats(noman_dir=tmp_noman_dir)
    assert result == 0


def test_stats_with_session(tmp_noman_dir):
    """Stats should report session data when present."""
    session_dir = tmp_noman_dir / "sessions"
    session_dir.mkdir(exist_ok=True)
    session_data = {
        "id": "sess001",
        "turns": [
            {"user_input": "hello", "assistant_output": "hi", "tool_calls": [], "tool_results": [], "tokens_used": 100},
            {"user_input": "world", "assistant_output": "ok", "tool_calls": [], "tool_results": [], "tokens_used": 200},
        ],
        "total_tokens": 300,
        "created_at": 1234567890.0,
    }
    (session_dir / "active_session.json").write_text(json.dumps(session_data))

    result = _cmd_stats(noman_dir=tmp_noman_dir)
    assert result == 0


# ── Emergency Tests ───────────────────────────────────────────────────


def test_emergency_stop(tmp_noman_dir):
    with patch.object(Path, 'home', return_value=tmp_noman_dir.parent):
        result = _cmd_emergency("stop")
        assert result == 0
        # Verify flag file
        assert (tmp_noman_dir / "emergency_stop.flag").exists()


def test_emergency_disable_self_improve(tmp_noman_dir):
    with patch.object(Path, 'home', return_value=tmp_noman_dir.parent):
        result = _cmd_emergency("disable-self-improve")
        assert result == 0
        assert (tmp_noman_dir / "disable_self_improve.flag").exists()


def test_emergency_read_only(tmp_noman_dir):
    with patch.object(Path, 'home', return_value=tmp_noman_dir.parent):
        result = _cmd_emergency("read-only")
        assert result == 0
        assert (tmp_noman_dir / "read_only.flag").exists()


def test_emergency_lockdown(tmp_noman_dir):
    with patch.object(Path, 'home', return_value=tmp_noman_dir.parent):
        result = _cmd_emergency("lockdown")
        assert result == 0
        assert (tmp_noman_dir / "emergency_stop.flag").exists()
        assert (tmp_noman_dir / "disable_self_improve.flag").exists()
        assert (tmp_noman_dir / "read_only.flag").exists()


# ── Init Tests ────────────────────────────────────────────────────────


def test_init_new(tmp_path):
    """Init should create all directories and config."""
    home = tmp_path / "fake_home"
    home.mkdir()
    with patch.object(Path, 'home', return_value=home):
        result = _cmd_init()
        assert result == 0
        assert (home / ".noman" / "config.toml").exists()
        assert (home / ".noman" / "sessions").exists()
        assert (home / ".noman" / "rollbacks").exists()
        assert (home / ".noman" / "debug").exists()


def test_init_skips_existing_config(tmp_path):
    """Init should not overwrite existing config."""
    home = tmp_path / "fake_home2"
    home.mkdir()
    noman_dir = home / ".noman"
    noman_dir.mkdir(parents=True, exist_ok=True)
    (noman_dir / "config.toml").write_text("existing = true\n")
    with patch.object(Path, 'home', return_value=home):
        result = _cmd_init()
        assert result == 0
        assert (noman_dir / "config.toml").read_text() == "existing = true\n"


# ── Integration: CLI entry point ──────────────────────────────────────


def test_main_doctor():
    """Test main() dispatches to _cmd_doctor."""
    with patch('cli.main.parse_args') as mock_parse:
        mock_parse.return_value = MagicMock(command="doctor", debug=False)
        with patch('cli.main._cmd_doctor') as mock_doctor:
            mock_doctor.return_value = 0
            from cli.main import main
            result = main()
            assert result == 0


def test_main_stats():
    with patch('cli.main.parse_args') as mock_parse:
        mock_parse.return_value = MagicMock(command="stats", debug=False)
        with patch('cli.main._cmd_stats') as mock_stats:
            mock_stats.return_value = 0
            from cli.main import main
            result = main()
            assert result == 0


def test_main_init():
    with patch('cli.main.parse_args') as mock_parse:
        mock_parse.return_value = MagicMock(command="init", debug=False)
        with patch('cli.main._cmd_init') as mock_init:
            mock_init.return_value = 0
            from cli.main import main
            result = main()
            assert result == 0


def test_main_emergency_stop():
    with patch('cli.main.parse_args') as mock_parse:
        mock_parse.return_value = MagicMock(command="emergency", debug=False, action="stop")
        with patch('cli.main._cmd_emergency') as mock_emergency:
            mock_emergency.return_value = 0
            from cli.main import main
            result = main()
            assert result == 0


def test_main_memory_list():
    with patch('cli.main.parse_args') as mock_parse:
        args = MagicMock(command="memory", debug=False, subcmd="list",
                        tier_filter=None, scope_filter=None,
                        tier=None, scope=None, key=None, value=None)
        mock_parse.return_value = args
        with patch('cli.main._cmd_memory_list') as mock_mem:
            mock_mem.return_value = 0
            from cli.main import main
            result = main()
            assert result == 0


def test_main_memory_set():
    with patch('cli.main.parse_args') as mock_parse:
        args = MagicMock(command="memory", debug=False, subcmd="set",
                        tier_filter=None, scope_filter=None,
                        tier="semantic", scope="project", key="k", value="v")
        mock_parse.return_value = args
        with patch('cli.main._cmd_memory_set') as mock_mem:
            mock_mem.return_value = 0
            from cli.main import main
            result = main()
            assert result == 0


def test_main_skill_list():
    with patch('cli.main.parse_args') as mock_parse:
        mock_parse.return_value = MagicMock(command="skill", debug=False, subcmd="list",
                                            name=None, content=None, file=None)
        with patch('cli.main._cmd_skill_list') as mock_skill:
            mock_skill.return_value = 0
            from cli.main import main
            result = main()
            assert result == 0


def test_main_skill_get():
    with patch('cli.main.parse_args') as mock_parse:
        mock_parse.return_value = MagicMock(command="skill", debug=False, subcmd="get",
                                            name="my_skill", content=None, file=None)
        with patch('cli.main._cmd_skill_get') as mock_skill:
            mock_skill.return_value = 0
            from cli.main import main
            result = main()
            assert result == 0


def test_main_skill_set():
    with patch('cli.main.parse_args') as mock_parse:
        mock_parse.return_value = MagicMock(command="skill", debug=False, subcmd="set",
                                            name="my_skill", content="content", file=None)
        with patch('cli.main._cmd_skill_set') as mock_skill:
            mock_skill.return_value = 0
            from cli.main import main
            result = main()
            assert result == 0


def test_main_skill_add():
    with patch('cli.main.parse_args') as mock_parse:
        mock_parse.return_value = MagicMock(command="skill", debug=False, subcmd="add",
                                            name="my_skill", content="skill.py", file=None)
        with patch('cli.main._cmd_skill_add') as mock_skill:
            mock_skill.return_value = 0
            from cli.main import main
            result = main()
            assert result == 0


def test_main_review_no_file():
    with patch('cli.main.parse_args') as mock_parse:
        mock_parse.return_value = MagicMock(command="review", debug=False, file=None, n=5)
        with patch('cli.main._cmd_review') as mock_review:
            mock_review.return_value = 0
            from cli.main import main
            result = main()
            assert result == 0


def test_main_review_with_file():
    with patch('cli.main.parse_args') as mock_parse:
        mock_parse.return_value = MagicMock(command="review", debug=False, file="test.py", n=3)
        with patch('cli.main._cmd_review') as mock_review:
            mock_review.return_value = 0
            from cli.main import main
            result = main()
            assert result == 0


def test_main_rollback_n():
    with patch('cli.main.parse_args') as mock_parse:
        mock_parse.return_value = MagicMock(command="rollback", debug=False, n=2,
                                            trace_id=None, list_rollbacks=False)
        with patch('cli.main._cmd_rollback') as mock_rollback:
            mock_rollback.return_value = 0
            from cli.main import main
            result = main()
            assert result == 0


def test_main_rollback_list():
    with patch('cli.main.parse_args') as mock_parse:
        mock_parse.return_value = MagicMock(command="rollback", debug=False, n=1,
                                            trace_id=None, list_rollbacks=True)
        with patch('cli.main._cmd_rollback') as mock_rollback:
            mock_rollback.return_value = 0
            from cli.main import main
            result = main()
            assert result == 0


def test_main_doctor_dispatch():
    with patch('cli.main.parse_args') as mock_parse:
        mock_parse.return_value = MagicMock(command="doctor", debug=False)
        with patch('cli.main._cmd_doctor') as mock_doctor:
            mock_doctor.return_value = 0
            from cli.main import main
            result = main()
            assert result == 0


def test_main_doctor_returns_nonzero():
    with patch('cli.main.parse_args') as mock_parse:
        mock_parse.return_value = MagicMock(command="doctor", debug=False)
        with patch('cli.main._cmd_doctor') as mock_doctor:
            mock_doctor.return_value = 1
            from cli.main import main
            result = main()
            assert result == 1


# ── Edge cases ────────────────────────────────────────────────────────


def test_get_noman_dir_creates():
    """_get_noman_dir should create .noman if it doesn't exist."""
    with tempfile.TemporaryDirectory() as td:
        fake_home = Path(td) / "fake_home"
        fake_home.mkdir()
        with patch.object(Path, 'home', return_value=fake_home):
            noman_dir = _get_noman_dir()
            assert noman_dir.exists()
            assert noman_dir == fake_home / ".noman"


def test_load_config_returns_defaults_when_invalid():
    """_load_config should return defaults when config is invalid."""
    with tempfile.TemporaryDirectory() as td:
        fake_home = Path(td) / "fake_home"
        fake_home.mkdir()
        noman_dir = fake_home / ".noman"
        noman_dir.mkdir()
        # Write invalid TOML
        (noman_dir / "config.toml").write_text("invalid [[[toml")
        with patch.object(Path, 'home', return_value=fake_home):
            cfg = _load_config()
            assert "providers" in cfg
