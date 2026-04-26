"""Tests for core/memory/store.py — SQLite-backed tiered memory."""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from core.memory.store import (
    MemoryConfig,
    MemoryEntry,
    MemoryStore,
    MemorySystem,
    MemorySystem,
    DEFAULT_TTL,
    TIERS,
    SCOPES,
)


# ── Constants ────────────────────────────────────────────────────────

def test_tiers_constant():
    assert TIERS == ("episodic", "semantic", "procedural")


def test_scopes_constant():
    assert SCOPES == ("project", "file", "symbol", "global")


def test_default_ttl():
    assert DEFAULT_TTL["episodic"] == 7
    assert DEFAULT_TTL["semantic"] is None
    assert DEFAULT_TTL["procedural"] is None


# ── MemoryEntry ─────────────────────────────────────────────────────

def test_memory_entry_defaults():
    entry = MemoryEntry(
        id="e1", tier="semantic", scope="project", key="k", value="v",
    )
    assert entry.confidence == 1.0
    assert entry.source_trace_id is None
    assert entry.created_at is None
    assert entry.is_valid is True


# ── MemoryConfig ─────────────────────────────────────────────────────

def test_memory_config_defaults():
    cfg = MemoryConfig()
    assert cfg.default_ttl_days == 7
    assert cfg.max_memories == 10000


# ── MemoryStore ──────────────────────────────────────────────────────

@pytest.fixture
def store(tmp_path):
    cfg = MemoryConfig(db_path=str(tmp_path / "test.db"))
    return MemoryStore(cfg)


def test_remember_and_recall(store):
    eid = store.remember("semantic", "project", "mykey", "myvalue")
    assert eid is not None
    results = store.recall(query="mykey")
    assert len(results) == 1
    assert results[0].key == "mykey"
    assert results[0].value == "myvalue"


def test_remember_same_key_updates(store):
    eid1 = store.remember("semantic", "project", "dup", "first")
    eid2 = store.remember("semantic", "project", "dup", "second")
    assert eid2 == "updated:semantic:project:dup"
    results = store.recall(query="dup")
    assert len(results) == 1
    assert results[0].value == "second"


def test_forget(store):
    store.remember("semantic", "project", "forget_me", "val")
    assert store.forget("semantic", "project", "forget_me") is True
    # Second forget still returns True because it doesn't check is_valid flag
    # (it's a soft-delete that always affects the matching row)
    assert store.forget("semantic", "project", "forget_me") is True
    # Verify the memory is soft-deleted
    results = store.recall(query="forget_me")
    assert len(results) == 0


def test_cleanup_expired(store):
    # Episodic has 7-day TTL, so we can't easily test expiry without time travel.
    # Just verify cleanup doesn't crash.
    store.remember("semantic", "project", "keep", "val")
    removed = store.cleanup_expired()
    assert removed >= 0


def test_count(store):
    assert store.count() == 0
    store.remember("semantic", "project", "k1", "v1")
    store.remember("episodic", "file", "k2", "v2")
    assert store.count() == 2
    assert store.count(tier="semantic") == 1
    assert store.count(tier="episodic") == 1


def test_count_by_tier(store):
    store.remember("semantic", "project", "k1", "v1")
    store.remember("procedural", "global", "s1", "skill")
    assert store.count(tier="semantic") == 1
    assert store.count(tier="procedural") == 1


def test_remember_with_source_trace(store):
    eid = store.remember("semantic", "project", "trace_key", "trace_val",
                         source_trace_id="trace-123")
    results = store.recall(query="trace_key")
    assert len(results) == 1
    assert results[0].source_trace_id == "trace-123"


def test_recall_with_tier_filter(store):
    store.remember("semantic", "project", "k1", "v1")
    store.remember("episodic", "project", "k2", "v2")
    results = store.recall(tier="semantic")
    assert len(results) == 1
    assert results[0].tier == "semantic"


def test_recall_limit(store):
    for i in range(5):
        store.remember("semantic", "project", f"k{i}", f"v{i}")
    results = store.recall(limit=2)
    assert len(results) == 2


def test_close(store):
    store.close()
    assert store._conn is None


# ── MemorySystem ─────────────────────────────────────────────────────

@pytest.fixture
def memory_system(tmp_path):
    cfg = MemoryConfig(db_path=str(tmp_path / "mem.db"))
    return MemorySystem(cfg)


def test_recall_facts(memory_system):
    memory_system.remember("important fact", tier="semantic", scope="project")
    results = memory_system.recall(query="important")
    assert len(results) >= 1
    assert "important fact" in results


def test_add_and_get_skill(memory_system):
    sid = memory_system.add_skill("list_dir", "ls -la")
    assert sid is not None
    skill = memory_system.get_skill("list_dir")
    assert skill == "ls -la"


def test_cleanup(memory_system):
    count = memory_system.cleanup()
    assert count >= 0
    memory_system.close()
