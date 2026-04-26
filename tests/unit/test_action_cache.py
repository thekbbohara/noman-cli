"""Tests for core/utils/action_cache.py — Action cache."""

import pytest

from core.utils.action_cache import ActionCache, _make_key


# ── _make_key ────────────────────────────────────────────────────────

def test_make_key_deterministic():
    k1 = _make_key("read_file", ("path.py",), {})
    k2 = _make_key("read_file", ("path.py",), {})
    assert k1 == k2


def test_make_key_different_tools():
    k1 = _make_key("read_file", ("a.py",), {})
    k2 = _make_key("edit_file", ("a.py",), {})
    assert k1 != k2


def test_make_key_different_args():
    k1 = _make_key("read_file", ("a.py",), {})
    k2 = _make_key("read_file", ("b.py",), {})
    assert k1 != k2


# ── ActionCache ──────────────────────────────────────────────────────

def test_get_set():
    cache = ActionCache()
    cache.set("read_file", "file content", args=("a.py",))
    result = cache.get("read_file", args=("a.py",))
    assert result == "file content"


def test_get_miss():
    cache = ActionCache()
    with pytest.raises(KeyError):
        cache.get("read_file", args=("a.py",))
    assert cache.misses == 1


def test_get_different_args_miss():
    cache = ActionCache()
    cache.set("read_file", "content", args=("a.py",))
    with pytest.raises(KeyError):
        cache.get("read_file", args=("b.py",))


def test_hits_misses_counting():
    cache = ActionCache()
    cache.set("tool", "result", args=("x",))
    cache.get("tool", args=("x",))  # hit
    cache.get("tool", args=("x",))  # hit
    with pytest.raises(KeyError):
        cache.get("tool", args=("y",))  # miss
    assert cache.hits == 2
    assert cache.misses == 1


def test_summary():
    cache = ActionCache()
    cache.set("tool", "result", args=("x",))
    cache.get("tool", args=("x",))  # hit
    summary = cache.summary()
    assert summary["hits"] == 1
    assert summary["misses"] == 0
    assert summary["hit_rate"] == 1.0


def test_summary_with_misses():
    cache = ActionCache()
    with pytest.raises(KeyError):
        cache.get("tool", args=("x",))  # miss
    summary = cache.summary()
    assert summary["misses"] == 1
    assert summary["hit_rate"] == 0.0


def test_clear():
    cache = ActionCache()
    cache.set("tool", "result", args=("x",))
    cache.get("tool", args=("x",))  # hit
    cache.clear()
    assert cache._store == {}
    assert cache.hits == 0
    assert cache.misses == 0


def test_invalidate():
    """invalidate should correctly remove entries by tool name."""
    cache = ActionCache()
    cache.set("read_file", "content", args=("a.py",))
    cache.set("read_file", "content2", args=("b.py",))
    cache.set("edit_file", "patch", args=("a.py",))
    cache.invalidate("read_file")
    assert len(cache._store) == 1
    assert cache.get("edit_file", args=("a.py",)) == "patch"


def test_kwargs_in_key():
    cache = ActionCache()
    cache.set("tool", "result", kwargs={"key": "val"})
    result = cache.get("tool", kwargs={"key": "val"})
    assert result == "result"
