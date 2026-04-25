# Diff Preview + Code Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable agent to make surgical code changes with visibility — agent can navigate codebase, see diff preview before applying, and user sees colored diff after each edit.

**Architecture:** Extend `core/tools/__init__.py` with diff_preview and edit_file tools. Navigation reuses existing search patterns. TUI renders diff with colors (+green/-red) in chat output.

**Tech Stack:** Python, difflib (stdlib), Rich (for TUI colors)

---
### Task 1: Add diff_preview Tool

**Files:**
- Modify: `core/tools/__init__.py:630-650`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_tool_bus.py (new file)
import pytest
from core.tools import diff_preview

def test_diff_preview_returns_unified_diff():
    """Given current file content and new content, returns unified diff."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
        f.write("line1\nline2\nline3\n")
        f.flush()
        path = f.name
    
    new_content = "line1\nmodified\nline3\n"
    result = diff_preview(path, new_content)
    
    assert "---" in result  # old file marker
    assert "+++" in result  # new file marker
    assert "-line2" in result  # removed
    assert "+modified" in result  # added
    
    os.unlink(path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_tool_bus.py::test_diff_preview_returns_unified_diff -v`
Expected: FAIL with "function not defined"

- [ ] **Step 3: Write diff_preview implementation**

Add to `core/tools/__init__.py` after line 630:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_tool_bus.py::test_diff_preview_returns_unified_diff -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/tools/__init__.py tests/unit/test_tool_bus.py
git commit -m "feat: add diff_preview tool"
```

---

### Task 2: Add edit_file Tool

**Files:**
- Modify: `core/tools/__init__.py:650-680`

- [ ] **Step 1: Write the failing test**

```python
def test_edit_file_applies_change():
    """Given file, old content, new content — applies change."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
        f.write("line1\nline2\nline3\n")
        f.flush()
        path = f.name
    
    result = edit_file(path, "line2\n", "replaced\n")
    
    content = Path(path).read_text()
    assert "replaced" in content
    assert "line2" not in content
    assert "Applied" in result
    
    os.unlink(path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_tool_bus.py::test_edit_file_applies_change -v`
Expected: FAIL with "function not defined"

- [ ] **Step 3: Write edit_file implementation**

Add to `core/tools/__init__.py` after diff_preview:

```python
def edit_file(path: str, old_content: str, new_content: str) -> str:
    """Replace old_content with new_content in file."""
    p = Path(path).resolve()
    if not p.exists():
        return f"File not found: {path}"
    
    current = p.read_text()
    if old_content not in current:
        return f"Old content not found in {path}"
    
    updated = current.replace(old_content, new_content)
    p.write_text(updated)
    
    return f"Applied change to {path}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_tool_bus.py::test_edit_file_applies_change -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/tools/__init__.py tests/unit/test_tool_bus.py
git commit -m "feat: add edit_file tool"
```

---

### Task 3: Add Navigation Tools

**Files:**
- Modify: `core/tools/__init__.py` — add three functions before tool registration

- [ ] **Step 1: Write the failing test**

```python
def test_find_definition_returns_location():
    """Find where a symbol is defined."""
    # Uses grep pattern ^def symbol_name or ^class symbol_name
    result = find_definition("write_file")
    assert "def write_file" in result

def test_find_references_returns_files():
    """Find files that reference a symbol."""
    result = find_references("diff_preview")
    assert isinstance(result, list)

def test_search_symbols_finds_by_name():
    """Search for symbols matching query."""
    result = search_symbols("diff")
    assert "diff_preview" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_tool_bus.py -k "find_definition or find_references or search_symbols" -v`
Expected: FAIL with "function not defined"

- [ ] **Step 3: Write navigation implementations**

```python
import re

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
            if py_file.read_text().search(pattern):
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_tool_bus.py -k "find_definition or find_references or search_symbols" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/tools/__init__.py
git commit -m "feat: add navigation tools (find_definition, find_references, search_symbols)"
```

---

### Task 4: Register Tools in ToolBus

**Files:**
- Modify: `core/tools/__init__.py:630` — add Tool registration lines

- [ ] **Step 1: Add tool registrations**

After existing tool registrations, add:

```python
Tool("diff_preview", "Show diff between current and new file content", SCHEMA_DIFF_PREVIEW, diff_preview, 50),
Tool("edit_file", "Replace content in a file", SCHEMA_EDIT_FILE, edit_file, 100),
Tool("find_definition", "Find where a symbol is defined", {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}, find_definition, 50),
Tool("find_references", "Find files that reference a symbol", {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}, find_references, 50),
Tool("search_symbols", "Search for symbols by name", {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}, search_symbols, 50),
```

- [ ] **Step 2: Test registrations load**

Run: `python -c "from core.tools import TOOLS; print([t.name for t in TOOLS])"`
Expected: Contains diff_preview, edit_file, find_definition, find_references, search_symbols

- [ ] **Step 3: Commit**

```bash
git add core/tools/__init__.py
git commit -m "feat: register new tools in ToolBus"
```

---

### Task 5: Add TUI Diff Display

**Files:**
- Modify: `cli/tui.py:153-180` — update action_diff_view

- [ ] **Step 1: Extend diff view to show file edits**

Update `action_diff_view` to track recent edits and display:

```python
def action_diff_view(self) -> None:
    """Show diff of recent file changes."""
    from difflib import unified_diff
    
    # Check if we have recent edit_file calls stored
    if not hasattr(self, '_edit_history'):
        output.write("[yellow]No file edits yet[/yellow]")
        return
    
    for edit in self._edit_history[-5:]:  # last 5 edits
        path = edit['path']
        old_lines = edit['old'].splitlines(keepends=True)
        new_lines = edit['new'].splitlines(keepends=True)
        
        diff = list(unified_diff(old_lines, new_lines, fromfile=path, tofile=path, lineterm=""))
        
        output.write(f"\n[bold]Edit: {path}[/bold]")
        for line in diff:
            if line.startswith("+++") or line.startswith("---"):
                continue  # Skip file markers
            elif line.startswith("+"):
                output.write(Text(line, style="green bold"))
            elif line.startswith("-"):
                output.write(Text(line, style="red strike"))
            elif line.startswith("@@"):
                output.write(Text(line, style="cyan"))
            else:
                output.write(line)
```

- [ ] **Step 2: Track edits when edit_file runs**

In core.py or tool execution, store edit history:

```python
# After successful edit_file, append to _edit_history
# This requires orchestrator to track tool results
```

- [ ] **Step 3: Test TUI diff display**

Run TUI, make an edit, press Ctrl+D
Expected: Shows colored diff in output

- [ ] **Step 4: Commit**

```bash
git add cli/tui.py
git commit -m "feat: add colored diff display in TUI"
```

---

## Execution

**Plan complete and saved to `docs/superpowers/plans/2026-04-25-diff-preview-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**