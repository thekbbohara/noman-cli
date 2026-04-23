## 4. CLI Surface

### 4.1 Command Reference

```bash
# Core Commands
noman init                      # Scaffold .noman/, build initial skeleton
noman                           # Interactive REPL
noman "do X"                    # One-shot task execution
noman --explain "do X"          # Execute with reasoning trace

# Review & Control
noman review                    # Review pending agent self-modifications
noman rollback [N]              # Revert last N overlay changes
noman approve <patch-id>        # Approve specific pending change

# Diagnostics
noman doctor                    # Health check (DB, patches, capabilities)
noman stats                     # Token usage, success rates, memory size
noman debug last-turn           # Show full prompt from last turn
noman debug trace <id>          # Replay past trace step-by-step
noman debug memory-query "X"    # Preview memory retrieval for query
noman debug context-budget      # Show current token allocation
noman debug tool-costs          # Historical costs per tool

# Memory Management
noman memory ls [tier]          # List memories (optionally by tier)
noman memory search "query"     # Search memories
noman memory export <path>      # Export memory to JSON
noman memory import <path>      # Import memory from JSON
noman memory forget <id>        # Delete specific memory

# Skill Management
noman skill ls                  # List available skills
noman skill show <name>         # Show skill details
noman skill disable <name>      # Disable a skill
noman skill enable <name>       # Re-enable a skill

# Collaboration (future)
noman collaboration sync        # Sync team memory
noman collaboration resolve     # Resolve sync conflicts

# Utility
noman config edit               # Open config in editor
noman config validate           # Validate config syntax
noman --version                 # Show version
noman --help                    # Show help
```

### 4.2 REPL Mode

```python
# cli/repl.py

import readline
from rich.console import Console
from rich.markdown import Markdown

class NoManREPL:
    """Interactive REPL for NoMan."""
    
    def __init__(self, orchestrator):
        self.orchestrator = orchestrator
        self.console = Console()
        self.history = []
        self.session_id = uuid4()
    
    def run(self):
        """Main REPL loop."""
        self.console.print(Markdown("# NoMan CLI"))
        self.console.print("[dim]Type 'exit' to quit, 'help' for commands[/dim]\n")
        
        while True:
            try:
                user_input = input("❯ ").strip()
                
                if user_input.lower() in ["exit", "quit"]:
                    break
                
                if user_input.startswith("/"):
                    self._handle_command(user_input)
                else:
                    self._handle_task(user_input)
            
            except KeyboardInterrupt:
                self.console.print("\n[dim]Interrupted. Type 'exit' to quit.[/dim]")
            except EOFError:
                break
    
    def _handle_task(self, task: str):
        """Execute a task through the orchestrator."""
        self.console.print("\n[bold blue]Thinking...[/bold blue]")
        
        result = await self.orchestrator.orchestrate(
            task,
            session_id=self.session_id
        )
        
        if result.success:
            self.console.print(Markdown(result.response))
        else:
            self.console.print(f"[red]Error: {result.error}[/red]")
    
    def _handle_command(self, cmd: str):
        """Handle REPL-specific commands (/help, /stats, etc.)."""
        parts = cmd[1:].split(maxsplit=1)
        command = parts[0]
        args = parts[1] if len(parts) > 1 else ""
        
        handlers = {
            "help": self._cmd_help,
            "stats": self._cmd_stats,
            "history": self._cmd_history,
            "clear": self._cmd_clear,
        }
        
        if command in handlers:
            handlers[command](args)
        else:
            self.console.print(f"[red]Unknown command: /{command}[/red]")
```

### 4.3 Implementation Tasks

| Task | File(s) | Priority | Dependencies |
|------|---------|----------|--------------|
| CLI argument parser | `cli/main.py` | P0 | None |
| REPL implementation | `cli/repl.py` | P0 | Orchestrator |
| Init command | `cli/commands/init.py` | P0 | Context mgmt |
| Doctor command | `cli/commands/doctor.py` | P0 | All subsystems |
| Review command | `cli/commands/review.py` | P1 | Self-improve |
| Memory commands | `cli/commands/memory.py` | P1 | Memory system |
| Skill commands | `cli/commands/skills.py` | P1 | Self-improve |
| Debug commands | `cli/commands/debug.py` | P1 | All subsystems |
| Stats command | `cli/commands/stats.py` | P2 | Observability |

---

