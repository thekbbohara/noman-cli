"""Tests for core/context/manager.py — Context management."""

import tempfile
from pathlib import Path

from core.context.manager import (
    ContextManager,
    ContextView,
    SkeletonCache,
    SkeletonFile,
    SymbolIndex,
    SymbolSkeleton,
)

# ── SkeletonCache ────────────────────────────────────────────────────

def test_skeleton_cache_get_set():
    cache = SkeletonCache()
    sf = SkeletonFile(file_path="test.py", mtime=1.0)
    cache.set("test.py", sf)
    assert cache.get("test.py") is sf
    assert cache.get("missing.py") is None


def test_skeleton_cache_invalidate():
    cache = SkeletonCache()
    sf = SkeletonFile(file_path="test.py", mtime=1.0)
    cache.set("test.py", sf)
    cache.invalidate("test.py")
    assert cache.get("test.py") is None


def test_skeleton_cache_clear():
    cache = SkeletonCache()
    cache.set("a.py", SkeletonFile(file_path="a.py", mtime=1.0))
    cache.set("b.py", SkeletonFile(file_path="b.py", mtime=2.0))
    cache.clear()
    assert cache.get("a.py") is None
    assert cache.get("b.py") is None


# ── SymbolIndex ──────────────────────────────────────────────────────

def test_symbol_index_top_n():
    syms = [
        SymbolSkeleton(name=f"sym{i}", kind="function", file_path="x.py",
                       signature=f"def sym{i}()", line_number=i)
        for i in range(10)
    ]
    idx = SymbolIndex(symbols=syms)
    top = idx.top_n(3)
    assert len(top) == 3


def test_symbol_index_by_file():
    syms = [
        SymbolSkeleton(name="foo", kind="function", file_path="a.py",
                       signature="def foo()", line_number=1),
        SymbolSkeleton(name="bar", kind="function", file_path="a.py",
                       signature="def bar()", line_number=2),
        SymbolSkeleton(name="baz", kind="function", file_path="b.py",
                       signature="def baz()", line_number=1),
    ]
    idx = SymbolIndex(symbols=syms)
    a_syms = idx.by_file("a.py")
    assert len(a_syms) == 2
    assert all(s.kind == "function" for s in a_syms)


def test_symbol_index_top_n_exceeds():
    syms = [
        SymbolSkeleton(name=f"s{i}", kind="class", file_path="x.py",
                       signature=f"class S{i}()", line_number=i)
        for i in range(3)
    ]
    idx = SymbolIndex(symbols=syms)
    top = idx.top_n(100)
    assert len(top) == 3


# ── ContextView ──────────────────────────────────────────────────────

def test_context_view_truncated_to():
    cv = ContextView(skeleton=[SymbolSkeleton(name="x", kind="function",
                  file_path="a.py", signature="def x()", line_number=1)] * 100,
                  token_count=500, budget=1000)
    truncated = cv.truncated_to(50)
    assert truncated.token_count <= 50
    assert len(truncated.skeleton) <= 10


def test_context_view_fit_budget():
    cv = ContextView(skeleton=[SymbolSkeleton(name="x", kind="function",
                  file_path="a.py", signature="def x()", line_number=1)],
                  token_count=5, budget=100)
    truncated = cv.truncated_to(50)
    assert truncated.token_count == 5


# ── ContextManager ───────────────────────────────────────────────────

def test_context_manager_index_repo():
    with tempfile.TemporaryDirectory() as tmp:
        # Create a sample Python file
        src_dir = Path(tmp) / "src"
        src_dir.mkdir()
        (src_dir / "sample.py").write_text("""
class MyClass:
    def method_one(self):
        pass

CONSTANT = 42

def standalone():
    pass
""")
        cm = ContextManager(tmp)
        cm.index_repo([".py"])
        assert len(cm.symbol_index.symbols) >= 3  # class, method, constant, function


def test_context_manager_read_lines():
    with tempfile.TemporaryDirectory() as tmp:
        src_dir = Path(tmp) / "src"
        src_dir.mkdir()
        fpath = src_dir / "hello.py"
        fpath.write_text("line1\nline2\nline3\nline4\nline5\n")
        cm = ContextManager(tmp)
        result = cm.read_lines("src/hello.py", start=2, end=4)
        assert "line2" in result
        assert "line4" in result
        assert "line1" not in result


def test_context_manager_read_lines_cached():
    with tempfile.TemporaryDirectory() as tmp:
        src_dir = Path(tmp) / "src"
        src_dir.mkdir()
        fpath = src_dir / "cached.py"
        fpath.write_text("hello\nworld\n")
        cm = ContextManager(tmp)
        r1 = cm.read_lines("src/cached.py", start=1, end=2)
        r2 = cm.read_lines("src/cached.py", start=1, end=2)
        assert r1 == r2


def test_context_manager_invalidate():
    with tempfile.TemporaryDirectory() as tmp:
        src_dir = Path(tmp) / "src"
        src_dir.mkdir()
        fpath = src_dir / "inv.py"
        fpath.write_text("old content\n")
        cm = ContextManager(tmp)
        cm.read_lines("src/inv.py", start=1)
        cm.invalidate("src/inv.py")
        # Write new content
        fpath.write_text("new content\n")
        result = cm.read_lines("src/inv.py", start=1)
        assert "new content" in result


def test_context_manager_get_context():
    with tempfile.TemporaryDirectory() as tmp:
        src_dir = Path(tmp) / "src"
        src_dir.mkdir()
        (src_dir / "sample.py").write_text("def foo(): pass\n")
        cm = ContextManager(tmp)
        cm.index_repo([".py"])
        ctx = cm.get_context(budget=50)
        assert isinstance(ctx, ContextView)
        assert ctx.budget == 50


def test_context_manager_read_symbol():
    with tempfile.TemporaryDirectory() as tmp:
        src_dir = Path(tmp) / "src"
        src_dir.mkdir()
        (src_dir / "sym.py").write_text(
            "class MyClass:\n    def method_one(self):\n        pass\n\nCONSTANT = 42\n"
        )
        cm = ContextManager(tmp)
        cm.index_repo([".py"])
        result = cm.read_symbol("method_one", "src/sym.py")
        assert result is not None
        assert "method_one" in result
