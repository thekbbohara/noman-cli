"""NoMan TUI REPL."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.events import Key
from textual.reactive import reactive
from textual.widgets import Input, RichLog, Static


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
    App { background: transparent; }
    #header { dock: top; height: 3; background: transparent; color: $text; }
    #status { width: 100%; content-align: center middle; }
    #output { height: 100%; border: none; background: transparent; color: $text; overflow-y: auto; }
    #input-area { dock: bottom; height: 3; background: transparent; }
    #input { width: 100%; background: transparent; }
    """

    BINDINGS = [
        ("ctrl+c", "cancel", "Cancel"),
        ("ctrl+e", "expand", "Expand"),
        ("ctrl+d", "diff_view", "Diff"),
        ("f2", "switch_model", "Model"),
    ]

    _orchestrator = None
    _metrics = reactive(TUIMetrics)
    _last_result_full = ""
    _last_task = ""
    _expanded = False
    # Force text-only clipboard — no image upload, no vision errors
    CLIPBOARD_READ_COMMAND: str | None = ""

    def __init__(self, orchestrator=None, **kwargs):
        super().__init__(**kwargs)
        self._orchestrator = orchestrator

    def compose(self) -> ComposeResult:
        with Container():
            with Horizontal(id="header"):
                yield Static("NoMan v0.0.01", id="status")
            yield RichLog(id="output", markup=True, wrap=True)
            with Horizontal(id="input-area"):
                yield Input(placeholder="Enter task...", id="input", valid_empty=False)

    def on_mount(self) -> None:
        self.update_status()
        self.query_one("#input", Input).focus()

    def on_key(self, event: Key) -> None:
        if event.key == "enter":
            self.action_submit()

    def _convert_markdown_to_textual(self, text: str) -> list:
        """Convert markdown to Rich Text objects."""
        from rich.text import Text

        lines = []
        in_code = False

        for line in text.split("\n"):
            if line.strip().startswith("```"):
                if in_code:
                    lines.append(Text("─" * 40, style="dim"))
                else:
                    lines.append(Text("─" * 40, style="dim"))
                in_code = not in_code
                continue

            if in_code:
                lines.append(Text(line, style="cyan"))
                continue

            if line.startswith("# "):
                lines.append(Text(line[2:].strip(), style="bold"))
                continue
            elif line.startswith("## "):
                lines.append(Text(line[3:].strip(), style="bold"))
                continue
            elif line.startswith("### "):
                lines.append(Text(line[4:].strip(), style="bold"))
                continue

            stripped = line.strip()
            if stripped.startswith(("- ", "* ", "+ ")):
                item = stripped[2:].strip()
                item = re.sub(r"\*\*(.+?)\*\*", r"[b]\1[/b]", item)
                item = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"[i]\1[/i]", item)
                lines.append(Text.from_markup(f"  • {item}"))
                continue
            elif "**" in line:
                line = re.sub(r"\*\*(.+?)\*\*", r"[b]\1[/b]", line)
                lines.append(Text.from_markup(line))
                continue
            else:
                lines.append(Text(line))

        return lines

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
            for line in self._last_result_full.split("\n"):
                output.write(line)
        else:
            lines = self._convert_markdown_to_textual(self._last_result_full)
            for line in lines[:5]:
                output.write(line)
            if len(lines) > 5:
                output.write("[i]... (Ctrl+E for full)[/i]")

    def action_diff_view(self) -> None:
        if not self._last_result_full:
            return
        output = self.query_one("#output", RichLog)
        output.clear()
        from difflib import unified_diff
        from rich.text import Text
        lines = self._last_task.split("\n") if self._last_task else []
        result_lines = self._last_result_full.split("\n")
        diff = list(unified_diff(lines, result_lines, lineterm=""))
        if not diff:
            output.write("[yellow]No diff available - run a task first[/yellow]")
            return
        output.write("[bold]Diff View:[/bold]")
        for line in diff:
            if line.startswith("+++") or line.startswith("---"):
                output.write(Text(line, style="dim"))
            elif line.startswith("+"):
                output.write(Text(line, style="green bold"))
            elif line.startswith("-"):
                output.write(Text(line, style="red strike"))
            elif line.startswith("@@"):
                output.write(Text(line, style="cyan"))
            else:
                output.write(line)

    def action_switch_model(self) -> None:
        providers = self._load_providers()
        if not providers:
            return

        config_path = Path("~/.noman/provider.txt").expanduser()
        current = config_path.read_text().strip() if config_path.exists() else "default"

        current_idx = providers.index(current) if current in providers else 0
        next_idx = (current_idx + 1) % len(providers)
        new_provider = providers[next_idx]

        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(new_provider)

        output = self.query_one("#output", RichLog)
        output.clear()
        output.write(f"[green]Provider: {new_provider}[/green] (restart)")

    def _load_providers(self) -> list[str]:
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
        history_file = Path.home() / ".noman" / "history.txt"
        history_file.parent.mkdir(exist_ok=True)
        history_file.open("a").write(text + "\n")

    async def run_task(self, task: str) -> None:
        self._metrics.state = TUIState.INITIALIZING
        self.update_status()
        self.hide_input()

        output = self.query_one("#output", RichLog)
        output.clear()
        output.write(f"[b]❯[/b] {task}")

        self._metrics.state = TUIState.RUNNING
        self.update_status()

        try:
            if self._orchestrator:
                result = await self._orchestrator.run(task)
                self._last_result_full = result
                self._last_task = task
                self._expanded = False

                lines = self._convert_markdown_to_textual(result)
                for line in lines[:5]:
                    output.write(line)
                if len(lines) > 5:
                    output.write("[i]... (Ctrl+E to expand)[/i]")

                self.write_history(f"❯ {task}\n{result}")
                self._metrics.state = TUIState.COMPLETE
            else:
                output.write("[red]Error: No orchestrator[/red]")
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
            status.update(f"Turn {m.turn_count + 1} | running")
        elif m.state == TUIState.COMPLETE:
            status.update(f"Turn {m.turn_count} | complete")
        elif m.state == TUIState.ERROR:
            status.update(f"Turn {m.turn_count} | error")

    def hide_input(self) -> None:
        self.query_one("#input-area", Horizontal).display = False

    def show_input(self) -> None:
        self.query_one("#input-area", Horizontal).display = True
        self.query_one("#input", Input).focus()


def run_tui(orchestrator=None) -> None:
    app = NoManTUI(orchestrator=orchestrator)
    app.run()
