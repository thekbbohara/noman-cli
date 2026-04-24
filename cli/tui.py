"""NoMan TUI REPL."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum

from rich.console import Console
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.events import Key
from textual.reactive import reactive
from textual.widgets import Input, Static, RichLog


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
    _console = Console()

    def __init__(self, orchestrator=None, **kwargs):
        super().__init__(**kwargs)
        self._orchestrator = orchestrator

    def compose(self) -> ComposeResult:
        with Container():
            with Horizontal(id="header"):
                yield Static("NoMan v0.0.01", id="status")
            yield RichLog(id="output")
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
        output = self.query_one("#output", RichLog)
        output.clear()
        if self._expanded:
            output.write(self._last_result_full)
        else:
            lines = self._last_result_full.strip().split("\n")
            for line in lines[:3]:
                output.write(line)
            if len(lines) > 3:
                output.write("... (press Ctrl+E to see all)")

    def action_switch_model(self) -> None:
        providers = self._load_providers()
        if not providers:
            return

        import os
        config_path = os.path.expanduser("~/.noman/provider.txt")
        current = open(config_path).read().strip() if os.path.exists(config_path) else "default"

        current_idx = providers.index(current) if current in providers else 0
        next_idx = (current_idx + 1) % len(providers)
        new_provider = providers[next_idx]

        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        open(config_path, "w").write(new_provider)

        output = self.query_one("#output", RichLog)
        output.clear()
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

    async def run_task(self, task: str) -> None:
        self._metrics.state = TUIState.INITIALIZING
        self.update_status()
        self.hide_input()

        output = self.query_one("#output", RichLog)
        output.clear()
        output.write(f"[bold]❯[/bold] {task}")

        self._metrics.state = TUIState.RUNNING
        self.update_status()

        try:
            if self._orchestrator:
                result = await self._orchestrator.run(task)
                self._last_result_full = result
                self._expanded = False
                output.write(result)
                self.write_history(f"❯ {task}\n{result}")
                self._metrics.state = TUIState.COMPLETE
            else:
                output.write("[red]Error: No orchestrator configured[/red]")
                self._metrics.state = TUIState.ERROR
        except Exception as e:
            output.write(f"[red]Error: {e}[/red]")
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