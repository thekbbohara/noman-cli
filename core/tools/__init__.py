"""Core tools — 35 tools registered on the ToolBus."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from core.security.fs_sandbox import FilesystemSandbox
from core.tools.bus import Tool, ToolBus

EDIT_HISTORY: list[dict] = []


def clear_edit_history() -> None:
    """Clear edit history."""
    EDIT_HISTORY.clear()


def _s(schema: dict) -> dict:
    """Shorthand JSON Schema builder."""
    return schema


# ── Schema definitions ────────────────────────────────────────────────────────

SCHEMA_PATH: dict = _s({
    "type": "object",
    "properties": {"path": {"type": "string"}},
    "required": ["path"],
})

SCHEMA_COMMAND: dict = _s({
    "type": "object",
    "properties": {"command": {"type": "string"}},
    "required": ["command"],
})

SCHEMA_PATTERN: dict = _s({
    "type": "object",
    "properties": {
        "pattern": {"type": "string"},
        "path": {"type": "string", "default": "."},
    },
    "required": ["pattern"],
})

SCHEMA_GLOB: dict = _s({
    "type": "object",
    "properties": {
        "pattern": {"type": "string"},
        "path": {"type": "string", "default": "."},
    },
    "required": ["pattern"],
})

SCHEMA_FIND: dict = _s({
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "path": {"type": "string", "default": "."},
    },
    "required": ["name"],
})

SCHEMA_WRITE: dict = _s({
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "content": {"type": "string"},
    },
    "required": ["path", "content"],
})

SCHEMA_APPEND: dict = _s({
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "content": {"type": "string"},
    },
    "required": ["path", "content"],
})

SCHEMA_MKDIR: dict = _s({
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "parents": {"type": "boolean", "default": False},
    },
    "required": ["path"],
})

SCHEMA_COPY: dict = _s({
    "type": "object",
    "properties": {
        "src": {"type": "string"},
        "dst": {"type": "string"},
    },
    "required": ["src", "dst"],
})

SCHEMA_MOVE: dict = _s({
    "type": "object",
    "properties": {
        "src": {"type": "string"},
        "dst": {"type": "string"},
    },
    "required": ["src", "dst"],
})

SCHEMA_DELETE: dict = _s({
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "recursive": {"type": "boolean", "default": False},
    },
    "required": ["path"],
})

SCHEMA_ENV: dict = _s({
    "type": "object",
    "properties": {"key": {"type": "string"}},
    "required": ["key"],
})

SCHEMA_SETENV: dict = _s({
    "type": "object",
    "properties": {
        "key": {"type": "string"},
        "value": {"type": "string"},
    },
    "required": ["key", "value"],
})

SCHEMA_PS: dict = _s({
    "type": "object",
    "properties": {"user": {"type": "string", "default": ""}},
})

SCHEMA_KILL: dict = _s({
    "type": "object",
    "properties": {"pid": {"type": "integer"}},
    "required": ["pid"],
})

SCHEMA_DOCKER: dict = _s({
    "type": "object",
    "properties": {"container": {"type": "string"}},
    "required": ["container"],
})

SCHEMA_DOCKER_EXEC: dict = _s({
    "type": "object",
    "properties": {
        "container": {"type": "string"},
        "command": {"type": "string"},
    },
    "required": ["container", "command"],
})

SCHEMA_RUN_TESTS: dict = _s({
    "type": "object",
    "properties": {
        "path": {"type": "string", "default": "."},
        "pattern": {"type": "string", "default": "test"},
        "verbose": {"type": "boolean", "default": False},
    },
})

SCHEMA_EXPLAIN: dict = _s({
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "name": {"type": "string"},
        "symbol": {"type": "string"},
    },
})

SCHEMA_MEM_SEARCH: dict = _s({
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "tier": {"type": "string", "default": ""},
        "limit": {"type": "integer", "default": 5},
    },
})

SCHEMA_SKILL: dict = _s({
    "type": "object",
    "properties": {"name": {"type": "string"}},
})

SCHEMA_GIT_REPO: dict = _s({
    "type": "object",
    "properties": {"repo_path": {"type": "string", "default": "."}},
})

SCHEMA_GIT_PUSH: dict = _s({
    "type": "object",
    "properties": {
        "remote": {"type": "string", "default": "origin"},
        "branch": {"type": "string"},
        "repo_path": {"type": "string", "default": "."},
    },
})

SCHEMA_GIT_RESET: dict = _s({
    "type": "object",
    "properties": {
        "target": {"type": "string"},
        "hard": {"type": "boolean", "default": False},
        "repo_path": {"type": "string", "default": "."},
    },
    "required": ["target"],
})

SCHEMA_GIT_DELETE: dict = _s({
    "type": "object",
    "properties": {
        "branch": {"type": "string"},
        "force": {"type": "boolean", "default": False},
        "repo_path": {"type": "string", "default": "."},
    },
    "required": ["branch"],
})

SCHEMA_READ: dict = _s({
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "lines": {"type": "integer", "default": 100},
    },
    "required": ["path"],
})

SCHEMA_FIND_SYM: dict = _s({
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "path": {"type": "string", "default": "."},
    },
    "required": ["query"],
})

SCHEMA_FIND_REF: dict = _s({
    "type": "object",
    "properties": {
        "symbol": {"type": "string"},
        "path": {"type": "string", "default": "."},
    },
    "required": ["symbol"],
})

SCHEMA_TREE: dict = _s({
    "type": "object",
    "properties": {
        "path": {"type": "string", "default": "."},
        "max_depth": {"type": "integer", "default": 3},
    },
})

SCHEMA_EMPTY: dict = _s({"type": "object", "properties": {}})

SCHEMA_PREVIEW: dict = _s({
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "new_content": {"type": "string"},
    },
    "required": ["path", "new_content"],
})

SCHEMA_EDIT: dict = _s({
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "old_content": {"type": "string"},
        "new_content": {"type": "string"},
    },
    "required": ["path", "old_content", "new_content"],
})

SCHEMA_SYMBOL_QUERY: dict = _s({
    "type": "object",
    "properties": {
        "query": {"type": "string"},
    },
    "required": ["query"],
})


# ── Handlers ──────────────────────────────────────────────────────────────────

def run_shell(command: str, cwd: str | None = None) -> str:
    result = subprocess.run(
        command, shell=True, capture_output=True, text=True, timeout=30,
        cwd=cwd or os.getcwd(),
    )
    return result.stdout or result.stderr or ""


def list_dir(path: str = ".") -> str:
    try:
        return "\n".join(os.listdir(path))
    except FileNotFoundError:
        return f"Directory not found: {path}"
    except PermissionError:
        return f"Permission denied: {path}"


def read_file(path: str, lines: int = 100) -> str:
    try:
        with open(path) as f:
            return "".join(f.readlines()[:lines])
    except FileNotFoundError:
        return f"File not found: {path}"
    except PermissionError:
        return f"Permission denied: {path}"


def search_code(pattern: str, path: str = ".") -> str:
    result = subprocess.run(
        ["grep", "-r", pattern, path], capture_output=True, text=True,
    )
    return result.stdout or "No matches found"


def glob_files(pattern: str, path: str = ".") -> str:
    matches = list(Path(path).glob(pattern))
    if not matches:
        return f"No matches for {pattern} in {path}"
    return "\n".join(str(m) for m in matches)


def find_files(name: str, path: str = ".") -> str:
    result = subprocess.run(
        ["find", path, "-name", name, "-type", "f"],
        capture_output=True, text=True,
    )
    return result.stdout or f"No files named '{name}' in {path}"


def write_file(path: str, content: str) -> str:
    p = Path(path).resolve()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return f"Written {len(content)} chars to {path}"
    except PermissionError:
        return f"Permission denied: {path}"
    except OSError as e:
        return f"Error writing {path}: {e}"


def append_file(path: str, content: str) -> str:
    p = Path(path).resolve()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.open("a").write(content)
        return f"Appended {len(content)} chars to {path}"
    except FileNotFoundError:
        return write_file(path, content)
    except PermissionError:
        return f"Permission denied: {path}"


def diff_preview(path: str, new_content: str) -> str:
    """Show unified diff between current file and new content."""
    from difflib import unified_diff
    p = Path(path)
    if not p.exists():
        return f"File not found: {path}"

    current_lines = p.read_text().splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)

    diff = list(unified_diff(
        current_lines, new_lines,
        fromfile=str(path), tofile=str(path),
        lineterm=""
    ))

    if not diff:
        return "No changes"

    return "\n".join(diff)


def edit_file(path: str, old_content: str, new_content: str) -> str:
    """Replace old_content with new_content in file."""
    p = Path(path).resolve()
    if not p.exists():
        return f"File not found: {path}"

    current = p.read_text()
    count = current.count(old_content)
    if count == 0:
        return f"Old content not found in {path}"
    if count > 1:
        return f"Found {count} occurrences - use replace_all for multiple replacements"

    updated = current.replace(old_content, new_content)

    try:
        p.write_text(updated)
        EDIT_HISTORY.append({
            "path": str(p),
            "old": old_content,
            "new": new_content,
        })
    except Exception:
        raise

    return f"Applied change to {path}"


def mkdir_tool(path: str, parents: bool = False) -> str:
    p = Path(path)
    try:
        if parents:
            p.mkdir(parents=True, exist_ok=True)
        else:
            p.mkdir()
        return f"Created directory: {path}"
    except FileExistsError:
        return f"Already exists: {path}"
    except PermissionError:
        return f"Permission denied: {path}"


def copy_file(src: str, dst: str) -> str:
    import shutil
    try:
        shutil.copy2(Path(src).resolve(), Path(dst).resolve())
        return f"Copied {src} -> {dst}"
    except FileNotFoundError:
        return f"Source not found: {src}"
    except PermissionError:
        return "Permission denied"
    except OSError as e:
        return f"Error copying: {e}"


def move_file(src: str, dst: str) -> str:
    import shutil
    try:
        shutil.move(src, dst)
        return f"Moved {src} -> {dst}"
    except FileNotFoundError:
        return f"Source not found: {src}"
    except PermissionError:
        return "Permission denied"
    except OSError as e:
        return f"Error moving: {e}"


def delete_file(path: str, recursive: bool = False) -> str:
    p = Path(path)
    try:
        if p.is_dir():
            if recursive:
                import shutil
                shutil.rmtree(p)
            else:
                p.rmdir()
        else:
            p.unlink()
        return f"Deleted: {path}"
    except FileNotFoundError:
        return f"Not found: {path}"
    except PermissionError:
        return f"Permission denied: {path}"
    except OSError as e:
        return f"Error deleting: {e}"


def path_exists(path: str) -> str:
    return "exists" if Path(path).exists() else "not found"


def path_type(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return "not found"
    if p.is_symlink():
        return "symlink"
    if p.is_dir():
        return "directory"
    if p.is_file():
        return "file"
    return "unknown"


def git_status(repo_path: str = ".") -> str:
    from core.tools.git import SafeGitOperations
    return SafeGitOperations(repo_path).status()


def git_current_branch(repo_path: str = ".") -> str:
    from core.tools.git import SafeGitOperations
    return SafeGitOperations(repo_path).current_branch()


def git_push(remote: str = "origin", branch: str | None = None,
              repo_path: str = ".") -> str:
    from core.errors import SandboxViolation
    from core.tools.git import SafeGitOperations
    git = SafeGitOperations(repo_path)
    try:
        git.push(remote=remote, branch=branch)
        return f"Pushed to {remote}/{branch or 'current'}"
    except SandboxViolation as e:
        return f"Blocked: {e}"


def git_reset(target: str, hard: bool = False, repo_path: str = ".") -> str:
    from core.errors import SandboxViolation
    from core.tools.git import SafeGitOperations
    git = SafeGitOperations(repo_path)
    try:
        git.reset(target, hard=hard)
        return f"Reset to {target} (hard={hard})"
    except SandboxViolation as e:
        return f"Blocked: {e}"


def git_delete_branch(branch: str, force: bool = False,
                      repo_path: str = ".") -> str:
    from core.errors import SandboxViolation
    from core.tools.git import SafeGitOperations
    git = SafeGitOperations(repo_path)
    try:
        git.delete_branch(branch, force=force)
        return f"Deleted branch: {branch}"
    except SandboxViolation as e:
        return f"Blocked: {e}"


def get_env(key: str) -> str:
    val = os.environ.get(key, "")
    return f"{key}={val}" if val else f"ENV {key} not set"


def set_env(key: str, value: str) -> str:
    os.environ[key] = value
    return f"Set {key}={value}"


def list_processes(user: str = "") -> str:
    cmd = ["ps", "aux"]
    if user:
        cmd.extend(["-u", user])
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout or "No processes found"


def kill_process(pid: int) -> str:
    try:
        import signal
        os.kill(pid, signal.SIGTERM)
        return f"Sent SIGTERM to {pid}"
    except PermissionError:
        return f"Permission denied for PID {pid}"
    except ProcessLookupError:
        return f"PID {pid} not found"
    except OSError as e:
        return f"Error killing PID {pid}: {e}"


def docker_ps() -> str:
    result = subprocess.run(["docker", "ps"], capture_output=True, text=True)
    return result.stdout or result.stderr or "docker not available"


def docker_logs(container: str) -> str:
    result = subprocess.run(
        ["docker", "logs", "--tail", "50", container],
        capture_output=True, text=True,
    )
    return result.stdout or result.stderr or f"Container '{container}' not found"


def docker_exec(container: str, command: str) -> str:
    result = subprocess.run(
        ["docker", "exec", container, "sh", "-c", command],
        capture_output=True, text=True,
    )
    return result.stdout or result.stderr or f"Failed: {command} in {container}"


def run_tests(path: str = ".", pattern: str = "test",
              verbose: bool = False) -> str:
    import sys

    import pytest
    args = [path, "-k", pattern, "-v" if verbose else "-q"]
    old_out, old_err = sys.stdout, sys.stderr
    with open(os.devnull, "w") as devnull:
        sys.stdout, sys.stderr = devnull, devnull
        try:
            pytest.main(args)
        finally:
            sys.stdout, sys.stderr = old_out, old_err
    return f"Test run complete for {path} (pattern={pattern})"


def explain_code(path: str = "", name: str = "", symbol: str = "") -> str:
    from core.context import ContextManager
    ctx = ContextManager(Path.cwd())
    if symbol and name:
        return ctx.read_symbol(symbol, name) or f"Symbol {symbol} not found in {name}"
    if path:
        return ctx.read_lines(path) or f"Could not read {path}"
    return "Usage: explain_code path=<file> name=<file> symbol=<name>"


def find_symbol(query: str, path: str = ".") -> str:
    results = []
    for ext in (".py", ".ts", ".js", ".go", ".rs"):
        for f in Path(path).rglob(f"*{ext}"):
            try:
                for i, line in enumerate(f.read_text(errors="ignore").split("\n"), 1):
                    stripped = line.strip()
                    if stripped.startswith("def ") or stripped.startswith("class "):
                        if query.lower() in line.lower():
                            results.append(f"{f}:{i}: {line.strip()}")
            except Exception:
                pass
    return "\n".join(results) if results else f"No symbols matching '{query}'"


def find_definition(symbol: str) -> str:
    """Find where a symbol is defined. Searches for def/class/const patterns."""
    pattern = rf"^(def|class|const|async def)\s+{re.escape(symbol)}\s*[\(=]"
    matches = []
    for py_file in Path(".").rglob("*.py"):
        try:
            content = py_file.read_text()
            for i, line in enumerate(content.splitlines(), 1):
                if re.search(pattern, line):
                    matches.append(f"{py_file}:{i}: {line.strip()}")
        except Exception:
            continue
    return "\n".join(matches) if matches else f"Symbol '{symbol}' not found"


def find_references(symbol: str) -> list[str]:
    """Find files that reference a symbol."""
    pattern = rf"\b{re.escape(symbol)}\b"
    files = []
    for py_file in Path(".").rglob("*.py"):
        try:
            if pattern in py_file.read_text():
                files.append(str(py_file))
        except Exception:
            continue
    return files


def search_symbols(query: str) -> str:
    """Search for symbols by name pattern."""
    pattern = rf"^(def|class|async def)\s+{re.escape(query)}"
    matches = []
    for py_file in Path(".").rglob("*.py"):
        try:
            content = py_file.read_text()
            for i, line in enumerate(content.splitlines(), 1):
                if re.search(pattern, line, re.IGNORECASE):
                    matches.append(f"{py_file}:{i}: {line.strip()}")
        except Exception:
            continue
    return "\n".join(matches) if matches else f"No symbols matching '{query}'"


def get_file_tree(path: str = ".", max_depth: int = 3) -> str:
    import io
    buf = io.StringIO()

    def walk(p: Path, prefix: str = "", depth: int = 0) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name))
            for i, entry in enumerate(entries):
                last = i == len(entries) - 1
                buf.write(f"{prefix}{'└── ' if last else '├── '}{entry.name}\n")
                if entry.is_dir() and not entry.is_symlink():
                    walk(entry, prefix + ("    " if last else "│   "), depth + 1)
        except PermissionError:
            buf.write(f"{prefix}(permission denied)\n")

    walk(Path(path))
    return buf.getvalue()


def list_imports(path: str) -> str:
    result = subprocess.run(
        ["grep", "-E", r"^import |^from ", path],
        capture_output=True, text=True,
    )
    return result.stdout or f"No imports in {path}"


def memory_search(query: str = "", tier: str = "", limit: int = 5) -> str:
    from core.memory import MemorySystem
    mem = MemorySystem()
    try:
        results = mem.recall(query, tier=tier or None, limit=limit)
        if not results:
            return f"No memories matching '{query}'"
        return "\n".join(results)
    finally:
        mem.close()


def skill_list() -> str:
    from core.memory import MemorySystem
    mem = MemorySystem()
    try:
        entries = mem._store.recall(tier="procedural", scope="global", limit=100)
        return "\n".join(f"- {e.key}" for e in entries) if entries else "No skills loaded"
    finally:
        mem.close()


def skill_match(task: str, max_results: int = 5) -> str:
    """Find the most relevant skills for a task using BM25 + semantic matching."""
    from core.selfimprove.skill_loader import get_skill_loader
    loader = get_skill_loader()
    candidates = loader.match_skills(task, max_results=max_results)
    return loader.format_match_results(candidates)


def skill_load(name: str) -> str:
    """Load a skill into context (with dependency resolution + budget check)."""
    from core.selfimprove.skill_loader import get_skill_loader
    loader = get_skill_loader()
    return loader.load_skill_by_name(name)


def skill_load_all(task: str = "", max_skills: int = 3, max_tokens: int = 4000) -> str:
    """Auto-load the most relevant skills for the current task."""
    from core.selfimprove.skill_loader import get_skill_loader
    loader = get_skill_loader()
    
    if not task:
        skills_list_result = skill_list()
        return (
            f"=== Available Skills ===\n{skills_list_result}\n\n"
            f"Use skill_match(task) to find relevant skills.\n"
            f"Use skill_load(name) to load a specific skill."
        )
    
    result = loader.load_all_relevant(task, max_skills=max_skills, max_tokens=max_tokens)
    
    lines = []
    if result.auto_loaded:
        lines.append(f"Auto-loaded {len(result.auto_loaded)} skill(s):")
        for sid in result.auto_loaded:
            lines.append(f"  ✓ {sid}")
    if result.skipped_low_relevance:
        lines.append(f"\nSkipped (low relevance): {', '.join(result.skipped_low_relevance)}")
    if result.skipped_budget:
        lines.append(f"\nSkipped (budget): {', '.join(result.skipped_budget)}")
    if result.errors:
        lines.append(f"\nErrors:")
        for err in result.errors:
            lines.append(f"  ✗ {err}")
    if not result.auto_loaded and not result.errors:
        lines.append("No skills loaded.")
    
    lines.append(f"\nToken usage: {result.token_usage} / {loader.budget}")
    return "\n".join(lines)


def skill_stats() -> str:
    """Show skill usage statistics."""
    from core.selfimprove.skill_metadata import SkillMetadataStore
    store = SkillMetadataStore()
    
    lines = ["=== Skill Usage Statistics ==="]
    
    from core.selfimprove.skill_loader import get_skill_loader
    loader = get_skill_loader()
    all_skills = loader.index.get_all_ids()
    
    loaded_skills = []
    for sid in all_skills:
        meta = store.get(sid)
        if meta.loaded_count > 0:
            loaded_skills.append((sid, meta))
    
    if not loaded_skills:
        return "No skill usage data available."
    
    loaded_skills.sort(key=lambda x: x[1].effectiveness_score, reverse=True)
    
    for sid, meta in loaded_skills[:20]:
        bar_len = int(meta.effectiveness_score * 20)
        bar = "█" * bar_len + "░" * (20 - bar_len)
        lines.append(f"  {sid:<35} [{bar}] {meta.effectiveness_score:.2f} "
                     f"(loaded: {meta.loaded_count}, discarded: {meta.discarded_count})")
    
    return "\n".join(lines)


# ── ToolBus factory ────────────────────────────────────────────────────────────

def create_toolbus(cwd: str | Path = ".") -> ToolBus:
    bus = ToolBus(FilesystemSandbox(cwd))

    tools = [
        Tool("run_shell", "Run a shell command", SCHEMA_COMMAND, run_shell, 500),
        Tool("list_dir", "List directory contents", SCHEMA_PATH, list_dir, 100),
        Tool("read_file", "Read a file (first N lines)", SCHEMA_READ, read_file, 200),
        Tool("search_code", "Search code with grep", SCHEMA_PATTERN, search_code, 200),
        Tool("glob", "Find files matching a glob pattern", SCHEMA_GLOB, glob_files, 150),
        Tool("find", "Find files by name", SCHEMA_FIND, find_files, 150),
        Tool("write_file", "Write content to a file", SCHEMA_WRITE, write_file, 200),
        Tool("append_file", "Append content to a file", SCHEMA_APPEND, append_file, 200),
        Tool("mkdir", "Create a directory", SCHEMA_MKDIR, mkdir_tool, 100),
        Tool("copy_file", "Copy a file or directory", SCHEMA_COPY, copy_file, 200),
        Tool("move_file", "Move or rename a file or directory", SCHEMA_MOVE, move_file, 200),
        Tool("delete_file", "Delete a file or directory", SCHEMA_DELETE, delete_file, 200),
        Tool("path_exists", "Check if a path exists", SCHEMA_PATH, path_exists, 50),
        Tool("path_type", "Get path type", SCHEMA_PATH, path_type, 50),
        Tool("git_status", "Show git status", SCHEMA_GIT_REPO, git_status, 100),
        Tool("git_current_branch", "Show current branch", SCHEMA_GIT_REPO, git_current_branch, 50),
        Tool("git_push", "Push to remote", SCHEMA_GIT_PUSH, git_push, 200),
        Tool("git_reset", "Reset HEAD", SCHEMA_GIT_RESET, git_reset, 200),
        Tool("git_delete_branch", "Delete git branch", SCHEMA_GIT_DELETE, git_delete_branch, 200),
        Tool("get_env", "Read an environment variable", SCHEMA_ENV, get_env, 50),
        Tool("set_env", "Set an environment variable", SCHEMA_SETENV, set_env, 50),
        Tool("list_processes", "List running processes", SCHEMA_PS, list_processes, 200),
        Tool("kill_process", "Terminate a process by PID", SCHEMA_KILL, kill_process, 100),
        Tool("docker_ps", "List running Docker containers", SCHEMA_EMPTY, docker_ps, 150),
        Tool("docker_logs", "Fetch Docker container logs", SCHEMA_DOCKER, docker_logs, 200),
        Tool("docker_exec", "Run command in container", SCHEMA_DOCKER_EXEC, docker_exec, 300),
        Tool("run_tests", "Discover and run test suites", SCHEMA_RUN_TESTS, run_tests, 500),
        Tool("explain_code", "Read and explain a code symbol", SCHEMA_EXPLAIN, explain_code, 200),
        Tool("find_symbol", "Search class/function definitions", SCHEMA_FIND_SYM, find_symbol, 200),
        Tool("find_references", "Find symbol references", SCHEMA_FIND_REF, find_references, 200),
        Tool("get_file_tree", "Show directory tree view", SCHEMA_TREE, get_file_tree, 150),
        Tool("list_imports", "List all imports in a file", SCHEMA_PATH, list_imports, 100),
        Tool("memory_search", "Search the memory store", SCHEMA_MEM_SEARCH, memory_search, 100),
        Tool("skill_list", "List available procedural skills (deprecated, use skill_match)", SCHEMA_EMPTY, skill_list, 50),
        Tool("skill_match", "Find most relevant skills for a task using BM25 + semantic matching", "task: str, max_results: int = 5", skill_match, 100),
        Tool("skill_load", "Load a skill into context with dependency resolution + budget check", "name: str", skill_load, 200),
        Tool("skill_load_all", "Auto-load the most relevant skills for the current task", "task: str = '', max_skills: int = 3, max_tokens: int = 4000", skill_load_all, 100),
        Tool("skill_stats", "Show skill usage statistics with effectiveness scores", "", skill_stats, 50),
        Tool("diff_preview", "Show diff between current and new file content", SCHEMA_PREVIEW, diff_preview, 50),
        Tool("edit_file", "Edit content in a file", SCHEMA_EDIT, edit_file, 100),
        Tool("find_definition", "Find where a symbol is defined", SCHEMA_FIND_SYM, find_definition, 50),
        Tool("search_symbols", "Search for symbols by name", SCHEMA_SYMBOL_QUERY, search_symbols, 50),
    ]

    for tool in tools:
        bus.register(tool)

    return bus


__all__ = ["Tool", "ToolBus", "create_toolbus", "EDIT_HISTORY", "clear_edit_history"]
