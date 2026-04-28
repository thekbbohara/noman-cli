"""NoMan TUI REPL."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime
from difflib import unified_diff
from enum import Enum
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.events import Key
from textual.reactive import reactive
from textual.widgets import DataTable, Input, Label, RichLog, Static

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

    def write(self, *args: object, **kwargs: object) -> RichLog:  # type: ignore[override]
        if args:
            text = str(args[0])
            self.content += text + "\n"
        return super().write(*args, **kwargs)  # type: ignore[arg-type]

    def write_markup(self, markup: str, style: str | None = None) -> None:
        self.content += markup + "\n"
        super().write_markup(markup, style)  # type: ignore[misc]

    def clear(self) -> RichLog:
        self.content = ""
        super().clear()


class NoManTUI(App):
    CSS = """
    Screen { background: transparent; }
    App { background: transparent; }
    #header { dock: top; height: 3; background: transparent; color: $text; }
    #status { width: 100%; content-align: center middle; }
    #output { height: 100%; border: none; background: transparent; color: $text; overflow-y: auto; allow-select: true; }
    #input-area { dock: bottom; height: 5; background: transparent; }
    #input { width: 100%; background: transparent; }

    #command-palette {
        dock: bottom;
        height: 10;
        width: 70;
        margin-bottom: 6;
        background: transparent;
        color: $text;
        border: none;
        padding: 1 2;
        display: none;
    }
    #command-palette.visible {
        display: block;
    }
    #palette-title {
        text-align: center;
        width: 100%;
    }
    #command-table {
        height: 100%;
    }
    #command-table > DataTable {
        border: none;
    }
    #command-table > DataTable.row:hover {
        background: $accent 20%;
    }
    #command-table > DataTable.row:focus {
        background: $accent;
        color: $text;
    }
    """

    BINDINGS = [
        ("ctrl+c", "cancel", "Cancel"),
        ("ctrl+shift+c", "copy_selection", "Copy"),
        ("ctrl+e", "expand", "Expand"),
        ("ctrl+d", "diff_view", "Diff"),
        ("ctrl+s", "save_output", "Save Output"),
        ("f2", "switch_model", "Model"),
        ("/", "toggle_palette", "Commands"),
    ]

    _orchestrator = None
    _metrics: TUIMetrics = reactive(lambda: TUIMetrics())  # type: ignore[assignment,return-value,arg-type]
    _last_result_full = ""
    _last_task = ""
    _expanded = False
    _output_buffer: str = ""
    CLIPBOARD_READ_COMMAND: str | None = ""

    # Command palette state
    _command_palette_open = False
    _filtered_commands: list[dict] = []
    _selected_index = 0
    _all_commands: list[dict] = []

    def __init__(self, orchestrator=None, **kwargs):
        super().__init__(**kwargs)
        self._orchestrator = orchestrator
        self._session_file = Path.home() / ".noman" / "sessions" / "active_session.md"

    def compose(self) -> ComposeResult:
        with Container():
            with Horizontal(id="header"):
                yield Static("NoMan v0.0.01", id="status")
            yield TrackedRichLog(id="output", markup=True, wrap=True, allow_select=True)
            # Command palette (hidden by default, floats above input)
            with Container(id="command-palette"):
                yield Label("[dim]type to filter[/dim]", id="palette-title")
                yield DataTable(id="command-table")
            with Horizontal(id="input-area"):
                yield Input(
                    placeholder="Enter task... (type / for commands)",
                    id="input",
                    valid_empty=False,
                )

    def on_mount(self) -> None:
        self.update_status()
        self.query_one("#input", Input).focus()
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
            tool_list = ', '.join(tools[:10])
            suffix = '...' if len(tools) > 10 else ''
            print(f"[LOG] Loaded {len(tools)} tools: {tool_list}{suffix}")

    # ── Command palette ──────────────────────────────────────────────

    def action_toggle_palette(self) -> None:
        """Show/hide the command palette."""
        if self._command_palette_open:
            self._hide_command_palette()
        else:
            self._show_command_palette()

    def _build_command_list(self, filter_text: str = "") -> list[dict]:
        """Build the list of available commands, optionally filtered."""
        commands = [
            {
                "label": "/reset       — Reset current session",
                "value": "/reset",
                "id": "cmd-reset",
            },
            {
                "label": "/diff        — Show file edits (Ctrl+D)",
                "value": "/diff",
                "id": "cmd-diff",
            },
            {
                "label": "/save        — Save output to file (Ctrl+S)",
                "value": "/save",
                "id": "cmd-save",
            },
            {
                "label": "/model       — Switch provider (F2)",
                "value": "/model",
                "id": "cmd-model",
            },
            {
                "label": "/help        — Show this help",
                "value": "/help",
                "id": "cmd-help",
            },
            {
                "label": "/exit        — Exit NoMan",
                "value": "/exit",
                "id": "cmd-exit",
            },
            {
                "label": "/wiki_init   — Build knowledge graph for this project",
                "value": "/wiki_init",
                "id": "cmd-wiki-init",
            },
            {
                "label": "/wiki_summary — Show graph stats",
                "value": "/wiki_summary",
                "id": "cmd-wiki-summary",
            },
            {
                "label": "/wiki_list    — List entities",
                "value": "/wiki_list",
                "id": "cmd-wiki-list",
            },
            {
                "label": "/wiki_search  — Search wiki pages",
                "value": "/wiki_search",
                "id": "cmd-wiki-search",
            },
            {
                "label": "/wiki_lint    — Health check",
                "value": "/wiki_lint",
                "id": "cmd-wiki-lint",
            },
            {
                "label": "/wiki_query   — Query graph (neighbors)",
                "value": "/wiki_query",
                "id": "cmd-wiki-query",
            },
            {
                "label": "/wiki_pages   — Get a wiki page",
                "value": "/wiki_pages",
                "id": "cmd-wiki-pages",
            },
            {
                "label": "/wiki_semantic — Concept search",
                "value": "/wiki_semantic",
                "id": "cmd-wiki-semantic",
            },
            {
                "label": "/wiki_dedup   — Deduplicate entities",
                "value": "/wiki_dedup",
                "id": "cmd-wiki-dedup",
            },
            {
                "label": "/wiki_sync    — Incremental sync",
                "value": "/wiki_sync",
                "id": "cmd-wiki-sync",
            },
            {
                "label": "/wiki_save_ver — Save wiki version",
                "value": "/wiki_save_ver",
                "id": "cmd-wiki-save-ver",
            },
            {
                "label": "/wiki_auto_link — Auto cross-link",
                "value": "/wiki_auto_link",
                "id": "cmd-wiki-auto-link",
            },
            {
                "label": "/wiki_ascii   — ASCII graph render",
                "value": "/wiki_ascii",
                "id": "cmd-wiki-ascii",
            },
            {
                "label": "/wiki_mermaid — Mermaid graph render",
                "value": "/wiki_mermaid",
                "id": "cmd-wiki-mermaid",
            },
            {
                "label": "/wiki_hotspots — High-risk entities",
                "value": "/wiki_hotspots",
                "id": "cmd-wiki-hotspots",
            },
            {
                "label": "/wiki_cross_links — Cross-project links",
                "value": "/wiki_cross_links",
                "id": "cmd-wiki-cross-links",
            },
            {
                "label": "/wiki_index   — Index/catalog",
                "value": "/wiki_index",
                "id": "cmd-wiki-index",
            },
            {
                "label": "/wiki_ingest  — Ingest file/conversation",
                "value": "/wiki_ingest",
                "id": "cmd-wiki-ingest",
            },
        ]
        if not filter_text:
            return commands
        lower = filter_text.lower()
        return [c for c in commands if lower in c["label"].lower() or lower in c["value"].lower()]

    def _populate_table(self, commands: list[dict]) -> None:
        """Populate the DataTable with command rows."""
        table = self.query_one("#command-table", DataTable)
        table.clear(columns=True)
        table.cursor_type = "row"
        table.add_columns("Command", "Description")
        for i, cmd in enumerate(commands):
            label = cmd["label"].split("—")[0].strip()
            desc = cmd["label"].split("—")[1].strip() if "—" in cmd["label"] else ""
            table.add_row(label, desc, key=str(i))
        self._filtered_commands = commands
        self._selected_index = 0
        if commands:
            from textual.coordinate import Coordinate
            table.cursor_coordinate = Coordinate(0, 0)

    def _filter_palette(self, filter_text: str = "") -> None:
        """Filter and re-populate the command table."""
        commands = self._build_command_list(filter_text)
        self._populate_table(commands)

    def _show_command_palette(self, filter_text: str = "") -> None:
        """Show the command palette above the input area."""
        if self._command_palette_open:
            self._filter_palette(filter_text)
            return
        self._command_palette_open = True
        palette = self.query_one("#command-palette", Container)
        palette.add_class("visible")
        self._filter_palette(filter_text)

    def _hide_command_palette(self) -> None:
        """Hide the command palette."""
        self._command_palette_open = False
        palette = self.query_one("#command-palette", Container)
        palette.remove_class("visible")
        self.query_one("#input", Input).focus()

    def _execute_command(self, cmd: str) -> None:
        """Execute a command from the palette and close it."""
        self._hide_command_palette()
        input_widget = self.query_one("#input", Input)
        input_widget.value = cmd
        input_widget.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection in the command table."""
        if not self._command_palette_open:
            return
        row_key = event.row_key
        if row_key is not None and row_key.value is not None:
            try:
                idx = int(row_key.value)
                if 0 <= idx < len(self._filtered_commands):
                    cmd = self._filtered_commands[idx]["value"]
                    self._execute_command(cmd)
            except (ValueError, TypeError):
                pass

    def on_input_key(self, event: Key) -> None:
        """Handle arrow keys on the input while palette is open."""
        if not self._command_palette_open:
            return
        if event.key == "arrow_down":
            if self._filtered_commands:
                new_idx = min(self._selected_index + 1, len(self._filtered_commands) - 1)
                self._selected_index = new_idx
                table = self.query_one("#command-table", DataTable)
                from textual.coordinate import Coordinate
                table.cursor_coordinate = Coordinate(new_idx, 0)
                event.stop()
                return
        if event.key == "arrow_up":
            if self._filtered_commands:
                new_idx = max(self._selected_index - 1, 0)
                self._selected_index = new_idx
                table = self.query_one("#command-table", DataTable)
                from textual.coordinate import Coordinate
                table.cursor_coordinate = Coordinate(new_idx, 0)
                event.stop()
                return
        if event.key == "enter":
            if self._filtered_commands and self._selected_index < len(self._filtered_commands):
                cmd = self._filtered_commands[self._selected_index]["value"]
                self._execute_command(cmd)
                event.stop()
                return
        if event.key == "escape":
            self._hide_command_palette()
            event.stop()
            return

    def on_key(self, event: Key) -> None:
        """Handle keyboard events for palette navigation."""
        if not self._command_palette_open:
            return

        table = self.query_one("#command-table", DataTable)
        from textual.coordinate import Coordinate

        # ArrowDown — move selection down
        if event.key == "arrow_down":
            if self._filtered_commands:
                new_idx = min(self._selected_index + 1, len(self._filtered_commands) - 1)
                self._selected_index = new_idx
                table.cursor_coordinate = Coordinate(new_idx, 0)
                event.stop()
                return

        # ArrowUp — move selection up
        if event.key == "arrow_up":
            if self._filtered_commands:
                new_idx = max(self._selected_index - 1, 0)
                self._selected_index = new_idx
                table.cursor_coordinate = Coordinate(new_idx, 0)
                event.stop()
                return

        # Enter — execute selected command
        if event.key == "enter":
            if self._filtered_commands and self._selected_index < len(self._filtered_commands):
                cmd = self._filtered_commands[self._selected_index]["value"]
                self._execute_command(cmd)
                event.stop()
                return

        # Escape — close palette
        if event.key == "escape":
            self._hide_command_palette()
            event.stop()
            return

    def on_input_changed(self, event: Input.Changed) -> None:
        """Show/hide command palette when user types in the input field."""
        input_value = event.value
        if not input_value or input_value.isspace():
            self._hide_command_palette()
            return
        if input_value.startswith("/"):
            self._show_command_palette(input_value)
        else:
            self._hide_command_palette()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter in the input field."""
        if self._command_palette_open:
            # Let the palette handle Enter via on_data_table_row_selected
            return
        self.action_submit()

    # ── Session management ───────────────────────────────────────────

    def _load_session(self, content: str) -> None:
        """Load session content into the output log."""
        output = self.query_one("#output", TrackedRichLog)
        output.clear()
        lines = content.split("\n")
        in_history = False
        for line in lines:
            if line.startswith("# Active Session"):
                in_history = True
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                output.write(f"[dim]# Session started: {ts}[/dim]\n")
                continue
            if in_history and line.startswith("> "):
                session_text = line[2:]
                if session_text.startswith("❯ "):
                    output.write(f"\n[b]{session_text}[/b]\n")
                elif session_text.strip():
                    output.write(f"{session_text}\n")
            elif (in_history and line.strip()
                    and not line.startswith("---")
                    and not line.startswith("#")
                    and not line.startswith(">")):
                output.write(f"{line}\n")

    def _update_session_status(self) -> None:
        """Update status bar to show session state."""
        status = self.query_one("#status", Static)
        if self._session_file.exists():
            try:
                content = self._session_file.read_text()
                task_count = content.count("❯ ")
                size_kb = self._session_file.stat().st_size / 1024
                turn = self._metrics.turn_count
                status.update(f"Turn {turn} | {task_count} tasks | {size_kb:.1f}KB")
            except Exception:
                status.update(f"Turn {self._metrics.turn_count} | session loaded")
        else:
            status.update(f"Turn {self._metrics.turn_count} | new session")

    # ── Actions ──────────────────────────────────────────────────────

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

    def action_copy_selection(self) -> None:
        """Copy output content to clipboard."""
        try:
            import pyperclip
            output = self.query_one("#output", TrackedRichLog)
            pyperclip.copy(output.content)
            self.notify("Output copied to clipboard")
        except ImportError:
            self.notify("pip install pyperclip for copy support")

    def action_expand(self) -> None:
        self._expanded = not self._expanded
        output = self.query_one("#output", TrackedRichLog)
        if self._expanded:
            output.wrap = True
        else:
            output.wrap = True  # always wrap for readability

    def action_diff_view(self) -> None:
        output = self.query_one("#output", TrackedRichLog)
        output.clear()

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
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_path = session_dir / f"output_{ts}.txt"
        file_path.write_text(content)
        self.notify(f"Saved to {file_path}", severity="information")

    def _handle_command(self, task: str) -> bool:
        """Handle special commands. Returns True if command was handled."""
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
        if task == "/wiki_init":
            return self._run_wiki_command("wiki_init", {})
        if task == "/wiki_summary":
            return self._run_wiki_command("wiki_graph_summary", {})
        if task == "/wiki_list":
            return self._run_wiki_command("wiki_list_entities", {})
        if task.startswith("/wiki_search"):
            query = task[len("/wiki_search"):].strip()
            if not query:
                self._notify_with_output("Usage: /wiki_search <query>", "warning")
                return True
            return self._run_wiki_command("wiki_search_pages", {"query": query})
        if task == "/wiki_lint":
            return self._run_wiki_command("wiki_lint", {})
        if task == "/wiki_query":
            query = task[len("/wiki_query"):].strip()
            if not query:
                self._notify_with_output("Usage: /wiki_query <entity_id>", "warning")
                return True
            return self._run_wiki_command("wiki_query_graph", {"entity_id": query})
        if task.startswith("/wiki_pages"):
            page_id = task[len("/wiki_pages"):].strip()
            if not page_id:
                self._notify_with_output("Usage: /wiki_pages <page_id>", "warning")
                return True
            return self._run_wiki_command("wiki_get_page", {"page_id": page_id})
        if task == "/wiki_semantic":
            query = task[len("/wiki_semantic"):].strip()
            if not query:
                self._notify_with_output("Usage: /wiki_semantic <query>", "warning")
                return True
            return self._run_wiki_command("wiki_semantic_search", {"query": query})
        if task == "/wiki_dedup":
            return self._run_wiki_command("wiki_dedup", {})
        if task == "/wiki_sync":
            return self._run_wiki_command("wiki_sync", {})
        if task.startswith("/wiki_save_ver"):
            version_name = task[len("/wiki_save_ver"):].strip() or "default"
            return self._run_wiki_command("wiki_save_version", {"name": version_name})
        if task == "/wiki_auto_link":
            return self._run_wiki_command("wiki_auto_link", {})
        if task == "/wiki_ascii":
            entity_id = task[len("/wiki_ascii"):].strip() or None
            return self._run_wiki_command("wiki_enhanced_ascii", {"entity_id": entity_id} if entity_id else {})
        if task == "/wiki_mermaid":
            entity_id = task[len("/wiki_mermaid"):].strip() or None
            return self._run_wiki_command("wiki_enhanced_mermaid", {"entity_id": entity_id} if entity_id else {})
        if task == "/wiki_hotspots":
            return self._run_wiki_command("wiki_hotspots", {})
        if task == "/wiki_cross_links":
            return self._run_wiki_command("wiki_cross_links", {})
        if task == "/wiki_index":
            return self._run_wiki_command("wiki_index", {})
        if task.startswith("/wiki_ingest"):
            file_path = task[len("/wiki_ingest"):].strip()
            if not file_path:
                self._notify_with_output("Usage: /wiki_ingest <file_path>", "warning")
                return True
            return self._run_wiki_command("wiki_auto_extract", {"file_path": file_path})
        return False

    def _reset_session(self) -> None:
        """Reset the current session — clear orchestrator, output, and session file."""
        if self._orchestrator:
            self._orchestrator.reset_session()

        output = self.query_one("#output", TrackedRichLog)
        output.clear()

        if self._session_file.exists():
            try:
                self._session_file.unlink()
            except Exception:
                pass

        self._metrics.turn_count = 0
        self._metrics.state = TUIState.IDLE
        self.update_status()
        self.notify("Session reset", severity="information")

    def _run_wiki_command(self, tool_name: str, args: dict) -> bool:
        """Run a wiki tool command and display the result in the output."""
        if not self._orchestrator:
            self.notify("NoMan not initialized yet", severity="warning")
            return True

        output = self.query_one("#output", TrackedRichLog)
        output.clear()
        output.write(f"[dim]# Running /{tool_name}...[/dim]\n")

        # Use the tool bus execute directly (it's async but Textual's event loop handles it)
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                future = asyncio.ensure_future(
                    self._orchestrator.tool_bus.execute(tool_name, args),
                    loop=loop
                )

                def _on_done(fut):
                    try:
                        result = fut.result()
                        self.call_next(lambda r=result: output.write(f"[bold]Result:[/bold]\n{r}"))
                    except Exception as err:
                        self.call_next(lambda e=err: output.write(f"[red]Error: {e}[/red]"))
                    self.call_next(self.update_status)

                future.add_done_callback(_on_done)
            else:
                # No running loop — use asyncio.run in a thread
                import threading
                def _run():
                    result = asyncio.run(self._orchestrator.tool_bus.execute(tool_name, args))
                    self.call_next(lambda r=result: output.write(f"[bold]Result:[/bold]\n{r}"))
                    self.call_next(self.update_status)
                t = threading.Thread(target=_run, daemon=True)
                t.start()
        except Exception as exc:
            output.write(f"[red]Error running command: {exc}[/red]")
            self.call_next(self.update_status)
        return True

    def _notify_with_output(self, message: str, severity: str = "information") -> None:
        """Show a notification and display the message in the output."""
        self.notify(message, severity=severity)
        output = self.query_one("#output", TrackedRichLog)
        output.write(f"[{severity}]{message}[/{severity}]")

    def _convert_markdown_to_textual(self, text: str) -> list:
        """Convert markdown to Rich Text objects."""
        from rich.text import Text

        lines = []
        in_code = False

        for line in text.split("\n"):
            if line.strip().startswith("```"):
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

    async def run_task(self, task: str) -> None:
        try:
            self._metrics.state = TUIState.INITIALIZING
            self.call_next(self.update_status)
            self.call_next(self.hide_input)

            output = self.query_one("#output", TrackedRichLog)
            output.write(f"\n[b]❯ {task}[/b]\n")

            self._metrics.state = TUIState.RUNNING
            self.call_next(self.update_status)

            if self._orchestrator:
                result = await self._orchestrator.run(task)
                self._last_result_full = result
                self._last_task = task

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
