"""NoMan TUI REPL."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.events import Key
from textual.keys import Keys
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
    Screen { background: $surface; }
    #header { dock: top; height: 3; background: $panel; color: $text; }
    #status { width: 100%; content-align: center middle; }
    #output { height: 100%; border: solid $border; }
    #output:focus { border: double $accent; }
    #input-area { dock: bottom; height: 3; background: $panel; }
    #input { width: 100%; }
    """

    BINDINGS = [
        ("ctrl+c", "cancel", "Cancel"),
        ("ctrl+a", "select_all", "Select All"),
    ]

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

    def action_select_all(self) -> None:
        """Select all text in output for copying."""
        output = self.query_one("#output", Log)
        output.anchor()

    async def run_task(self, task: str) -> None:
        self._metrics.state = TUIState.INITIALIZING
        self.update_status()
        self.hide_input()

        output = self.query_one("#output", Log)
        output.write(f"$ {task}")
        output.write("")

        self._metrics.state = TUIState.RUNNING
        self.update_status()

        try:
            if self._orchestrator:
                result = await self._orchestrator.run(task)
                output.write(result)
                output.write("")
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