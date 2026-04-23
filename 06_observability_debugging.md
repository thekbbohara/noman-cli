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

### 6.4 Distributed Tracing (NEW)

**Problem:** No distributed tracing, making it hard to trace requests across subsystems.

**Solution:** OpenTelemetry-compatible tracing with correlation IDs.

```python
# core/observability/tracing.py

from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict
import uuid
import time

# Context-local trace state
current_trace_id: ContextVar[str] = ContextVar("trace_id", default="")
current_span_id: ContextVar[str] = ContextVar("span_id", default="")


@dataclass
class Span:
    """A single span in a distributed trace."""
    trace_id: str
    span_id: str
    parent_span_id: Optional[str]
    operation_name: str
    start_time: float
    end_time: Optional[float] = None
    tags: Dict[str, str] = field(default_factory=dict)
    logs: List[Dict] = field(default_factory=list)
    error: Optional[Exception] = None
    
    def duration_ms(self) -> float:
        if self.end_time is None:
            return 0.0
        return (self.end_time - self.start_time) * 1000
    
    def set_tag(self, key: str, value: str):
        self.tags[key] = value
    
    def log(self, event: str, **kwargs):
        self.logs.append({
            "timestamp": time.time(),
            "event": event,
            **kwargs
        })
    
    def finish(self, error: Exception = None):
        self.end_time = time.time()
        if error:
            self.error = error
            self.set_tag("error", str(error))


class Tracer:
    """Distributed tracer with OpenTelemetry compatibility."""
    
    def __init__(self, service_name: str = "noman"):
        self.service_name = service_name
        self.spans: List[Span] = []
        self.export_endpoint: Optional[str] = None  # OTLP endpoint
    
    def start_trace(self, operation_name: str) -> Span:
        """Start a new trace."""
        trace_id = str(uuid.uuid4())
        span_id = str(uuid.uuid4())[:16]
        
        span = Span(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=None,
            operation_name=operation_name,
            start_time=time.time()
        )
        
        # Set context
        current_trace_id.set(trace_id)
        current_span_id.set(span_id)
        
        span.set_tag("service", self.service_name)
        self.spans.append(span)
        
        return span
    
    def start_span(self, operation_name: str, child_of: Span = None) -> Span:
        """Start a child span."""
        trace_id = current_trace_id.get() or str(uuid.uuid4())
        parent_span_id = child_of.span_id if child_of else current_span_id.get()
        span_id = str(uuid.uuid4())[:16]
        
        span = Span(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            operation_name=operation_name,
            start_time=time.time()
        )
        
        current_span_id.set(span_id)
        span.set_tag("service", self.service_name)
        self.spans.append(span)
        
        return span
    
    def inject_context(self, carrier: dict):
        """Inject trace context into carrier for propagation."""
        carrier["traceparent"] = f"00-{current_trace_id.get()}-{current_span_id.get()}-01"
    
    def extract_context(self, carrier: dict) -> Optional[Span]:
        """Extract trace context from carrier."""
        if "traceparent" not in carrier:
            return None
        
        parts = carrier["traceparent"].split("-")
        if len(parts) != 4:
            return None
        
        trace_id, span_id = parts[1], parts[2]
        current_trace_id.set(trace_id)
        current_span_id.set(span_id)
        
        return Span(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=None,
            operation_name="extracted",
            start_time=time.time()
        )
    
    def export_spans(self):
        """Export spans to backend (Jaeger, Zipkin, etc.)."""
        # In production, would use OTLP exporter
        # For now, just log
        for span in self.spans:
            if span.end_time:
                logger.info(f"Trace {span.trace_id}: {span.operation_name} took {span.duration_ms():.2f}ms")


# Global tracer instance
tracer = Tracer()
```

### 6.5 Log Volume Management (NEW)

**Problem:** Unmanaged log volume can fill disk quickly.

**Solution:** Structured logging with rotation, sampling, and level-based filtering.

```python
# core/observability/log_rotation.py

import logging
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pathlib import Path
import json
from datetime import datetime


class StructuredJsonFormatter(logging.Formatter):
    """Format logs as JSON for easier parsing."""
    
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        
        # Add extra fields
        for key, value in record.__dict__.items():
            if key not in ["msg", "args", "levelname", "levelno", "pathname", 
                          "filename", "module", "lineno", "funcName", "created",
                          "msecs", "relativeCreated", "thread", "threadName",
                          "processName", "process", "message"]:
                log_entry[key] = value
        
        return json.dumps(log_entry)


def setup_logging(
    log_dir: str,
    level: str = "INFO",
    max_size_mb: int = 100,
    backup_count: int = 10,
    sample_rate: float = 1.0  # 1.0 = log everything, 0.1 = 10% sampling
) -> logging.Logger:
    """
    Setup structured logging with rotation.
    
    Args:
        log_dir: Directory for log files
        level: Minimum log level
        max_size_mb: Max size per log file before rotation
        backup_count: Number of backup files to keep
        sample_rate: Sampling rate for DEBUG logs
    """
    logger = logging.getLogger("noman")
    logger.setLevel(getattr(logging, level.upper()))
    
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    
    # Main log file with size-based rotation
    main_handler = RotatingFileHandler(
        log_path / "noman.log",
        maxBytes=max_size_mb * 1024 * 1024,
        backupCount=backup_count
    )
    main_handler.setFormatter(StructuredJsonFormatter())
    logger.addHandler(main_handler)
    
    # Error log with separate file
    error_handler = RotatingFileHandler(
        log_path / "error.log",
        maxBytes=max_size_mb * 1024 * 1024,
        backupCount=backup_count
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(StructuredJsonFormatter())
    logger.addHandler(error_handler)
    
    # Console handler for interactive sessions
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))
    logger.addHandler(console_handler)
    
    return logger


class SampledLogger:
    """Logger that samples DEBUG messages to reduce volume."""
    
    def __init__(self, logger: logging.Logger, sample_rate: float = 0.1):
        self.logger = logger
        self.sample_rate = sample_rate
        self._counter = 0
    
    def debug(self, msg, *args, **kwargs):
        self._counter += 1
        if self._counter % int(1 / self.sample_rate) == 0:
            self.logger.debug(msg, *args, **kwargs)
    
    def info(self, msg, *args, **kwargs):
        self.logger.info(msg, *args, **kwargs)
    
    def warning(self, msg, *args, **kwargs):
        self.logger.warning(msg, *args, **kwargs)
    
    def error(self, msg, *args, **kwargs):
        self.logger.error(msg, *args, **kwargs)
```

### 6.6 Metrics Aggregation (NEW)

**Problem:** No metrics aggregation for monitoring system health.

**Solution:** Prometheus-compatible metrics with histograms, counters, and gauges.

```python
# core/observability/metrics.py

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import time
import statistics


@dataclass
class MetricSample:
    timestamp: float
    value: float
    labels: Dict[str, str] = field(default_factory=dict)


class Counter:
    """Monotonically increasing counter metric."""
    
    def __init__(self, name: str, description: str, labels: List[str] = None):
        self.name = name
        self.description = description
        self.labels = labels or []
        self._values: Dict[str, int] = defaultdict(int)
    
    def inc(self, value: int = 1, **label_values):
        key = self._make_key(label_values)
        self._values[key] += value
    
    def get(self, **label_values) -> int:
        key = self._make_key(label_values)
        return self._values[key]
    
    def _make_key(self, label_values: dict) -> str:
        return ",".join(f"{k}={v}" for k, v in sorted(label_values.items()))


class Histogram:
    """Distribution metric for tracking latencies and sizes."""
    
    def __init__(
        self,
        name: str,
        description: str,
        buckets: List[float] = None,
        labels: List[str] = None
    ):
        self.name = name
        self.description = description
        self.buckets = buckets or [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
        self.labels = labels or []
        self._samples: Dict[str, List[float]] = defaultdict(list)
    
    def observe(self, value: float, **label_values):
        key = self._make_key(label_values)
        self._samples[key].append(value)
    
    def get_percentiles(self, **label_values) -> Dict[str, float]:
        key = self._make_key(label_values)
        samples = self._samples[key]
        if not samples:
            return {}
        
        return {
            "p50": statistics.quantiles(samples, n=100)[49],
            "p90": statistics.quantiles(samples, n=100)[89],
            "p99": statistics.quantiles(samples, n=100)[98],
            "mean": statistics.mean(samples),
            "count": len(samples)
        }
    
    def _make_key(self, label_values: dict) -> str:
        return ",".join(f"{k}={v}" for k, v in sorted(label_values.items()))


class Gauge:
    """Point-in-time metric that can go up or down."""
    
    def __init__(self, name: str, description: str, labels: List[str] = None):
        self.name = name
        self.description = description
        self.labels = labels or []
        self._values: Dict[str, float] = {}
    
    def set(self, value: float, **label_values):
        key = self._make_key(label_values)
        self._values[key] = value
    
    def inc(self, value: float = 1, **label_values):
        key = self._make_key(label_values)
        self._values[key] = self._values.get(key, 0) + value
    
    def dec(self, value: float = 1, **label_values):
        key = self._make_key(label_values)
        self._values[key] = self._values.get(key, 0) - value
    
    def get(self, **label_values) -> float:
        key = self._make_key(label_values)
        return self._values.get(key, 0.0)
    
    def _make_key(self, label_values: dict) -> str:
        return ",".join(f"{k}={v}" for k, v in sorted(label_values.items()))


# Pre-defined metrics for NoMan
metrics = {
    "requests_total": Counter("noman_requests_total", "Total requests processed"),
    "request_duration": Histogram("noman_request_duration_seconds", "Request latency"),
    "tokens_consumed": Counter("noman_tokens_total", "Total tokens consumed"),
    "active_sessions": Gauge("noman_active_sessions", "Currently active sessions"),
    "memory_usage_bytes": Gauge("noman_memory_usage_bytes", "Memory usage in bytes"),
    "cache_hits": Counter("noman_cache_hits_total", "Cache hit count"),
    "cache_misses": Counter("noman_cache_misses_total", "Cache miss count"),
    "errors_total": Counter("noman_errors_total", "Total errors", ["type"]),
}


def record_request(start_time: float, tokens: int, success: bool):
    """Helper to record standard request metrics."""
    duration = time.time() - start_time
    
    metrics["requests_total"].inc()
    metrics["request_duration"].observe(duration)
    metrics["tokens_consumed"].inc(tokens)
    
    if not success:
        metrics["errors_total"].inc(type="request_failure")


def export_metrics() -> str:
    """Export metrics in Prometheus format."""
    lines = []
    
    for metric in metrics.values():
        if isinstance(metric, Counter):
            lines.append(f"# HELP {metric.name} {metric.description}")
            lines.append(f"# TYPE {metric.name} counter")
            for key, value in metric._values.items():
                labels = "{" + key + "}" if key else ""
                lines.append(f"{metric.name}{labels} {value}")
        
        elif isinstance(metric, Histogram):
            lines.append(f"# HELP {metric.name} {metric.description}")
            lines.append(f"# TYPE {metric.name} histogram")
            # Simplified - would export bucket counts in production
        
        elif isinstance(metric, Gauge):
            lines.append(f"# HELP {metric.name} {metric.description}")
            lines.append(f"# TYPE {metric.name} gauge")
            for key, value in metric._values.items():
                labels = "{" + key + "}" if key else ""
                lines.append(f"{metric.name}{labels} {value}")
    
    return "\n".join(lines)
```

### 6.7 Updated Implementation Tasks

| Task | File(s) | Priority | Dependencies | Change |
|------|---------|----------|--------------|--------|
| Telemetry logger | `core/observability/logger.py` | P0 | None | — |
| Trace viewer | `core/observability/traces.py` | P0 | Self-improve | — |
| **Distributed tracing** | `core/observability/tracing.py` | **P0** | None | ↑ NEW - OpenTelemetry-compatible |
| **Log rotation** | `core/observability/log_rotation.py` | **P0** | Logger | ↑ Fixed unmanaged log volume |
| **Metrics aggregation** | `core/observability/metrics.py` | **P0** | Logger | ↑ NEW - Prometheus-compatible |
| Debug CLI commands | `cli/commands/debug.py` | P1 | All subsystems | — |
| Log rotation | `core/observability/rotation.py` | P1 | Logger | ↓ Merged into log_rotation.py |
| Metrics exporter | `core/observability/metrics.py` | P2 | Logger | ↑ Elevated P2→P0 |

