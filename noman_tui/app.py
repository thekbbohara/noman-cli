"""
Noman TUI - The Agent-Native Coding Environment
"""
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Input, Log, ContentSwitcher, TabPane, Tabs
from textual.widgets import FileTree, Static, Label
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.binding import Binding
from textual.reactive import reactive
from textual import events
from typing import Generator

# --- Custom Widgets ---

class ChatStream(Log):
    """The main chat history."""
    
    def on_mount(self):
        self.write("Welcome to Noman. How can I help you code today?")

class DiffView(Static):
    """Interactive diff viewer."""
    CSS = """
    DiffView {
        dock: bottom;
        height: 100%;
        background: $surface;
        color: $text;
    }
    """
    
    def on_mount(self) -> None:
        self.update("[b]Diff View[/b]\n\nReady for changes...")

    def add_hunk(self, filename: str, content: str):
        self.update(f"[b]{filename}[/b]\n\n{content}\n\n[b]Actions:[/b] (A)ll, (R)eject, or [Enter] to ignore")

class CodePreview(Static):
    """Live code preview."""
    CSS = """
    CodePreview {
        dock: right;
        width: 3fr;
        background: $surface;
    }
    """
    
    def on_mount(self) -> None:
        self.update("[b]Code Preview[/b]\n\nSelect a file to view.")

class FileExplorer(FileTree):
    """Enhanced file explorer."""
    CSS = """
    FileExplorer {
        dock: left;
        width: 25%;
        background: $surface;
    }
    """

# --- Main App ---

class NomanApp(App):
    """Noman Coding Agent Interface."""
    
    BINDINGS = [
        Binding("ctrl+l", "toggle_explorer", "Explorer"),
        Binding("ctrl+d", "toggle_diff", "Diff"),
        Binding("ctrl+t", "toggle_terminal", "Terminal"),
        Binding("escape", "reset_focus", "Reset Focus"),
    ]
    
    CSS = """
    Screen {
        layout: grid;
        grid-size: 2;
        grid-gutter: 1;
        padding: 1;
    }

    #main-pane {
        grid-columns: 1fr 2fr;
        height: 100%;
    }

    #center-pane {
        layout: vertical;
        height: 1fr;
    }

    #bottom-pane {
        layout: horizontal;
        height: 30%;
    }

    .panel {
        border: round $primary;
        padding: 1;
        margin: 1;
        background: $surface-darken-1;
    }

    #chat-stream {
        height: 1fr;
        margin-bottom: 1;
        border: round $primary;
    }

    #input-area {
        height: auto;
        margin-bottom: 1;
    }

    #diff-view {
        width: 70%;
        border: round $success;
    }

    #terminal-output {
        width: 30%;
        border: round $warning;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        
        # Main Container
        with Container(id="main-pane"):
            # Left: Explorer
            yield FileExplorer(id="explorer", path=".")
            
            # Center: Chat & Input
            with Container(id="center-pane", classes="panel"):
                yield ChatStream(id="chat-stream")
                with Container(id="input-area"):
                    yield Input(placeholder="Ask Noman to code...", id="user-input")
        
        # Bottom: Diff & Terminal
        with Container(id="bottom-pane"):
            yield DiffView(id="diff-view")
            yield Log(id="terminal-output", id="terminal-output")
            
        yield Footer()

    # --- Actions ---
    
    def on_input_submitted(self, event: Input.Changed) -> None:
        """Handle user input."""
        user_text = event.value
        if not user_text.strip():
            return
        
        # 1. Echo to chat
        self.query_one("#chat-stream", ChatStream).write(f"[b]You:[/b] {user_text}")
        
        # 2. Clear input
        self.query_one("#user-input", Input).value = ""
        
        # 3. Simulate Agent Response (Placeholder for Orchestrator logic)
        self.run_worker(self.process_command(user_text))

    async def process_command(self, command: str) -> None:
        """Simulate the Orchestrator processing a command."""
        chat = self.query_one("#chat-stream", ChatStream)
        chat.write(f"[b]Noman:[/b] Processing...")
        
        # Simulate "Coder" agent work
        chat.write(f"[b]Noman:[/b] Coder agent is working on '{command}'...")
        
        # Simulate "Diff" generation
        diff_view = self.query_one("#diff-view", DiffView)
        diff_view.add_hunk("example.py", "+ def new_function():\n+     return True")
        
        chat.write(f"[b]Noman:[/b] Changes ready for review in Diff Pane.")

if __name__ == "__main__":
    app = NomanApp()
    app.run()
