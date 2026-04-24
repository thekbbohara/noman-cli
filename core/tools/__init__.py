"""Core tools."""

from __future__ import annotations

import asyncio
import os
import shlex
from typing import Any

from core.tools.bus import Tool, ToolBus


def run_shell(command: str, cwd: str | None = None) -> str:
    """Run a shell command."""
    import subprocess
    result = subprocess.run(
        command,
        shell=True,
        cwd=cwd or os.getcwd(),
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.stdout or result.stderr or ""


def list_dir(path: str = ".") -> str:
    """List directory contents."""
    import os
    try:
        return "\n".join(os.listdir(path))
    except FileNotFoundError:
        return f"Directory not found: {path}"
    except PermissionError:
        return f"Permission denied: {path}"


def read_file(path: str, lines: int = 100) -> str:
    """Read a file."""
    try:
        with open(path) as f:
            return "".join(f.readlines()[:lines])
    except FileNotFoundError:
        return f"File not found: {path}"
    except PermissionError:
        return f"Permission denied: {path}"


def search_code(pattern: str, path: str = ".") -> str:
    """Search code with grep."""
    import subprocess
    result = subprocess.run(
        ["grep", "-r", pattern, path],
        capture_output=True,
        text=True,
    )
    return result.stdout or "No matches found"


def create_toolbus(cwd: str) -> ToolBus:
    """Create a toolbus with core tools registered."""
    from core.security.fs_sandbox import FilesystemSandbox
    
    fs = FilesystemSandbox(cwd)
    bus = ToolBus(fs)
    
    bus.register(Tool(
        name="run_shell",
        description="Run shell command",
        parameters={"required": ["command"]},
        handler=run_shell,
        cost_estimate=500,
    ))
    
    bus.register(Tool(
        name="list_dir",
        description="List directory contents",
        parameters={"required": ["path"]},
        handler=list_dir,
        cost_estimate=100,
    ))
    
    bus.register(Tool(
        name="read_file",
        description="Read a file",
        parameters={"required": ["path"]},
        handler=read_file,
        cost_estimate=200,
    ))
    
    bus.register(Tool(
        name="search_code",
        description="Search code with grep",
        parameters={"required": ["pattern"]},
        handler=search_code,
        cost_estimate=200,
    ))
    
    return bus


__all__ = ["Tool", "ToolBus", "create_toolbus"]