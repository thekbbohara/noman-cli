# NoMan Tool Bus — Detailed Design

> *The hands of NoMan. Discovers, registers, sandboxes, and executes all agent tools.*

**Version:** 0.1  
**Status:** Ready for Implementation  
**Parent Document:** NOMAN_DESIGN.md  
**Last Updated:** 2026-04-23

---

## 1. Overview

### 1.1 Purpose

The Tool Bus is the execution layer that:
- Provides a registry of available tools
- Validates tool calls before execution
- Sandboxes tool execution for security
- Tracks tool costs and performance
- Enables extensibility (user + agent-authored tools)


### 1.2 Key Principles

| Principle | Description | Rationale |
|-----------|-------------|-----------|
| **Explicit contracts** | Every tool has a JSON schema | Validation, documentation, auto-completion |
| **Cost transparency** | Tools declare estimated token cost | Budget enforcement |
| **Sandboxed execution** | Tools run with restricted permissions | Security |
| **Composable** | Tools can call other tools | Reusability |
| **Observable** | All tool calls are logged | Debugging, self-improvement |

### 1.3 Non-Goals

- **Not a general plugin system** — Tools must be registered at startup
- **Not a distributed task queue** — All execution is local
- **Not an RPC framework** — Tools are called synchronously within the same process

---

## 2. Architecture

### 2.1 Component Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                      Tool Bus                               │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────┐    ┌─────────────────┐                │
│  │   Tool          │    │   Tool          │                │
│  │   Registry      │    │   Validator     │                │
│  └────────┬────────┘    └────────┬────────┘                │
│           │                      │                          │
│           ▼                      ▼                          │
│  ┌─────────────────┐    ┌─────────────────┐                │
│  │   Cost          │    │   Permission    │                │
│  │   Estimator     │    │   Checker       │                │
│  └────────┬────────┘    └────────┬────────┘                │
│           │                      │                          │
│           └──────────┬───────────┘                          │
│                      │                                      │
│              ┌───────▼────────┐                             │
│              │   Executor     │                             │
│              │   (sandboxed)  │                             │
│              └───────┬────────┘                             │
│                      │                                      │
│  ┌───────────────────▼───────────────────┐                 │
│  │         Tool Implementations          │                 │
│  │  (core/  overlay/  user/  plugins/)   │                 │
│  └───────────────────────────────────────┘                 │
│                                                             │
│  ┌─────────────────────────────────────────┐               │
│  │          Execution Logger               │               │
│  │    (traces, metrics, audit trail)       │               │
│  └─────────────────────────────────────────┘               │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Tool Discovery Flow

```
1. Startup discovery
   ├─► Scan core/tools/ (built-in tools)
   ├─► Scan overlay/tools/ (agent-authored)
   ├─► Scan user/plugins/tools/ (user extensions)
   ├─► Load each tool module
   ├─► Extract @tool decorator metadata
   └─► Register in Tool Registry

2. Runtime execution
   ├─► Orchestrator requests tool call
   ├─► Validator checks schema + permissions
   ├─► Cost estimator verifies budget
   ├─► Executor runs tool in sandbox
   ├─► Result returned to orchestrator
   └─► Logger records execution trace
```

---

## 3. Tool Definition API

### 3.1 Decorator Interface

```python
from typing import Any, Dict, Optional, List
from dataclasses import dataclass

@dataclass
class ToolMetadata:
    name: str
    description: str
    parameters: Dict  # JSON Schema
    return_type: str
    cost_estimate: int  # Expected tokens in output
    risk_level: Literal["read-only", "write", "execute", "self-modify"]
    timeout_sec: Optional[int] = None
    requires_confirmation: bool = False

def tool(
    name: str,
    description: str,
    cost_estimate: int = 100,
    risk_level: str = "read-only",
    timeout_sec: Optional[int] = None
):
    """Decorator to register a function as a tool."""
    
    def decorator(func):
        # Extract parameter schema from type hints
        schema = extract_json_schema(func)
        
        # Attach metadata
        func._tool_metadata = ToolMetadata(
            name=name,
            description=description,
            parameters=schema,
            return_type=extract_return_type(func),
            cost_estimate=cost_estimate,
            risk_level=risk_level,
            timeout_sec=timeout_sec,
            requires_confirmation=risk_level in ["write", "execute"]
        )
        
        return func
    
    return decorator
```

### 3.2 Example Tool Definitions

#### Context Tools

```python
# core/tools/context.py

@tool(
    name="read_lines",
    description="Read specific line range from a file. Use for examining code without loading entire file.",
    cost_estimate=200,
    risk_level="read-only"
)
def read_lines(path: str, start: int, end: int) -> str:
    """
    Read lines from start to end (inclusive, 1-indexed).
    
    Args:
        path: Relative path to file
        start: Starting line number (1-indexed)
        end: Ending line number (inclusive)
    
    Returns:
        The requested lines as a string
    """
    ...

@tool(
    name="read_symbol",
    description="Read the full body of a named function/class using tree-sitter.",
    cost_estimate=150,
    risk_level="read-only"
)
def read_symbol(path: str, symbol_name: str) -> str:
    """
    Read a complete symbol (function, class, method) by name.
    
    Args:
        path: Relative path to file
        symbol_name: Name of the symbol to read
    
    Returns:
        Full source code of the symbol
    """
    ...

@tool(
    name="search_symbols",
    description="Search for symbols by name or pattern across the repository.",
    cost_estimate=100,
    risk_level="read-only"
)
def search_symbols(query: str, scope: Optional[str] = None) -> List[Dict]:
    """
    Fuzzy search for symbols matching query.
    
    Args:
        query: Search term (fuzzy match)
        scope: Optional directory prefix to limit search
    
    Returns:
        List of matching symbols with metadata
    """
    ...

@tool(
    name="skeleton",
    description="Get the compressed skeleton map of the repository structure.",
    cost_estimate=500,
    risk_level="read-only"
)
def skeleton() -> str:
    """
    Return the current skeleton map (signatures only, ranked by importance).
    
    Returns:
        Formatted skeleton string
    """
    ...
```

#### Filesystem Tools

```python
# core/tools/filesystem.py

@tool(
    name="list_dir",
    description="List contents of a directory.",
    cost_estimate=50,
    risk_level="read-only"
)
def list_dir(path: str, recursive: bool = False) -> str:
    """
    List files and directories.
    
    Args:
        path: Directory path
        recursive: If True, list recursively
    
    Returns:
        Formatted directory listing
    """
    ...

@tool(
    name="write_file",
    description="Write content to a file. Creates parent directories if needed.",
    cost_estimate=50,
    risk_level="write"
)
def write_file(path: str, content: str) -> bool:
    """
    Write content to file.
    
    Args:
        path: File path
        content: Content to write
    
    Returns:
        True on success
    """
    ...

@tool(
    name="edit_file",
    description="Apply a unified diff patch to a file.",
    cost_estimate=100,
    risk_level="write"
)
def edit_file(path: str, diff: str) -> bool:
    """
    Apply a diff patch.
    
    Args:
        path: File path
        diff: Unified diff format patch
    
    Returns:
        True on success
    """
    ...

@tool(
    name="delete_file",
    description="Delete a file.",
    cost_estimate=20,
    risk_level="write"
)
def delete_file(path: str) -> bool:
    """
    Delete a file.
    
    Args:
        path: File path
    
    Returns:
        True on success
    """
    ...
```

#### Execution Tools

```python
# core/tools/execution.py

@tool(
    name="run_shell",
    description="Execute a shell command in a sandboxed subprocess.",
    cost_estimate=500,
    risk_level="execute",
    timeout_sec=60
)
def run_shell(command: str, cwd: Optional[str] = None) -> str:
    """
    Run a shell command.
    
    Args:
        command: Shell command to execute
        cwd: Working directory (default: repo root)
    
    Returns:
        Combined stdout + stderr
    """
    ...

@tool(
    name="run_tests",
    description="Run the test suite or specific tests.",
    cost_estimate=1000,
    risk_level="execute",
    timeout_sec=300
)
def run_tests(pattern: Optional[str] = None) -> str:
    """
    Run tests.
    
    Args:
        pattern: Optional test pattern (e.g., "test_auth*")
    
    Returns:
        Test output
    """
    ...

@tool(
    name="lint",
    description="Run linter on specified files.",
    cost_estimate=300,
    risk_level="execute"
)
def lint(paths: List[str]) -> str:
    """
    Run linter.
    
    Args:
        paths: Files or directories to lint
    
    Returns:
        Lint output
    """
    ...
```

#### Memory Tools

```python
# core/tools/memory.py

@tool(
    name="remember",
    description="Store a semantic fact in long-term memory.",
    cost_estimate=50,
    risk_level="self-modify"
)
def remember(scope: str, key: str, value: str) -> bool:
    """
    Store a fact.
    
    Args:
        scope: Fact scope (project, file, symbol)
        key: Fact key
        value: Fact value
    
    Returns:
        True on success
    """
    ...

@tool(
    name="recall",
    description="Retrieve memories relevant to a query.",
    cost_estimate=100,
    risk_level="read-only"
)
def recall(query: str, tier: str = "auto", k: int = 5) -> List[Dict]:
    """
    Retrieve memories.
    
    Args:
        query: Search query
        tier: Memory tier (episodic, semantic, procedural, auto)
        k: Number of results
    
    Returns:
        List of memory entries
    """
    ...

@tool(
    name="skill_load",
    description="Load a skill from the procedural memory library.",
    cost_estimate=200,
    risk_level="read-only"
)
def skill_load(name: str) -> str:
    """
    Load a skill definition.
    
    Args:
        name: Skill name
    
    Returns:
        Full skill definition
    """
    ...
```

### 3.3 User-Defined Tools

Users can add custom tools in `user/plugins/tools/`:

```python
# user/plugins/tools/jira.py

from noman.tools import tool

@tool(
    name="jira_create_ticket",
    description="Create a Jira ticket for tracking work.",
    cost_estimate=100,
    risk_level="execute"
)
def jira_create_ticket(summary: str, description: str, project: str = "ENG") -> str:
    """
    Create a Jira ticket.
    
    Requires JIRA_URL and JIRA_TOKEN environment variables.
    """
    import os
    import requests
    
    url = os.environ["JIRA_URL"]
    headers = {"Authorization": f"Bearer {os.environ['JIRA_TOKEN']}"}
    
    response = requests.post(
        f"{url}/rest/api/3/issue",
        headers=headers,
        json={
            "fields": {
                "project": {"key": project},
                "summary": summary,
                "description": description,
                "issuetype": {"name": "Task"}
            }
        }
    )
    
    return response.json()["key"]
```

### 3.4 Agent-Authored Tools

The agent can generate new tools during self-improvement. These go to `overlay/tools/`:

```python
# overlay/tools/refactor_extract_method.py
# Auto-generated by NoMan on 2026-04-22

from noman.tools import tool

@tool(
    name="refactor_extract_method",
    description="Extract a block of code into a new method with proper signature.",
    cost_estimate=300,
    risk_level="write"
)
def refactor_extract_method(
    file_path: str,
    start_line: int,
    end_line: int,
    new_method_name: str,
    parameters: List[str]
) -> str:
    """
    Extract code block into new method.
    
    This tool was auto-generated from successful refactoring patterns.
    """
    # Implementation generated by meta-agent
    ...
```

---

## 4. Tool Registration & Discovery

### 4.1 Registry Implementation

```python
class ToolRegistry:
    """Central registry for all available tools."""
    
    def __init__(self):
        self.tools: Dict[str, Callable] = {}
        self.metadata: Dict[str, ToolMetadata] = {}
        self.schemas: Dict[str, Dict] = {}
    
    def register(self, func: Callable):
        """Register a tool function."""
        
        meta = getattr(func, '_tool_metadata', None)
        if not meta:
            raise ValueError(f"Function {func.__name__} missing @tool decorator")
        
        self.tools[meta.name] = func
        self.metadata[meta.name] = meta
        self.schemas[meta.name] = meta.parameters
        
        logger.info(f"Registered tool: {meta.name} (risk={meta.risk_level})")
    
    def get_tool(self, name: str) -> Callable:
        """Get a tool by name."""
        if name not in self.tools:
            raise UnknownToolError(f"Unknown tool: {name}")
        return self.tools[name]
    
    def get_schema(self, name: str) -> Dict:
        """Get JSON schema for a tool."""
        if name not in self.schemas:
            raise UnknownToolError(f"Unknown tool: {name}")
        return self.schemas[name]
    
    def get_all_tools(self) -> List[Dict]:
        """Get all tools with metadata (for LLM tool-calling)."""
        return [
            {
                "name": meta.name,
                "description": meta.description,
                "parameters": self.schemas[name]
            }
            for name, meta in self.metadata.items()
        ]
    
    def has_tool(self, name: str) -> bool:
        """Check if tool exists."""
        return name in self.tools
```

### 4.2 Auto-Discovery

```python
class ToolDiscoverer:
    """Automatically discover tools from designated directories."""
    
    TOOL_DIRS = [
        "core/tools/",
        "overlay/tools/",
        "user/plugins/tools/"
    ]
    
    def discover_all(self) -> List[Callable]:
        """Scan all tool directories and load modules."""
        
        tools = []
        
        for tool_dir in self.TOOL_DIRS:
            if not Path(tool_dir).exists():
                continue
            
            for module_path in Path(tool_dir).glob("*.py"):
                if module_path.name.startswith("_"):
                    continue
                
                # Import module
                module = self._import_module(module_path)
                
                # Find decorated functions
                for name, obj in inspect.getmembers(module, inspect.isfunction):
                    if hasattr(obj, '_tool_metadata'):
                        tools.append(obj)
        
        return tools
    
    def _import_module(self, path: Path) -> ModuleType:
        """Dynamically import a Python module."""
        
        spec = importlib.util.spec_from_file_location(
            path.stem,
            path
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        return module
```

---

## 5. Security & Sandboxing

### 5.1 Permission Levels

| Level | Tools | Approval Required |
|-------|-------|-------------------|
| **read-only** | `read_lines`, `read_symbol`, `search_symbols`, `list_dir`, `grep` | None (auto-approved) |
| **write** | `write_file`, `edit_file`, `delete_file` | First use in session |
| **execute** | `run_shell`, `run_tests`, `lint` | Each time |
| **self-modify** | `remember`, tool generation, prompt patches | Queued for review |

### 5.2 Permission Checker

```python
class PermissionChecker:
    """Validate tool call permissions."""
    
    def __init__(self, config: SecurityConfig):
        self.config = config
        self.session_approved: Set[str] = set()
    
    def check_permission(
        self,
        tool_name: str,
        args: Dict,
        session_id: str
    ) -> PermissionResult:
        """Check if a tool call is allowed."""
        
        meta = registry.metadata.get(tool_name)
        if not meta:
            return PermissionResult(granted=False, reason=f"Unknown tool: {tool_name}")
        
        # Check risk level
        if meta.risk_level == "read-only":
            return PermissionResult(granted=True)
        
        # Check session approval cache
        cache_key = f"{session_id}:{tool_name}"
        if cache_key in self.session_approved:
            return PermissionResult(granted=True)
        
        # Check config allowlist/denylist
        if tool_name in self.config.auto_approve:
            self.session_approved.add(cache_key)
            return PermissionResult(granted=True)
        
        if tool_name in self.config.deny_list:
            return PermissionResult(granted=False, reason="Tool is deny-listed")
        
        # Requires explicit approval
        if meta.requires_confirmation:
            return PermissionResult(
                granted=False,
                reason="Requires user confirmation",
                requires_approval=True
            )
        
        return PermissionResult(granted=True)
    
    def approve_for_session(self, tool_name: str, session_id: str):
        """Approve a tool for the rest of the session."""
        self.session_approved.add(f"{session_id}:{tool_name}")
```

### 5.3 Sandboxed Execution

```python
class SandboxedExecutor:
    """Execute tools in a sandboxed environment."""
    
    def __init__(self, working_dir: Path, config: SecurityConfig):
        self.working_dir = working_dir
        self.config = config
    
    async def execute(
        self,
        tool_name: str,
        args: Dict,
        timeout_sec: Optional[int] = None
    ) -> ToolResult:
        """Execute a tool with sandboxing."""
        
        tool_func = registry.get_tool(tool_name)
        meta = registry.metadata[tool_name]
        
        # Set timeout
        timeout = timeout_sec or meta.timeout_sec or 60
        
        try:
            # Execute with timeout
            result = await asyncio.wait_for(
                self._run_sandboxed(tool_func, args),
                timeout=timeout
            )
            
            return ToolResult(
                tool_name=tool_name,
                success=True,
                output=result,
                duration_sec=0  # Will be calculated
            )
        
        except asyncio.TimeoutError:
            return ToolResult(
                tool_name=tool_name,
                success=False,
                error=f"Tool execution timed out after {timeout}s"
            )
        
        except Exception as e:
            return ToolResult(
                tool_name=tool_name,
                success=False,
                error=str(e)
            )
    
    async def _run_sandboxed(self, func: Callable, args: Dict) -> Any:
        """Run a function with filesystem/network restrictions."""
        
        # Validate all path arguments are within working_dir
        validated_args = self._validate_paths(args)
        
        # Run in thread pool (for CPU-bound tools)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: func(**validated_args)
        )
        
        return result
    
    def _validate_paths(self, args: Dict) -> Dict:
        """Ensure all path arguments are within allowed directories."""
        
        validated = {}
        for key, value in args.items():
            if isinstance(value, str) and Path(value).is_absolute():
                # Resolve and check
                resolved = Path(value).resolve()
                if not str(resolved).startswith(str(self.working_dir)):
                    raise SecurityError(
                        f"Path escape attempt: {value} is outside working directory"
                    )
                validated[key] = str(resolved)
            else:
                validated[key] = value
        
        return validated
```

---

## 6. Cost Estimation

### 6.1 Cost Model

```python
class CostEstimator:
    """Estimate token costs for tool calls."""
    
    # Base costs per tool type
    BASE_COSTS = {
        "read_lines": 200,      # ~50 lines average
        "read_symbol": 150,     # Average function size
        "search_symbols": 100,  # ~10 results
        "write_file": 50,       # Confirmation only
        "run_shell": 500,       # Variable, conservative estimate
        "run_tests": 1000,      # Large output expected
    }
    
    def estimate(self, tool_name: str, args: Dict) -> int:
        """Estimate token cost for a tool call."""
        
        meta = registry.metadata.get(tool_name)
        if meta:
            # Use declared estimate
            return meta.cost_estimate
        
        # Fall back to base cost
        base = self.BASE_COSTS.get(tool_name, 100)
        
        # Adjust based on arguments
        if tool_name == "read_lines":
            line_range = abs(args.get("end", 0) - args.get("start", 0))
            return min(base + (line_range * 4), 2000)  # Cap at 2000 tokens
        
        if tool_name == "run_shell":
            command = args.get("command", "")
            # Commands that produce large output
            if any(x in command for x in ["cat", "head", "tail", "grep"]):
                return base * 2
        
        return base
```

### 6.2 Historical Cost Tracking

```python
class CostTracker:
    """Track actual vs estimated costs for tools."""
    
    def __init__(self):
        self.history: List[CostRecord] = []
    
    def record(self, tool_name: str, estimated: int, actual: int):
        """Record actual cost after execution."""
        
        self.history.append(CostRecord(
            tool_name=tool_name,
            estimated=estimated,
            actual=actual,
            timestamp=datetime.now()
        ))
    
    def get_average_actual(self, tool_name: str, window: int = 100) -> float:
        """Get average actual cost for a tool (last N executions)."""
        
        records = [
            r for r in self.history
            if r.tool_name == tool_name
        ][-window:]
        
        if not records:
            return 0
        
        return sum(r.actual for r in records) / len(records)
    
    def get_accuracy(self, tool_name: str) -> float:
        """Calculate estimation accuracy (1.0 = perfect)."""
        
        records = [r for r in self.history if r.tool_name == tool_name]
        if not records:
            return 1.0
        
        errors = [abs(r.estimated - r.actual) / max(r.estimated, 1) for r in records]
        return 1.0 - (sum(errors) / len(errors))
```

---

## 7. Configuration

### 7.1 Tool Bus Config

```toml
# user/config.toml

[tools]
auto_discover = true
enable_user_plugins = true
enable_overlay_tools = true

[security]
auto_approve = ["read-only"]
require_confirmation = ["write"]
require_explicit_approval = ["execute", "self-modify"]
max_shell_timeout_sec = 60
allowed_shell_commands = ["git status", "pytest", "cargo build", "npm test"]
deny_list = ["rm", "sudo", "curl", "wget"]  # Dangerous commands

[costs]
enable_tracking = true
warn_at_budget_percent = 80
hard_limit_per_turn = 5000
```

### 7.2 Runtime Overrides

```bash
# Approve a specific tool for this session
noman --approve-tool run_shell "add logging"

# Disable a tool temporarily
noman --disable-tool delete_file "cleanup"

# Show tool costs
noman tools stats
```

---

## 8. Testing Strategy

### 8.1 Unit Tests

```python
# tests/test_tools.py

class TestToolRegistry:
    
    def test_register_and_get_tool(self):
        registry = ToolRegistry()
        
        @tool(name="test_tool", description="Test", cost_estimate=100)
        def test_func(x: int) -> int:
            return x * 2
        
        registry.register(test_func)
        
        assert registry.has_tool("test_tool")
        assert registry.get_tool("test_tool") == test_func
    
    def test_unknown_tool_raises_error(self):
        registry = ToolRegistry()
        
        with pytest.raises(UnknownToolError):
            registry.get_tool("nonexistent")

class TestPermissionChecker:
    
    def test_read_only_auto_approved(self):
        checker = PermissionChecker(test_config)
        result = checker.check_permission("read_lines", {"path": "test.py"}, "sess1")
        
        assert result.granted == True
    
    def test_write_requires_first_approval(self):
        checker = PermissionChecker(test_config)
        result = checker.check_permission("write_file", {"path": "test.py"}, "sess1")
        
        assert result.granted == False
        assert result.requires_approval == True
    
    def test_approved_tool_cached_for_session(self):
        checker = PermissionChecker(test_config)
        
        # First call requires approval
        result1 = checker.check_permission("write_file", {}, "sess1")
        assert result1.requires_approval == True
        
        # Approve
        checker.approve_for_session("write_file", "sess1")
        
        # Second call auto-approved
        result2 = checker.check_permission("write_file", {}, "sess1")
        assert result2.granted == True

class TestSandboxedExecutor:
    
    def test_path_escape_blocked(self):
        executor = SandboxedExecutor(working_dir=Path("/workspace"), config=test_config)
        
        with pytest.raises(SecurityError):
            await executor.execute(
                "read_lines",
                {"path": "/etc/passwd", "start": 1, "end": 10}
            )
```

### 8.2 Integration Tests

```python
# tests/integration/test_tools_full.py

async def test_full_tool_execution():
    """Test complete tool execution flow."""
    
    tool_bus = ToolBus(config=integration_config)
    
    # Execute a read tool
    result = await tool_bus.execute(
        tool_name="read_lines",
        args={"path": "tests/fixtures/sample.py", "start": 1, "end": 10}
    )
    
    assert result.success
    assert len(result.output) > 0
    
    # Execute a write tool (with approval)
    tool_bus.permissions.approve_for_session("write_file", "test_session")
    
    result = await tool_bus.execute(
        tool_name="write_file",
        args={"path": "tests/fixtures/output.txt", "content": "test"}
    )
    
    assert result.success
    assert exists("tests/fixtures/output.txt")
```

---

## 9. Performance Targets

| Metric | Target | Measurement |
|--------|--------|-------------|
| Tool discovery time | <500ms | Startup to ready |
| Tool validation latency | <10ms | Request to execution start |
| Sandbox overhead | <5% | Sandboxed vs native execution time |
| Cost estimation accuracy | ±20% | Estimated vs actual tokens |
| Max concurrent tools | 10 | Parallel execution limit |

---

## 10. Open Questions

1. **Should tools support streaming output?** For long-running tools like `run_tests`, should we stream partial results?

2. **How to handle tool versioning?** If an agent generates a tool, then upstream changes break it, how do we migrate?

3. **Should there be a tool marketplace?** Allow users to share community tools? Security implications?

4. **What about tool composition?** Should agents be able to chain multiple tools atomically?

---

## 11. Implementation Checklist

- [ ] Tool decorator and metadata extraction
- [ ] JSON schema generation from type hints
- [ ] Tool registry implementation
- [ ] Auto-discovery from directories
- [ ] Permission checker
- [ ] Sandboxed executor
- [ ] Path validation middleware
- [ ] Cost estimator
- [ ] Cost tracker
- [ ] Core tools implementation (context, filesystem, execution, memory)
- [ ] Logging/audit trail
- [ ] CLI commands (`noman tools ls`, `noman tools stats`)
- [ ] Unit tests (80%+ coverage)
- [ ] Security tests (path escape, injection)
- [ ] Documentation for tool authors

---

## 12. References

- **JSON Schema**: https://json-schema.org/
- **Parent Design**: [NOMAN_DESIGN.md](./NOMAN_DESIGN.md)
- **Related**: [orchestrator.md](./orchestrator.md), [memory.md](./memory.md)
