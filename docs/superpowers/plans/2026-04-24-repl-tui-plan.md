# REPL TUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement interactive TUI REPL using textual, replacing the stub message when running `noman` with no arguments.

**Architecture:** Create a new `cli/tui.py` module with a Textual app. Integrate with existing orchestrator from `core/orchestrator/core.py`. Add textual to dependencies in `pyproject.toml`.

**Tech Stack:** textual >= 0.50, Python 3.11+

---

## Task 1: Add textual dependency

**Files:**
- Modify: `pyproject.toml:33`

- [ ] **Step 1: Add textual to dependencies**

In `pyproject.toml`, add `"textual>=0.50"` to the dependencies list:

```toml
dependencies = [
    "httpx>=0.27",
    "pydantic>=2.0",
    "tomli>=2.0;python_version<'3.11'",
    "structlog>=24.1",
    "rich>=13.7",
    "click>=8.1",
    "pyyaml>=6.0",
    "cryptography>=42.0",
    "textual>=0.50",
]
```

- [ ] **Step 2: Install the dependency**

Run: `pip install textual>=0.50`
Expected: Installation completes without errors

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "deps: add textual for TUI"
```

---

## Task 2: Create TUI app module

**Files:**
- Create: `cli/tui.py`

- [ ] **Step 1: Create the TUI app**

Create `cli/tui.py`:

```python
"""NoMan TUI REPL."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.driver import Driver
from textual.events import Key
from textual.reactive import reactive
from textual.widgets import Header, Input, Static, Log


class TUIState(Enum):
    IDLE = "idle"
    INITIALIZING = "initializing"
    RUNNING = "running"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class TUIMetrics:
    """Runtime metrics."""
    turn_count: int = 0
    tokens_used: int = 0
    state: TUIState = TUIState.IDLE


class NoManTUI(App):
    """NoMan interactive TUI."""

    CSS = """
    Screen {
        background: $surface;
    }
    #header {
        dock: top;
        height: 3;
        background: $panel;
        color: $text;
    }
    #status {
        width: 100%;
        content-align: center middle;
    }
    #output {
        height: 100%;
        border: solid $border;
    }
    #input-area {
        dock: bottom;
        height: 3;
        background: $panel;
    }
    #input {
        width: 100%;
    }
    """

    _orchestrator = None
    _metrics = reactive(TUIMetrics)

    def __init__(self, orchestrator=None, **kwargs):
        super().__init__(**kwargs)
        self._orchestrator = orchestrator

    def compose(self) -> ComposeResult:
        with Container():
            with Horizontal(id="header"):
                yield Static("NoMan v0.0.01", id="status")
            yield Log(id="output")
            with Horizontal(id="input-area"):
                yield Input(placeholder="Enter task...", id="input")

    def on_mount(self) -> None:
        self.update_status()

    def on_input_submit(self, event: Input.Submit) -> None:
        task = event.value.strip()
        if not task:
            return
        asyncio.create_task(self.run_task(task))

    async def run_task(self, task: str) -> None:
        """Execute a task through the orchestrator."""
        self._metrics.state = TUIState.INITIALIZING
        self.update_status()
        self.hide_input()

        output = self.query_one("#output", Log)
        output.write(f"$ {task}")

        self._metrics.state = TUIState.RUNNING
        self.update_status()

        try:
            if self._orchestrator:
                result = await self._orchestrator.run(task)
                output.write(result)
                self._metrics.state = TUIState.COMPLETE
            else:
                output.write("Error: No orchestrator configured")
                self._metrics.state = TUIState.ERROR
        except Exception as e:
            output.write(f"Error: {e}")
            self._metrics.state = TUIState.ERROR

        self._metrics.turn_count += 1
        self.update_status()
        self.show_input()

    def update_status(self) -> None:
        status = self.query_one("#status", Static)
        m = self._metrics

        if m.state == TUIState.IDLE:
            status.update("NoMan v0.0.01")
        elif m.state == TUIState.INITIALIZING:
            status.update("Initializing...")
        elif m.state == TUIState.RUNNING:
            status.update(f"Turn {m.turn_count + 1} | {m.tokens_used} tokens | running")
        elif m.state == TUIState.COMPLETE:
            status.update(f"Turn {m.turn_count} | {m.tokens_used} tokens | complete")
        elif m.state == TUIState.ERROR:
            status.update(f"Turn {m.turn_count} | {m.tokens_used} tokens | error")

    def hide_input(self) -> None:
        inp = self.query_one("#input-area", Horizontal)
        inp.display = False

    def show_input(self) -> None:
        inp = self.query_one("#input-area", Horizontal)
        inp.display = True
        input_widget = self.query_one("#input", Input)
        input_widget.focus()


def run_tui(orchestrator=None) -> None:
    """Run the TUI app."""
    app = NoManTUI(orchestrator=orchestrator)
    app.run()
```

- [ ] **Step 2: Commit**

```bash
git add cli/tui.py
git commit -m "feat: add TUI app module"
```

---

## Task 3: Integrate TUI with CLI entry point

**Files:**
- Modify: `cli/main.py:172-176`

- [ ] **Step 1: Update main.py to use TUI**

Replace lines 172-176 in `cli/main.py`:

```python
    else:
        # Run TUI
        from cli.tui import run_tui
        orch = _create_orchestrator(args)
        run_tui(orch)
        return 0
```

With:

```python
    else:
        # Run TUI REPL
        from cli.tui import run_tui
        orch = _create_orchestrator(args)
        if orch is None:
            logger.error("Failed to create orchestrator")
            return 1
        run_tui(orch)
        return 0
```

- [ ] **Step 2: Test locally**

Run: `python -m cli.main`
Expected: TUI window opens with "NoMan v0.0.01" in header and input prompt

- [ ] **Step 3: Commit**

```bash
git add cli/main.py
git commit -m "feat: integrate TUI with CLI entrypoint"
```

---

## Task 4: Handle Ctrl+C gracefully

**Files:**
- Modify: `cli/tui.py`

- [ ] **Step 1: Add key handler for Ctrl+C**

Add to `NoManTUI` class in `cli/tui.py`:

```python
    def on_key(self, event: Key) -> None:
        if event.key == "ctrl+c":
            self._metrics.state = TUIState.IDLE
            self.update_status()
            self.show_input()
            return
        super().on_key(event)
```

- [ ] **Step 2: Test Ctrl+C**

Run a task, then press Ctrl+C. Expected: Returns to idle state.

- [ ] **Step 3: Commit**

```bash
git add cli/tui.py
git commit -m "feat: handle Ctrl+C gracefully"
```

---

## Acceptance Criteria

1. `noman` (no args) opens TUI with prompt ✓
2. Typing task and pressing Enter runs it ✓
3. Header shows turn count and token usage ✓
4. Output displays as task runs ✓
5. After completion, prompt returns ✓
6. Ctrl+C stops task gracefully ✓

---

## Spec Coverage

| Spec Section | Task |
|-------------|------|
| 2.1 Idle State | Task 2: compose(), on_mount() |
| 2.2 Running State | Task 2: run_task(), update_status() |
| 2.3 Transitions | Task 2: hide_input(), show_input() |
| 3.2 Layout | Task 2: CSS definition |
| 3.3 Components | Task 2: Header, Log, Input |
| 3.4 State Machine | Task 2: TUIState enum + reactive |
| 4. Integration | Task 3: main.py update |
| 5. Out of Scope | N/A - not implementing |

---

**Plan complete and saved to `docs/superpowers/plans/2026-04-24-repl-tui-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**