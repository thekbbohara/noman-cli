"""NoMan TUI REPL."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.events import Key
from textual.reactive import reactive
from textual.widgets import Input, RichLog, Static

from core.tools import EDIT_HISTORY


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


class TrackedRichLog(RichLog):
    """RichLog subclass that tracks written content for export."""
    content: str = ""
    def write(self, *args, **kwargs) -> None:
        if args:
            text = str(args[0])
            self.content += text + "\n"
        super().write(*args, **kwargs)
    def write_markup(self, markup: str, style: str | None = None) -> None:
        self.content += markup + "\n"
        super().write_markup(markup, style)
    def clear(self) -> None:
        self.content = ""
        super().clear()


class NoManTUI(App):
    CSS = """
    Screen { background: transparent; }
    App { background: transparent; }
    #header { dock: top; height: 3; background: transparent; color: $text; }
    #status { width: 100%; content-align: center middle; }
    #output { height: 100%; border: none; background: transparent; color: $text; overflow-y: auto; }
    #input-area { dock: bottom; height: 3; background: transparent; }
    #input { width: 100%; background: transparent; }
    #command-palette {
        dock: top;
        height: 15;
        width: 60;
        background: $surface;
        color: $text;
        border: solid $accent;
        padding: 1;
        margin-top: 1;
        display: none;
    }
    #command-palette.visible {
        display: block;
    }
    .command-item {
        margin: 0;
        padding: 0 1;
        height: 2;
    }
    .command-item:hover {
        background: $accent;
        color: $text;
    }
    """

    BINDINGS = [
        ("ctrl+c", "cancel", "Cancel"),
        ("ctrl+e", "expand", "Expand"),
        ("ctrl+d", "diff_view", "Diff"),
        ("ctrl+s", "save_output", "Save Output"),
        ("f2", "switch_model", "Model"),
    ]

    _orchestrator = None
    _metrics = reactive(TUIMetrics)
    _last_result_full = ""
    _last_task = ""
    _expanded = False
    _output_buffer: str = ""  # mirrors what's written to the RichLog
    # Force text-only clipboard — no image upload, no vision errors
    CLIPBOARD_READ_COMMAND: str | None = ""

    def __init__(self, orchestrator=None, **kwargs):
        super().__init__(**kwargs)
        self._orchestrator = orchestrator
        self._session_file = Path.home() / ".noman" / "sessions" / "active_session.md"

    def compose(self) -> ComposeResult:
        with Container():
            with Horizontal(id="header"):
                yield Static("NoMan v0.0.01", id="status")
            yield TrackedRichLog(id="output", markup=True, wrap=True)
            # Command palette (hidden by default)
            with Container(id="command-palette"):
                yield Static("[bold]Commands:[/bold]", style="bold")
                yield Static("  /reset       - Reset current session", id="cmd-reset")
                yield Static("  /diff        - Show file edits (Ctrl+D)", id="cmd-diff")
                yield Static("  /save        - Save output to file (Ctrl+S)", id="cmd-save")
                yield Static("  /model       - Switch provider (F2)", id="cmd-model")
                yield Static("  /help        - Show this help", id="cmd-help")
                yield Static("  /exit        - Exit NoMan", id="cmd-exit")
            with Horizontal(id="input-area"):
                yield Input(placeholder="Enter task... (type / for commands)", id="input", valid_empty=False)

    def on_mount(self) -> None:
        self.update_status()
        self.query_one("#input", Input).focus()
        # Watch for / command in input
        self.watch(self.query_one("#input", Input), "value", self._on_input_change)

        # Load last session if it exists
        if self._session_file.exists():
            try:
                content = self._session_file.read_text()
                if content.strip():
                    self._load_session(content)
                    self.call_next(self._update_session_status)
            except Exception:
                pass

        # Log available tools on startup
        if self._orchestrator:
            tools = self._orchestrator.tool_bus.list_tools()
            print(f"[LOG] Loaded {len(tools)} tools: {', '.join(tools[:10])}{'...' if len(tools) > 10 else ''}")

    def _on_input_change(self, old: str, new: str) -> None:
        """Show command palette when / is typed."""
        if new.strip().startswith("/"):
            self._show_command_palette()
        else:
            self._hide_command_palette()

    def _load_session(self, content: str) -> None:
        """Load session content into the output log."""
        output = self.query_one("#output", TrackedRichLog)
        output.clear()
        # Strip the header/metadata, show only task history
        lines = content.split("\n")
        in_history = False
        for line in lines:
            if line.startswith("# Active Session"):
                in_history = True
                output.write(f"[dim]# Session started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/dim]\n")
                continue
            if in_history and line.startswith("> "):
                # Extract the task and result
                session_text = line[2:]  # Remove "> "
                if session_text.startswith("❯ "):
                    output.write(f"\n[b]{session_text}[/b]\n")
                elif session_text.strip():
                    output.write(f"{session_text}\n")
            elif in_history and line.strip() and not line.startswith("---") and not line.startswith("#") and not line.startswith(">"):
                # Non-empty line that's not a separator or header
                output.write(f"{line}\n")

    def _update_session_status(self) -> None:
        """Update status bar to show session state."""
        status = self.query_one("#status", Static)
        if self._session_file.exists():
            try:
                content = self._session_file.read_text()
                # Count tasks in session
                task_count = content.count("❯ ")
                size_kb = self._session_file.stat().st_size / 1024
                status.update(f"Turn {self._metrics.turn_count} | {task_count} tasks | {size_kb:.1f}KB")
            except Exception:
                status.update(f"Turn {self._metrics.turn_count} | session loaded")
        else:
            status.update(f"Turn {self._metrics.turn_count} | new session")

    def on_key(self, event: Key) -> None:
        if event.key == "enter":
            self.action_submit()
        elif event.key == "escape":
            self._hide_command_palette()

    def _show_command_palette(self) -> None:
        """Show the command palette at the top of the screen."""
        palette = self.query_one("#command-palette", Container)
        palette.add_class("visible")
        self.query_one("#input", Input).blur()

    def _hide_command_palette(self) -> None:
        """Hide the command palette."""
        palette = self.query_one("#command-palette", Container)
        palette.remove_class("visible")

    def _on_click(self, event) -> None:
        """Handle clicks on command palette items."""
        if not hasattr(event, "node"):
            return
        node = event.node
        if node and hasattr(node, "id"):
            cmd_map = {
                "cmd-reset": "/reset",
                "cmd-diff": "/diff",
                "cmd-save": "/save",
                "cmd-model": "/model",
                "cmd-help": "/help",
                "cmd-exit": "/exit",
            }
            cmd = cmd_map.get(node.id)
            if cmd:
                self._hide_command_palette()
                input_widget = self.query_one("#input", Input)
                input_widget.value = cmd
                self.call_after_refresh(lambda: input_widget.focus())

    def _handle_command(self, task: str) -> bool:
        """Handle special commands. Returns True if command was handled."""
        input_widget = self.query_one("#input", Input)
        
        if task == "/reset":
            self._reset_session()
            return True
        
        if task == "/diff":
            self.action_diff_view()
            return True
        
        if task == "/save":
            self.action_save_output()
            return True
        
        if task == "/model":
            self.action_switch_model()
            return True
        
        if task == "/help":
            self._show_command_palette()
            return True
        
        if task == "/exit":
            self.exit()
            return True
        
        return False

    def _reset_session(self) -> None:
        """Reset the current session — clear orchestrator, output, and session file."""
        if self._orchestrator:
            self._orchestrator.reset_session()
        
        # Clear the output log
        output = self.query_one("#output", TrackedRichLog)
        output.clear()
        
        # Clear the active session file
        if self._session_file.exists():
            try:
                self._session_file.unlink()
            except Exception:
                pass
        
        # Reset metrics
        self._metrics.turn_count = 0
        self._metrics.state = TUIState.IDLE
        self.update_status()
        self.notify("Session reset", severity="info")

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
        
        # Handle special commands
        if task.startswith("/"):
            if self._handle_command(task):
                input_widget.value = ""
                return
        
        input_widget.value = ""
        asyncio.create_task(self.run_task(task))

    def action_cancel(self) -> None:
        self._metrics.state = TUIState.IDLE
        self.update_status()
        self.show_input()

    def action_expand(self) -> None:
        self._expanded = not self._expanded
        output = self.query_one("#output", TrackedRichLog)
        # Don't clear, just toggle wrap mode for long content
        if self._expanded:
            output.wrap = True
        else:
            output.wrap = True  # always wrap for readability

    def action_diff_view(self) -> None:
        output = self.query_one("#output", TrackedRichLog)
        output.clear()
        from difflib import unified_diff
        from rich.text import Text

        if not EDIT_HISTORY:
            output.write("[yellow]No file edits yet[/yellow]")
            return

        for edit in EDIT_HISTORY[-5:]:
            path = edit["path"]
            old_content = edit["old"]
            new_content = edit["new"]

            old_lines = old_content.splitlines(keepends=True)
            new_lines = new_content.splitlines(keepends=True)

            diff = list(unified_diff(old_lines, new_lines, fromfile=path, tofile=path, lineterm=""))

            if not diff:
                continue

            output.write(f"\n[bold]Edit: {path}[/bold]")
            for line in diff:
                if line.startswith("+++") or line.startswith("---"):
                    continue
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

        output = self.query_one("#output", TrackedRichLog)
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

    def action_save_output(self) -> None:
        """Dump the current output to a file so it can be copied."""
        output = self.query_one("#output", TrackedRichLog)
        content = output.content
        if not content.strip():
            self.notify("Nothing to save", severity="warning")
            return
        session_dir = Path.home() / ".noman" / "sessions"
        session_dir.mkdir(exist_ok=True)
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_path = session_dir / f"output_{ts}.txt"
        file_path.write_text(content)
        self.notify(f"Saved to {file_path}", severity="info")

    def write_history(self, text: str) -> None:
        session_dir = Path.home() / ".noman" / "sessions"
        session_dir.mkdir(exist_ok=True)

        # Append to active session file instead of creating new timestamped files
        session_file = session_dir / "active_session.md"

        prev = session_file.read_text() if session_file.exists() else ""

        if not prev:
            content = f"# Active Session\n\n**Started:** {datetime.now().isoformat()}\n\n---\n\n"
        else:
            content = prev.rstrip()

        content += f"\n---\n\n> {text}\n"

        session_file.write_text(content + "\n")

    async def run_task(self, task: str) -> None:
        try:
            self._metrics.state = TUIState.INITIALIZING
            self.call_next(self.update_status)
            self.call_next(self.hide_input)

            output = self.query_one("#output", TrackedRichLog)
            # Append task prompt instead of clearing — keeps full session history
            output.write(f"\n[b]❯ {task}[/b]\n")

            self._metrics.state = TUIState.RUNNING
            self.call_next(self.update_status)

            if self._orchestrator:
                result = await self._orchestrator.run(task)
                self._last_result_full = result
                self._last_task = task

                # Show full response — no truncation
                lines = self._convert_markdown_to_textual(result)
                for line in lines:
                    output.write(line)
                output.write("\n")

                self.write_history(f"❯ {task}\n{result}")
                self._metrics.state = TUIState.COMPLETE
            else:
                output.write("[red]Error: No orchestrator[/red]")
                self._metrics.state = TUIState.ERROR
        except Exception as e:
            import traceback
            output = self.query_one("#output", TrackedRichLog)
            output.write(f"[red]Crash: {e}[/red]")
            output.write(f"[dim]{traceback.format_exc()}[/dim]")
            self._metrics.state = TUIState.ERROR
        finally:
            self._metrics.turn_count += 1
            self.call_next(self.update_status)
            self.call_next(self.show_input)

    def update_status(self) -> None:
        status = self.query_one("#status", Static)
        m = self._metrics
        if m.state == TUIState.IDLE:
            if self._session_file.exists():
                try:
                    content = self._session_file.read_text()
                    task_count = content.count("❯ ")
                    size_kb = self._session_file.stat().st_size / 1024
                    status.update(f"Turn {m.turn_count} | {task_count} tasks | {size_kb:.1f}KB")
                except Exception:
                    status.update("NoMan v0.0.01 | session loaded")
            else:
                status.update("NoMan v0.0.01 | new session")
        elif m.state == TUIState.INITIALIZING:
            status.update("Initializing...")
        elif m.state == TUIState.RUNNING:
            status.update(f"Turn {m.turn_count + 1} | running")
        elif m.state == TUIState.COMPLETE:
            if self._session_file.exists():
                try:
                    content = self._session_file.read_text()
                    task_count = content.count("❯ ")
                    size_kb = self._session_file.stat().st_size / 1024
                    status.update(f"Turn {m.turn_count} | {task_count} tasks | {size_kb:.1f}KB")
                except Exception:
                    status.update(f"Turn {m.turn_count} | complete")
            else:
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
