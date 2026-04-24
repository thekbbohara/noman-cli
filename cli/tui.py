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
    _last_result_full: str = ""
    _expanded: bool = False

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
        output = self.query_one("#output", Log)
        output.tooltip = "Click to select text for copy"

    def on_key(self, event: Key) -> None:
        if event.key == "enter":
            self.action_submit()
        elif event.key == "f2":
            self.action_switch_model()

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
        """Toggle full result display."""
        self._expanded = not self._expanded
        if self._last_result_full:
            output = self.query_one("#output", Log)
            output.clear()
            lines = self._last_result_full.strip().split("\n") if self._expanded else self._last_result_full.strip().split("\n")[:100]
            for line in self.render_markdown("\n".join(lines)):
                output.write(f"{line}\n")

    def action_switch_model(self) -> None:
        """Switch model provider."""
        from pathlib import Path
        import os

        config_path = Path.home() / ".noman" / "provider.txt"
        current = config_path.read_text().strip() if config_path.exists() else "default"

        providers = self._load_providers()
        if not providers:
            output = self.query_one("#output", Log)
            output.write("No providers configured in user/config.toml")
            return

        # Cycle through providers
        current_idx = providers.index(current) if current in providers else 0
        next_idx = (current_idx + 1) % len(providers)
        new_provider = providers[next_idx]

        config_path.write_text(new_provider)

        output = self.query_one("#output", Log)
        output.write(f"Switched to: {new_provider} (restart to apply)")
        self.update_status()

    def _load_providers(self) -> list[str]:
        """Load available providers from config."""
        from pathlib import Path
        import tomllib

        config_path = Path.cwd() / "user" / "config.toml"
        if not config_path.exists():
            return []

        try:
            config = tomllib.loads(config_path.read_text())
            providers = config.get("providers", {})
            if isinstance(providers, list):
                return [p.get("id", "default") for p in providers]
            return list(providers.keys())
        except Exception:
            return []
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