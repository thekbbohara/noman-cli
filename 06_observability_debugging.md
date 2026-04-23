## 6. Observability & Debugging

### 6.1 Telemetry Schema

```toml
# user/config.toml

[observability]
log_level = "info"  # debug | info | warn | error
trace_retention_days = 30
export_traces_on_error = true
log_file = ".noman/logs/noman.log"
```

### 6.2 Logged Events

```python
# core/observability/logger.py

from enum import Enum
from dataclasses import dataclass
from datetime import datetime

class EventType(Enum):
    TOOL_CALL = "tool_call"
    MEMORY_OP = "memory_op"
    CONTEXT_LOAD = "context_load"
    BUDGET_STATE = "budget_state"
    SELF_IMPROVE = "self_improve"
    ERROR = "error"

@dataclass
class Event:
    timestamp: datetime
    event_type: EventType
    session_id: str
    trace_id: str
    data: dict
    metadata: dict  # {line_number, function_name, etc.}

class TelemetryLogger:
    """Local-only telemetry logger."""
    
    def __init__(self, log_dir: str, retention_days: int = 30):
        self.log_dir = Path(log_dir)
        self.retention_days = retention_days
        self.buffer = []
    
    def log(self, event: Event):
        """Log an event."""
        self.buffer.append(event)
        
        # Flush periodically
        if len(self.buffer) >= 100:
            self.flush()
    
    def flush(self):
        """Write buffered events to disk."""
        if not self.buffer:
            return
        
        # Append to daily log file
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = self.log_dir / f"events-{today}.jsonl"
        
        with open(log_file, "a") as f:
            for event in self.buffer:
                f.write(json.dumps(self._serialize(event)) + "\n")
        
        self.buffer.clear()
        self._cleanup_old_logs()
    
    def _cleanup_old_logs(self):
        """Delete logs older than retention period."""
        cutoff = datetime.now() - timedelta(days=self.retention_days)
        for log_file in self.log_dir.glob("events-*.jsonl"):
            file_date = datetime.strptime(log_file.stem, "events-%Y-%m-%d")
            if file_date < cutoff:
                log_file.unlink()
```

### 6.3 Debug Commands Implementation

```python
# cli/commands/debug.py

@click.group()
def debug():
    """Debug and inspection commands."""
    pass

@debug.command("last-turn")
def debug_last_turn():
    """Show full prompt sent to LLM in last turn."""
    trace = get_latest_trace()
    last_turn = trace["turns"][-1]
    
    console = Console()
    console.print("[bold]Full Prompt:[/bold]")
    console.print(last_turn["full_prompt"])
    console.print(f"\n[dim]Tokens: {last_turn['prompt_tokens']}[/dim]")

@debug.command("trace")
@click.argument("trace_id")
def debug_trace(trace_id):
    """Replay a past trace step-by-step."""
    trace = load_trace(trace_id)
    
    console = Console()
    for i, turn in enumerate(trace["turns"]):
        console.print(f"\n[bold]Turn {i+1}[/bold]")
        console.print(f"Thought: {turn.get('thought', 'N/A')}")
        console.print(f"Tool: {turn.get('tool_call', 'None')}")
        console.print(f"Result: {turn.get('tool_result', 'N/A')[:200]}...")

@debug.command("memory-query")
@click.argument("query")
def debug_memory_query(query):
    """Show what memories would be retrieved for a query."""
    memories = recall(query, top_k=10)
    
    console = Console()
    console.print(f"[bold]Top memories for '{query}':[/bold]\n")
    for mem in memories:
        console.print(f"- [{mem['tier']}] {mem['key']}: {mem['value'][:100]}...")
        console.print(f"  [dim]Score: {mem['score']:.3f}[/dim]")

@debug.command("context-budget")
def debug_context_budget():
    """Show current token allocation across slots."""
    budget = get_current_budget()
    
    console = Console()
    table = Table(title="Token Budget Allocation")
    table.add_column("Slot", style="cyan")
    table.add_column("Allocated", justify="right")
    table.add_column("Used", justify="right")
    table.add_column("Available", justify="right")
    
    for slot, info in budget.items():
        table.add_row(
            slot,
            str(info["allocated"]),
            str(info["used"]),
            str(info["available"])
        )
    
    console.print(table)
```

### 6.4 Implementation Tasks

| Task | File(s) | Priority | Dependencies |
|------|---------|----------|--------------|
| Telemetry logger | `core/observability/logger.py` | P0 | None |
| Trace viewer | `core/observability/traces.py` | P0 | Self-improve |
| Debug CLI commands | `cli/commands/debug.py` | P1 | All subsystems |
| Log rotation | `core/observability/rotation.py` | P1 | Logger |
| Metrics exporter | `core/observability/metrics.py` | P2 | Logger |

---

