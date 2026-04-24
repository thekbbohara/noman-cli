"""NoMan TUI REPL."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.events import Key
from textual.reactive import reactive
from textual.widgets import Input, Static, Log


class TUIState(Enum):
    IDLE = "idle"
    INITIALIZING = "initializing"
    RUNNING = "running"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class TUIMetrics:
    turn_count: int = 0
    tokens_used: int = 0
    state: TUIState = TUIState.IDLE


class NoManTUI(App):
    CSS = """
    Screen { background: transparent; }
    #header { dock: top; height: 3; background: $panel; color: $text; }
    #status { width: 100%; content-align: center middle; }
    #output { height: 100%; border: solid $border; background: $surface; }
    #input-area { dock: bottom; height: 3; background: $panel; }
    #input { width: 100%; }
    """

    BINDINGS = [
        ("ctrl+c", "cancel", "Cancel"),
        ("ctrl+e", "expand", "Expand"),
        ("f2", "switch_model", "Model"),
    ]

    _orchestrator = None
    _metrics = reactive(TUIMetrics)
    _last_result_full = ""
    _expanded = False
    _result_lines = []

    def __init__(self, orchestrator=None, **kwargs):
        super().__init__(**kwargs)
        self._orchestrator = orchestrator

    def compose(self) -> ComposeResult:
        with Container():
            with Horizontal(id="header"):
                yield Static("NoMan v0.0.01", id="status")
            yield Log(id="output")
            with Horizontal(id="input-area"):
                yield Input(placeholder="Enter task...", id="input", valid_empty=False)

    def on_mount(self) -> None:
        self.update_status()
        self.query_one("#input", Input).focus()

    def on_key(self, event: Key) -> None:
        if event.key == "enter":
            self.action_submit()

    def action_submit(self) -> None:
        input_widget = self.query_one("#input", Input)
        task = input_widget.value.strip()
        if not task:
            return
        input_widget.value = ""
        asyncio.create_task(self.run_task(task))

    def action_cancel(self) -> None:
        self._metrics.state = TUIState.IDLE
        self.update_status()
        self.show_input()

    def action_expand(self) -> None:
        self._expanded = not self._expanded
        output = self.query_one("#output", Log)
        output.clear()
        for line in self._result_lines:
            output.write(line)

    def action_switch_model(self) -> None:
        providers = self._load_providers()
        if not providers:
            output = self.query_one("#output", Log)
            output.write("No providers configured")
            return

        import os
        config_path = os.path.expanduser("~/.noman/provider.txt")
        current = open(config_path).read().strip() if os.path.exists(config_path) else "default"

        current_idx = providers.index(current) if current in providers else 0
        next_idx = (current_idx + 1) % len(providers)
        new_provider = providers[next_idx]

        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        open(config_path, "w").write(new_provider)

        output = self.query_one("#output", Log)
        output.write(f"Provider: {new_provider} (restart to apply)")

    def _load_providers(self) -> list[str]:
        from pathlib import Path
        config_path = Path.cwd() / "user" / "config.toml"
        if not config_path.exists():
            return []
        try:
            import tomllib
            config = tomllib.loads(config_path.read_text())
            providers = config.get("providers", {})
            if isinstance(providers, list):
                return [p.get("id", "default") for p in providers]
            return list(providers.keys())
        except Exception:
            return []

    def write_history(self, text: str) -> None:
        from pathlib import Path
        history_file = Path.home() / ".noman" / "history.txt"
        history_file.parent.mkdir(exist_ok=True)
        with open(history_file, "a") as f:
            f.write(text + "\n")

    def format_for_display(self, text: str) -> list[str]:
        """Format response for display."""
        import re
        lines = text.strip().split("\n")
        result = []

        in_code = False
        code_lines = []

        for line in lines:
            if line.strip().startswith("```"):
                if in_code:
                    result.append("┌" + "─" * 40)
                    for cl in code_lines:
                        result.append(f"│ {cl}")
                    result.append("└" + "─" * 40)
                    code_lines = []
                else:
                    code_lines = []
                in_code = not in_code
                continue

            if in_code:
                code_lines.append(line)
                continue

            if line.startswith("### "):
                result.append("")
                result.append(f"━━━ {line[4:]} ━━━")
            elif line.startswith("## "):
                result.append("")
                result.append(f"━━ {line[3:]}")
            elif line.startswith("# "):
                result.append(f"◆ {line[2:]}")
            elif line.strip().startswith(("- ", "* ", "+ ")):
                line_clean = line.strip()[2:].strip()
                line_clean = re.sub(r"\*\*(.+?)\*\*", r"[\1]", line_clean)
                result.append(f"◇ {line_clean}")
            elif "**" in line:
                line = re.sub(r"\*\*(.+?)\*\*", r"[\1]", line)
                result.append(line)
            elif line.strip():
                result.append(line)

        return result

    async def run_task(self, task: str) -> None:
        self._metrics.state = TUIState.INITIALIZING
        self.update_status()
        self.hide_input()

        output = self.query_one("#output", Log)
        output.write("")
        output.write(f"❯ {task}")
        output.write("─" * 40)

        self._metrics.state = TUIState.RUNNING
        self.update_status()

        try:
            if self._orchestrator:
                result = await self._orchestrator.run(task)
                self._last_result_full = result
                lines = self.format_for_display(result)
                self._result_lines = lines
                self._expanded = False

                for line in lines[:3]:
                    output.write(line)

                if len(lines) > 3:
                    output.write("")
                    output.write(f"... press Ctrl+E to expand ({len(lines)} lines)")

                self.write_history(f"❯ {task}\n{result}")
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
        self.query_one("#input-area", Horizontal).display = False

    def show_input(self) -> None:
        self.query_one("#input-area", Horizontal).display = True
        self.query_one("#input", Input).focus()


def run_tui(orchestrator=None) -> None:
    app = NoManTUI(orchestrator=orchestrator)
    app.run()