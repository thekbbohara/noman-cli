# NoMan — Remaining Design Plans Index

> *Comprehensive implementation plans for all subsystems not yet covered in detailed design documents.*

**Version:** 0.1
**Status:** Ready for Implementation
**Parent Document:** NOMAN_DESIGN.md
**Last Updated:** 2026-04-23

---

## Overview

This document consolidates detailed implementation plans for all subsystems identified in the gap analysis (§4 of NOMAN_DESIGN.md) and roadmap (§12) that don't yet have standalone design documents.

### Existing Design Documents

| Document | Status | Coverage |
|----------|--------|----------|
| `NOMAN_DESIGN.md` | ✅ Complete | High-level architecture, vision, roadmap |
| `context.md` | ✅ Complete | Context Management (Subsystem A) |
| `memory.md` | ✅ Complete | Memory System (Subsystem B) |
| `orchestrator.md` | ✅ Complete | Orchestrator (ReAct loop) |
| `tools.md` | ✅ Complete | Tool Bus |

### Remaining Components Requiring Plans

| Component | Priority | Phase | Estimated Effort | This Document Section |
|-----------|----------|-------|------------------|----------------------|
| Model Adapter | P0 | Phase 0 | 1 week | §1 |
| Self-Improvement Architecture | P0 | Phase 5 | 2 weeks | §2 |
| Security & Sandboxing | P0 | Phase 4 | 1.5 weeks | §3 |
| CLI Surface | P0 | Phase 0 | 0.5 weeks | §4 |
| Testing Framework | P1 | Phase 9 | 1.5 weeks | §5 |
| Observability & Debugging | P1 | Phase 8 | 1 week | §6 |
| Editor Integrations | P2 | Phase 10 | 2 weeks | §7 |
| Error Handling & Recovery | P1 | Phase 4 | 1 week | §8 |
| Performance Optimization | P1 | Phase 6 | Ongoing | §9 |
| Collaboration & Multi-User | P2 | Phase 11 | 1.5 weeks | §10 |

---

## Table of Contents

1. [Model Adapter](#1-model-adapter)
2. [Self-Improvement Architecture](#2-self-improvement-architecture)
3. [Security & Sandboxing](#3-security--sandboxing)
4. [CLI Surface](#4-cli-surface)
5. [Testing Framework](#5-testing-framework)
6. [Observability & Debugging](#6-observability--debugging)
7. [Editor Integrations](#7-editor-integrations)
8. [Error Handling & Recovery](#8-error-handling--recovery)
9. [Performance Optimization](#9-performance-optimization)
10. [Collaboration & Multi-User](#10-collaboration--multi-user)
11. [Implementation Checklist](#11-implementation-checklist)

---

## 1. Model Adapter

### 1.1 Purpose

The Model Adapter provides a unified interface to multiple LLM providers while supporting role-based routing (planner/executor/critic). It normalizes different provider APIs into a single OpenAI-compatible dialect.

### 1.2 Key Responsibilities

| Responsibility | Description | Implementation Notes |
|----------------|-------------|---------------------|
| **Provider Abstraction** | Normalize OpenAI, Anthropic, Ollama, Groq, etc. | Single `chat()` interface |
| **Role Routing** | Route planner/executor/critic to different models | Configurable per-role |
| **Capability Negotiation** | Probe provider capabilities at startup | Cache results with TTL |
| **Streaming Support** | Handle streaming responses uniformly | Async generator interface |
| **Tool Calling** | Normalize tool-calling dialects | Detect and adapt per-provider |
| **Fallback Logic** | Graceful degradation when providers fail | Retry + fallback chain |
| **Cost Tracking** | Track token usage and costs per provider | Log to traces |

### 1.3 Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Model Adapter                            │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────┐    ┌─────────────────┐                │
│  │   Provider      │    │   Capability    │                │
│  │   Registry      │    │   Negotiator    │                │
│  └────────┬────────┘    └────────┬────────┘                │
│           │                      │                          │
│           ▼                      ▼                          │
│  ┌─────────────────┐    ┌─────────────────┐                │
│  │   Role          │    │   Provider      │                │
│  │   Router        │    │   Adapters      │                │
│  │                 │    │  - OpenAI       │                │
│  │ (planner/       │    │  - Anthropic    │                │
│  │  executor/      │    │  - Ollama       │                │
│  │  critic)        │    │  - Groq         │                │
│  └────────┬────────┘    └────────┬────────┘                │
│           │                      │                          │
│           └──────────┬───────────┘                          │
│                      │                                      │
│              ┌───────▼────────┐                             │
│              │   Unified      │                             │
│              │   Interface    │                             │
│              │   chat()       │                             │
│              └───────┬────────┘                             │
│                      │                                      │
│  ┌───────────────────▼───────────────────┐                 │
│  │         Streaming Response Handler    │                 │
│  │         + Tool Call Parser            │                 │
│  └───────────────────────────────────────┘                 │
│                                                             │
│  ┌─────────────────────────────────────────┐               │
│  │          Cost Tracker + Logger          │               │
│  └─────────────────────────────────────────┘               │
└─────────────────────────────────────────────────────────────┘
```

### 1.4 Configuration Schema

```toml
# user/config.toml

[model]
# Default provider (used for all roles if not overridden)
default = "local_ollama"

# Per-role overrides (optional)
planner = "claude_cloud"     # Complex reasoning → stronger model
executor = "local_ollama"    # Tool calling → local is fine
critic = "groq_fast"         # Fast feedback → low-latency model

# Provider definitions
[[providers]]
id = "local_ollama"
type = "openai_compat"
base_url = "http://localhost:11434/v1"
model = "codellama:34b"
api_key = ""  # Not needed for local
timeout_sec = 120
max_retries = 3
stream = true

[[providers]]
id = "claude_cloud"
type = "anthropic"
api_key = "${ANTHROPIC_API_KEY}"
model = "claude-sonnet-4-20250514"
timeout_sec = 60
max_retries = 2
stream = true
# Anthropic-specific quirks
max_tokens_per_request = 4096
system_prompt_in_messages = true

[[providers]]
id = "groq_fast"
type = "openai_compat"
base_url = "https://api.groq.com/openai/v1"
api_key = "${GROQ_API_KEY}"
model = "mixtral-8x7b-32768"
timeout_sec = 30
max_retries = 3
stream = true
```

### 1.5 Provider Adapter Interface

```python
# core/adapters/base.py

from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional
from dataclasses import dataclass

@dataclass
class Message:
    role: str  # "system", "user", "assistant"
    content: str
    tool_calls: Optional[list] = None
    tool_call_id: Optional[str] = None

@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict  # JSON Schema

@dataclass
class Response:
    content: str
    tool_calls: list
    usage: dict  # {prompt_tokens, completion_tokens, total_tokens}
    model: str
    finish_reason: str

class BaseAdapter(ABC):
    """Base class for all model providers."""
    
    def __init__(self, config: dict):
        self.config = config
        self.capabilities = {}
    
    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        tools: Optional[list[ToolDefinition]] = None,
        stream: bool = False
    ) -> Response | AsyncIterator[str]:
        """Send chat request and return response."""
        pass
    
    @abstractmethod
    async def probe_capabilities(self) -> dict:
        """Probe provider for capabilities and quirks."""
        pass
    
    async def validate_connection(self) -> bool:
        """Check if provider is reachable and authenticated."""
        try:
            await self.probe_capabilities()
            return True
        except Exception:
            return False
```

### 1.6 Capability Negotiation Flow

```
1. Startup probe (per provider)
   ├─► GET /models endpoint (if available)
   ├─► Send test chat with tool call
   ├─► Detect tool-calling dialect:
   │   ├─ OpenAI: {"name": "...", "arguments": {...}}
   │   ├─ Anthropic: <tool_use> XML tags
   │   └─ Custom: regex patterns
   ├─► Measure latency (p50, p95)
   ├─► Check max context window
   ├─► Store in .noman/cache/capabilities.json
   └─► Set TTL (re-probe every 24h or on failure)

2. Runtime selection
   ├─► Orchestrator requests chat for role X
   ├─► Router selects provider for role X
   ├─► Check capability cache
   ├─► Adapt request to provider dialect
   ├─► Send request
   └─► Normalize response to unified format
```

### 1.7 Implementation Tasks

| Task | File(s) | Priority | Dependencies |
|------|---------|----------|--------------|
| Base adapter interface | `core/adapters/base.py` | P0 | None |
| OpenAI-compatible adapter | `core/adapters/openai.py` | P0 | Base adapter |
| Anthropic adapter | `core/adapters/anthropic.py` | P1 | Base adapter |
| Ollama adapter | `core/adapters/ollama.py` | P0 | OpenAI adapter |
| Capability negotiator | `core/adapters/negotiator.py` | P0 | Base adapter |
| Role router | `core/adapters/router.py` | P0 | Capability negotiator |
| Cost tracker | `core/adapters/cost_tracker.py` | P1 | Base adapter |
| Fallback chain | `core/adapters/fallback.py` | P1 | Role router |
| Unit tests | `tests/test_adapters.py` | P1 | All adapters |

---

## 2. Self-Improvement Architecture

### 2.1 Purpose

The Self-Improvement system enables NoMan to autonomously optimize its own prompts, heuristics, and skills based on performance traces. It consists of two agents: the Trace Critic (scores executions) and the Meta-Agent (proposes improvements).

### 2.2 Key Components

| Component | Responsibility | Trigger |
|-----------|---------------|---------|
| **Trace Collector** | Capture full execution traces (prompts, tool calls, results) | Every session |
| **Trace Critic** | Score traces on success, efficiency, correctness | Post-session |
| **Meta-Agent** | Analyze low-scoring traces, propose patches | Periodic or on-demand |
| **Patch Validator** | Test proposed changes before promotion | Before overlay update |
| **Rollback Manager** | Revert bad self-modifications | On user request or auto-detect |

### 2.3 Trace Schema

```json
{
  "trace_id": "uuid4",
  "session_id": "uuid4",
  "timestamp": "ISO8601",
  "task": "User's original prompt",
  "turns": [
    {
      "turn_id": 1,
      "role": "assistant",
      "prompt_tokens": 3421,
      "completion_tokens": 156,
      "thought": "I need to read the auth module first...",
      "tool_call": {
        "name": "read_lines",
        "args": {"path": "src/auth.py", "start": 1, "end": 50}
      },
      "tool_result": "...",
      "duration_ms": 2341
    }
  ],
  "outcome": {
    "success": true,
    "user_confirmed": true,
    "tests_passed": true,
    "total_tokens": 12453,
    "total_turns": 5,
    "duration_sec": 23.4
  },
  "context_snapshot": {
    "skeleton_size": 2341,
    "symbols_loaded": ["authenticate", "validate_token"],
    "memories_retrieved": 3
  }
}
```

### 2.4 Critic Scoring System

```python
# core/selfimprove/critic.py

from dataclasses import dataclass
from enum import Enum

class ScoreCategory(Enum):
    SUCCESS = "success"          # Did it work?
    EFFICIENCY = "efficiency"    # Token/time efficiency
    CORRECTNESS = "correctness"  # Code quality, no bugs
    CLARITY = "clarity"          # Clear explanations

@dataclass
class TraceScore:
    trace_id: str
    overall: float               # Weighted average 0.0-1.0
    categories: dict             # {category: score}
    feedback: str                # Natural language explanation
    suggested_improvements: list # ["Reduce tool calls", "Better prompt structure"]

class TraceCritic:
    """Scores execution traces using LLM + deterministic metrics."""
    
    def __init__(self, model_adapter, config: dict):
        self.model = model_adapter
        self.config = config
        self.weights = config.get("score_weights", {
            "success": 0.4,
            "efficiency": 0.25,
            "correctness": 0.25,
            "clarity": 0.1
        })
    
    async def score_trace(self, trace: dict) -> TraceScore:
        # Deterministic scores
        success_score = 1.0 if trace["outcome"]["success"] else 0.0
        efficiency_score = self._calc_efficiency_score(trace)
        
        # LLM-based scores (correctness, clarity)
        llm_scores = await self._llm_evaluate(trace)
        
        # Weighted average
        overall = (
            success_score * self.weights["success"] +
            efficiency_score * self.weights["efficiency"] +
            llm_scores["correctness"] * self.weights["correctness"] +
            llm_scores["clarity"] * self.weights["clarity"]
        )
        
        return TraceScore(
            trace_id=trace["trace_id"],
            overall=overall,
            categories={
                "success": success_score,
                "efficiency": efficiency_score,
                "correctness": llm_scores["correctness"],
                "clarity": llm_scores["clarity"]
            },
            feedback=llm_scores["feedback"],
            suggested_improvements=llm_scores["suggestions"]
        )
    
    def _calc_efficiency_score(self, trace: dict) -> float:
        # Compare against baseline for similar tasks
        # Return 1.0 for excellent, 0.0 for terrible
        ...
```

### 2.5 Meta-Agent Prompt Template

```markdown
# Meta-Agent: Self-Improvement Analysis

You are analyzing low-scoring execution traces to propose improvements.

## Current System State
- Active prompts: {current_prompts}
- Active heuristics: {active_heuristics}
- Available skills: {available_skills}

## Trace Under Analysis
{trace_json}

## Critic Scores
- Overall: {overall_score}
- Success: {success_score}
- Efficiency: {efficiency_score}
- Correctness: {correctness_score}
- Clarity: {clarity_score}

## Critic Feedback
{critic_feedback}

## Your Task

1. **Root Cause Analysis**: Why did this trace score poorly?
   - Was the prompt unclear?
   - Were wrong tools selected?
   - Was context missing?
   - Was memory retrieval ineffective?

2. **Propose Specific Changes**: Generate ONE of:
   - A prompt patch (modify existing prompt in core/prompts/)
   - A new heuristic (add to overlay/heuristics/)
   - A skill extraction (distill successful pattern)
   - A tool improvement suggestion

3. **Justify Impact**: Explain why this change will improve future scores.

## Output Format

```json
{
  "change_type": "prompt_patch|heuristic|skill_extraction",
  "target_file": "path/to/file",
  "patch": {
    "before": "...",
    "after": "..."
  },
  "justification": "...",
  "expected_score_delta": 0.15
}
```
```

### 2.6 Patch Validation Pipeline

```
1. Meta-Agent proposes patch
   ↓
2. Patch Validator receives proposal
   ↓
3. Syntactic validation
   ├─► Valid JSON/YAML?
   ├─► Valid Python (if code)?
   └─► Follows schema?
   ↓
4. Semantic validation
   ├─► Doesn't break existing tools?
   ├─► Doesn't remove critical prompts?
   └─► Passes unit tests?
   ↓
5. Shadow testing (optional for major changes)
   ├─► Run historical traces with old vs new
   └─► Compare scores
   ↓
6. Decision
   ├─► Auto-promote (if score delta > threshold)
   ├─► Queue for review (if borderline)
   └─► Reject (if regression)
   ↓
7. Apply to overlay/ (with rollback point)
```

### 2.7 Implementation Tasks

| Task | File(s) | Priority | Dependencies |
|------|---------|----------|--------------|
| Trace collector | `core/selfimprove/traces.py` | P0 | Orchestrator |
| Trace storage | `.noman/traces/` schema | P0 | None |
| Critic agent | `core/selfimprove/critic.py` | P0 | Model adapter |
| Meta-agent | `core/selfimprove/meta_agent.py` | P0 | Critic |
| Patch validator | `core/selfimprove/validator.py` | P0 | Tools, Tests |
| Rollback manager | `core/selfimprove/rollback.py` | P1 | Overlay arch |
| Review CLI | `noman review` command | P1 | CLI surface |
| Unit tests | `tests/test_self_improve.py` | P1 | All components |

---

## 3. Security & Sandboxing

### 3.1 Threat Model

| Threat Actor | Capabilities | Goals |
|--------------|--------------|-------|
| **Malicious User Input** | Crafted prompts attempting injection | Escape sandbox, access forbidden resources |
| **Compromised Agent** | Self-improvement gone wrong | Modify own constraints, exfiltrate data |
| **Malicious Tool** | Agent-authored tool with hidden behavior | Persist backdoor, steal credentials |
| **Supply Chain Attack** | Modified dependency or skill | Inject malicious code into workflow |

### 3.2 Sandboxing Layers

#### 3.2.1 Filesystem Sandbox

```python
# core/security/fs_sandbox.py

import os
from pathlib import Path
from typing import Set

class FilesystemSandbox:
    """Restrict file operations to allowed paths."""
    
    def __init__(self, working_dir: str, allowed_paths: Set[str] = None):
        self.working_dir = Path(working_dir).resolve()
        self.allowed_paths = {
            self.working_dir,
            Path(os.getcwd()).resolve(),
        }
        if allowed_paths:
            self.allowed_paths.update(Path(p).resolve() for p in allowed_paths)
        
        # Always allow overlay and .noman
        self.allowed_paths.add(self.working_dir / "overlay")
        self.allowed_paths.add(self.working_dir / ".noman")
    
    def validate_path(self, path: str, mode: str = "read") -> bool:
        """Check if path is within allowed boundaries."""
        resolved = Path(path).resolve()
        
        # Check if resolved path is within any allowed path
        for allowed in self.allowed_paths:
            try:
                resolved.relative_to(allowed)
                return True
            except ValueError:
                continue
        
        return False
    
    def wrap_open(self, path: str, mode: str = "r"):
        """Wrapped open() that enforces sandbox."""
        if not self.validate_path(path, mode):
            raise PermissionError(
                f"Path {path} is outside allowed directories"
            )
        return open(path, mode)
```

#### 3.2.2 Process Sandbox

```python
# core/security/process_sandbox.py

import subprocess
import signal
from typing import Optional, List

class ProcessSandbox:
    """Restrict subprocess execution."""
    
    def __init__(
        self,
        max_timeout_sec: int = 60,
        allowed_commands: List[str] = None,
        deny_network: bool = True
    ):
        self.max_timeout = max_timeout_sec
        self.allowed_commands = set(allowed_commands or [])
        self.deny_network = deny_network
    
    def validate_command(self, cmd: str | list) -> bool:
        """Check if command is allowed."""
        if isinstance(cmd, list):
            base_cmd = cmd[0]
        else:
            base_cmd = cmd.split()[0]
        
        # Check allowlist
        if self.allowed_commands:
            return any(
                base_cmd.endswith(allowed) 
                for allowed in self.allowed_commands
            )
        
        # Default deny dangerous commands
        dangerous = ["rm -rf", "mkfs", "dd", "curl", "wget"]
        return not any(d in cmd for d in dangerous)
    
    def run(
        self,
        cmd: str | list,
        timeout: Optional[int] = None,
        **kwargs
    ) -> subprocess.CompletedProcess:
        """Run command with sandbox restrictions."""
        if not self.validate_command(cmd):
            raise PermissionError(f"Command {cmd} is not allowed")
        
        timeout = min(timeout or self.max_timeout, self.max_timeout)
        
        # Add resource limits
        preexec_fn = None
        if self.deny_network:
            preexec_fn = self._block_network
        
        return subprocess.run(
            cmd,
            timeout=timeout,
            preexec_fn=preexec_fn,
            **kwargs
        )
    
    def _block_network(self):
        """Block network access via socket filtering (Linux)."""
        # Implementation uses seccomp-bpf on Linux
        # Or sandbox-exec on macOS
        pass
```

### 3.3 Permission Model

```toml
# user/config.toml

[security]
# Tool permission levels
auto_approve = ["read-only"]
require_confirmation = ["write"]
require_explicit_approval = ["execute", "self-modify"]

# Shell restrictions
max_shell_timeout_sec = 60
allowed_shell_patterns = [
    "git status",
    "git diff",
    "pytest",
    "cargo build",
    "npm test",
    "make",
    "ls",
    "cat",
    "grep",
    "find"
]
deny_shell_patterns = [
    "rm -rf /",
    "chmod -R 777",
    "curl.*\\|.*sh",
    "wget.*\\|.*sh"
]

# Self-modification thresholds
auto_promote_score_delta = 0.15
require_review_for_new_tools = true
max_overlay_changes_per_session = 5
```

### 3.4 Supply Chain Integrity

```python
# core/security/integrity.py

import hashlib
import json
from pathlib import Path

class CoreIntegrityChecker:
    """Verify core/ hasn't been tampered with."""
    
    def __init__(self, core_dir: str, manifest_path: str):
        self.core_dir = Path(core_dir)
        self.manifest_path = Path(manifest_path)
    
    def generate_manifest(self) -> dict:
        """Generate hash manifest for all core files."""
        manifest = {}
        for file in self.core_dir.rglob("*"):
            if file.is_file():
                relative = file.relative_to(self.core_dir)
                manifest[str(relative)] = self._hash_file(file)
        return manifest
    
    def verify(self) -> list[str]:
        """Verify core/ against manifest. Return list of mismatches."""
        if not self.manifest_path.exists():
            return ["Manifest missing"]
        
        manifest = json.loads(self.manifest_path.read_text())
        mismatches = []
        
        for rel_path, expected_hash in manifest.items():
            file_path = self.core_dir / rel_path
            if not file_path.exists():
                mismatches.append(f"Missing: {rel_path}")
            elif self._hash_file(file_path) != expected_hash:
                mismatches.append(f"Modified: {rel_path}")
        
        return mismatches
    
    def _hash_file(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()
```

### 3.5 Implementation Tasks

| Task | File(s) | Priority | Dependencies |
|------|---------|----------|--------------|
| Filesystem sandbox | `core/security/fs_sandbox.py` | P0 | Tools |
| Process sandbox | `core/security/process_sandbox.py` | P0 | Tools |
| Permission checker | `core/security/permissions.py` | P0 | Tools |
| Core integrity | `core/security/integrity.py` | P1 | None |
| Skill signing | `core/security/signing.py` | P2 | None |
| Security tests | `tests/test_security.py` | P1 | All security modules |

---

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

## 5. Testing Framework

### 5.1 Test Pyramid

```
                    ┌─────────────┐
                   ╱  E2E Tests  ╲
                  ╱   (scenarios) ╲
                 ╱─────────────────╲
                ╱  Integration Tests ╲
               ╱   (subsystem combos) ╲
              ╱─────────────────────────╲
             ╱       Unit Tests          ╲
            ╱    (individual functions)    ╲
           ─────────────────────────────────
```

### 5.2 Unit Test Structure

```python
# tests/test_context_mgmt.py

import pytest
from core.context.skeleton import generate_skeleton
from core.context.pagerank import pagerank, build_call_graph

class TestSkeletonGeneration:
    def test_generates_valid_skeleton(self):
        skeleton = generate_skeleton("tests/fixtures/sample_repo")
        assert len(skeleton.tokens) < 8000
        assert "class SessionManager" in skeleton.symbols
    
    def test_handles_empty_repo(self):
        skeleton = generate_skeleton("tests/fixtures/empty_repo")
        assert skeleton.symbols == []
    
    def test_caches_results(self):
        # First call parses
        skeleton1 = generate_skeleton("tests/fixtures/sample_repo")
        # Second call uses cache
        skeleton2 = generate_skeleton("tests/fixtures/sample_repo")
        assert skeleton1 is skeleton2

class TestPageRankRanking:
    def test_ranks_central_symbols_high(self):
        graph = build_call_graph("tests/fixtures/sample_repo")
        ranks = pagerank(graph, top_k=50)
        assert "main_entrypoint" in ranks  # Central symbol should rank high
    
    def test_handles_cycles(self):
        # Recursive functions create cycles
        graph = build_call_graph("tests/fixtures/recursive_repo")
        ranks = pagerank(graph, top_k=50)
        assert len(ranks) > 0  # Should not crash
```

### 5.3 Integration Test Structure

```python
# tests/integration/test_full_task.py

import pytest
from tests.integration.fixtures import run_noman, read_file, exists

@pytest.mark.integration
class TestFullTaskExecution:
    def test_add_function_with_tests(self):
        result = run_noman(
            "add a function to calculate fibonacci(10) in src/math_utils.py with tests",
            model="test_mock"
        )
        assert result.success
        assert "fibonacci" in read_file("src/math_utils.py")
        assert exists("tests/test_math_utils.py")
    
    def test_refactor_preserves_behavior(self):
        result = run_noman(
            "extract validate_input() helper from process_data()",
            model="test_mock"
        )
        assert result.success
        # Run existing tests to verify behavior preserved
        assert run_tests().passed
```

### 5.4 Benchmark Suite

```python
# tests/benchmarks/suite.py

from dataclasses import dataclass
from typing import Callable

@dataclass
class BenchmarkTask:
    name: str
    category: str  # read, edit, refactor, debug, feature
    description: str
    setup: Callable
    expected_outcome: Callable
    success_criteria: Callable

BENCHMARK_SUITE_V1 = [
    BenchmarkTask(
        name="understand_auth_middleware",
        category="read",
        description="Explain what auth_middleware does",
        setup=lambda: load_fixture("auth_repo"),
        expected_outcome=lambda ctx: "authentication" in ctx.summary.lower(),
        success_criteria=lambda ctx: ctx.cites_correct_lines
    ),
    BenchmarkTask(
        name="add_logging",
        category="edit",
        description="Add logging to parse_config()",
        setup=lambda: load_fixture("config_repo"),
        expected_outcome=lambda ctx: "log.debug" in read_file("src/config.py"),
        success_criteria=lambda ctx: no_syntax_errors()
    ),
    # ... more benchmarks
]

def run_benchmark_suite(suite_name: str = "v1"):
    suite = BENCHMARK_SUITE_V1  # Select by name
    results = []
    
    for task in suite:
        task.setup()
        result = run_noman(task.description)
        passed = task.success_criteria(result)
        results.append({
            "task": task.name,
            "passed": passed,
            "tokens": result.token_usage,
            "duration": result.duration
        })
    
    return {
        "total": len(results),
        "passed": sum(1 for r in results if r["passed"]),
        "avg_tokens": sum(r["tokens"] for r in results) / len(results),
        "results": results
    }
```

### 5.5 Implementation Tasks

| Task | File(s) | Priority | Dependencies |
|------|---------|----------|--------------|
| Test fixtures | `tests/fixtures/` | P0 | None |
| Unit tests (core) | `tests/test_*.py` | P0 | All core modules |
| Integration helpers | `tests/integration/helpers.py` | P0 | CLI |
| Integration tests | `tests/integration/test_*.py` | P1 | Full system |
| Benchmark suite | `tests/benchmarks/suite.py` | P1 | All subsystems |
| Adversarial tests | `tests/adversarial/` | P2 | Security |
| CI pipeline | `.github/workflows/test.yml` | P1 | All tests |

---

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

## 7. Editor Integrations

### 7.1 Architecture

```
┌─────────────────┐         JSON-RPC over stdio/socket        ┌─────────────────┐
│   VS Code       │                                           │   NoMan CLI     │
│   Extension     │ ◄───────────────────────────────────────► │   (server mode) │
│                 │                                           │                 │
│ - Run commands  │                                           │ - Execute tasks │
│ - Show diffs    │                                           │ - Stream output │
│ - Accept/reject │                                           │ - Return edits  │
└─────────────────┘                                           └─────────────────┘

Same protocol for Neovim, Emacs, JetBrains plugins
```

### 7.2 JSON-RPC Protocol

```json
// Request
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "noman/run",
  "params": {
    "task": "add type hints to src/auth.py",
    "file_context": ["src/auth.py"],
    "working_dir": "/path/to/project",
    "options": {
      "explain": true,
      "auto_apply": false
    }
  }
}

// Response (streaming chunks)
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "chunk_type": "thought",
    "content": "I'll start by reading the auth module..."
  }
}

{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "chunk_type": "diff",
    "path": "src/auth.py",
    "diff": "@@ -1,4 +1,5 ...\n-def authenticate(user_id, token):\n+def authenticate(user_id: int, token: str) -> bool:"
  }
}

{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "status": "completed",
    "changes": [
      {"path": "src/auth.py", "diff": "..."}
    ],
    "token_usage": 4521,
    "duration_sec": 12.3
  }
}

// Error response
{
  "jsonrpc": "2.0",
  "id": 1,
  "error": {
    "code": -32000,
    "message": "Permission denied: cannot write to src/auth.py",
    "data": {"requires_confirmation": true}
  }
}
```

### 7.3 VS Code Extension Skeleton

```typescript
// vscode-extension/src/extension.ts

import * as vscode from 'vscode';
import { NoManClient } from './client';

let client: NoManClient;

export function activate(context: vscode.ExtensionContext) {
    client = new NoManClient();
    
    let disposable = vscode.commands.registerCommand(
        'noman.runTask',
        async () => {
            const task = await vscode.window.showInputBox({
                prompt: 'What should NoMan do?',
                placeHolder: 'e.g., add type hints to this file'
            });
            
            if (!task) return;
            
            const editor = vscode.window.activeTextEditor;
            const fileContext = editor ? [editor.document.fileName] : [];
            
            const panel = vscode.window.createWebviewPanel(
                'nomanOutput',
                'NoMan Output',
                vscode.ViewColumn.Beside
            );
            
            const stream = client.runTask({
                task,
                fileContext,
                workingDir: vscode.workspace.rootPath
            });
            
            for await (const chunk of stream) {
                if (chunk.type === 'diff') {
                    // Show inline diff preview
                    showDiffPreview(panel, chunk.path, chunk.diff);
                } else if (chunk.type === 'thought') {
                    appendToOutput(panel, chunk.content);
                }
            }
        }
    );
    
    context.subscriptions.push(disposable);
}
```

### 7.4 Implementation Tasks

| Task | File(s) | Priority | Dependencies |
|------|---------|----------|--------------|
| JSON-RPC server | `cli/server.py` | P1 | Orchestrator |
| Protocol spec | `docs/json-rpc-spec.md` | P1 | None |
| VS Code extension | `extensions/vscode/` | P2 | JSON-RPC server |
| Neovim plugin | `extensions/nvim/` | P2 | JSON-RPC server |
| Inline diff UI | `extensions/*/diff-viewer` | P2 | Editor APIs |

---

## 8. Error Handling & Recovery

### 8.1 Error Categories

```python
# core/errors.py

from enum import Enum

class ErrorCategory(Enum):
    TRANSIENT = "transient"      # Retry will likely succeed
    CONFIG = "config"            # User must fix configuration
    PERMISSION = "permission"    # User must grant permission
    MODEL = "model"              # LLM error, may need fallback
    SANDBOX = "sandbox"          # Security violation
    INTERNAL = "internal"        # Bug in NoMan itself

class NoManError(Exception):
    """Base exception for NoMan."""
    
    def __init__(
        self,
        message: str,
        category: ErrorCategory,
        recoverable: bool = False,
        suggestions: list[str] = None
    ):
        super().__init__(message)
        self.category = category
        self.recoverable = recoverable
        self.suggestions = suggestions or []

class TransientError(NoManError):
    """Network timeout, rate limit, etc."""
    def __init__(self, message: str, retry_after: int = None):
        super().__init__(
            message,
            ErrorCategory.TRANSIENT,
            recoverable=True,
            suggestions=["Retry after delay"]
        )
        self.retry_after = retry_after

class ModelError(NoManError):
    """LLM returned invalid response."""
    def __init__(self, message: str, fallback_provider: str = None):
        super().__init__(
            message,
            ErrorCategory.MODEL,
            recoverable=bool(fallback_provider),
            suggestions=[f"Switch to {fallback_provider}"] if fallback_provider else []
        )
```

### 8.2 Checkpoint & Resume

```python
# core/orchestrator/checkpoint.py

import json
from pathlib import Path

@dataclass
class Checkpoint:
    session_id: str
    turn_id: int
    conversation_state: list
    memory_state: dict
    context_state: dict
    timestamp: str

class CheckpointManager:
    """Save and restore session state."""
    
    def __init__(self, checkpoint_dir: str):
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
    
    def save(self, checkpoint: Checkpoint):
        """Save checkpoint to disk."""
        path = self.checkpoint_dir / f"{checkpoint.session_id}.json"
        path.write_text(json.dumps(self._serialize(checkpoint)))
    
    def load(self, session_id: str) -> Checkpoint | None:
        """Load latest checkpoint for session."""
        path = self.checkpoint_dir / f"{session_id}.json"
        if not path.exists():
            return None
        return self._deserialize(json.loads(path.read_text()))
    
    def resume(self, session_id: str, orchestrator) -> bool:
        """Resume session from checkpoint."""
        checkpoint = self.load(session_id)
        if not checkpoint:
            return False
        
        orchestrator.restore_state(checkpoint)
        return True
```

### 8.3 Implementation Tasks

| Task | File(s) | Priority | Dependencies |
|------|---------|----------|--------------|
| Error hierarchy | `core/errors.py` | P0 | None |
| Retry logic | `core/utils/retry.py` | P0 | Errors |
| Checkpoint manager | `core/orchestrator/checkpoint.py` | P1 | Orchestrator |
| Rollback mechanism | `core/selfimprove/rollback.py` | P1 | Self-improve |
| Error reporting | `cli/commands/report.py` | P2 | Observability |

---

## 9. Performance Optimization

### 9.1 Caching Strategy

```python
# core/utils/cache.py

from functools import lru_cache
from pathlib import Path
import hashlib

class LayeredCache:
    """Multi-layer caching strategy."""
    
    def __init__(self, cache_dir: str, memory_limit_mb: int = 256):
        self.cache_dir = Path(cache_dir)
        self.memory_limit = memory_limit_mb * 1024 * 1024
        self.lru = lru_cache(maxsize=1000)  # In-memory LRU
        self.disk_index = {}  # Disk cache index
    
    def get(self, key: str) -> any | None:
        """Get cached value."""
        # Try memory first
        if key in self.lru:
            return self.lru[key]
        
        # Try disk
        if key in self.disk_index:
            path = self.cache_dir / self.disk_index[key]
            if path.exists():
                value = pickle.loads(path.read_bytes())
                self.lru[key] = value  # Promote to memory
                return value
        
        return None
    
    def set(self, key: str, value: any, ttl_hours: int = 24):
        """Cache a value."""
        self.lru[key] = value
        
        # Also write to disk for persistence
        hash_key = hashlib.sha256(key.encode()).hexdigest()[:16]
        path = self.cache_dir / hash_key
        path.write_bytes(pickle.dumps(value))
        self.disk_index[key] = hash_key
```

### 9.2 Parallelization Opportunities

| Operation | Parallelizable | Strategy |
|-----------|---------------|----------|
| Tree-sitter parsing | Yes | Parse files concurrently (async pool) |
| PageRank computation | Partial | Parallel iteration, synchronized convergence |
| Fact extraction | Yes | Process traces in background worker |
| Embedding generation | Yes | Batch embeddings, parallel API calls |
| Trace analysis | Yes | Multiple critics analyze different traces |

### 9.3 Memory Footprint Targets

| Component | Target | Measurement |
|-----------|--------|-------------|
| Skeleton cache | <50MB for 50k LOC | RSS memory |
| SQLite database | <500MB | File size |
| Vector index | <200MB | sqlite-vec index size |
| In-flight traces | <100MB | Session peak |
| **Total target** | **<1GB** | Typical workload |

### 9.4 Implementation Tasks

| Task | File(s) | Priority | Dependencies |
|------|---------|----------|--------------|
| Layered cache | `core/utils/cache.py` | P0 | None |
| Async parsing pool | `core/context/parser_pool.py` | P1 | Context mgmt |
| Background workers | `core/utils/workers.py` | P1 | None |
| Memory profiler | `scripts/profile_memory.py` | P2 | None |
| Benchmark harness | `tests/benchmarks/performance.py` | P1 | Testing framework |

---

## 10. Collaboration & Multi-User

### 10.1 Team Memory Sync Architecture

```
┌─────────────────┐         HTTPS          ┌─────────────────┐
│   User A        │                        │   Sync Server   │
│   noman         │ ◄────────────────────► │   (optional)    │
│   memory.db     │                        │                 │
└─────────────────┘                        └────────┬────────┘
                                                   │
                                          ┌────────▼────────┐
                                          │   User B        │
                                          │   noman         │
                                          │   memory.db     │
                                          └─────────────────┘
```

### 10.2 Sync Configuration

```toml
# user/config.toml

[collaboration]
team_id = "acme-corp/engineering"
sync_endpoint = "https://internal-noman.acme.com/sync"
auth_token = "${NOMAN_TEAM_TOKEN}"
push_on_session_end = true
pull_on_init = true
conflict_resolution = "last-write-wins"  # or "manual"

[sync_filters]
# What to sync
include_tiers = ["semantic", "procedural"]
exclude_tiers = ["episodic"]
include_scopes = ["project", "team"]
exclude_scopes = ["personal"]
```

### 10.3 Conflict Resolution

```python
# core/collaboration/conflicts.py

from dataclasses import dataclass
from datetime import datetime

@dataclass
class SyncConflict:
    local_fact: dict
    remote_fact: dict
    conflict_type: str  # "divergent_values", "both_modified", "deleted_vs_modified"
    detected_at: datetime

class ConflictResolver:
    """Resolve sync conflicts."""
    
    def __init__(self, strategy: str = "last-write-wins"):
        self.strategy = strategy
    
    def resolve(self, conflict: SyncConflict) -> dict | None:
        """Return winning fact, or None to delete."""
        
        if self.strategy == "last-write-wins":
            local_time = datetime.fromisoformat(conflict.local_fact["timestamp"])
            remote_time = datetime.fromisoformat(conflict.remote_fact["timestamp"])
            return conflict.local_fact if local_time > remote_time else conflict.remote_fact
        
        elif self.strategy == "manual":
            # Queue for user resolution
            queue_for_review(conflict)
            return None
        
        elif self.strategy == "merge":
            # Attempt semantic merge (for compatible facts)
            return self._try_merge(conflict)
```

### 10.4 Implementation Tasks

| Task | File(s) | Priority | Dependencies |
|------|---------|----------|--------------|
| Sync protocol | `core/collaboration/protocol.py` | P2 | Memory system |
| Conflict detector | `core/collaboration/conflicts.py` | P2 | Memory system |
| Sync CLI | `cli/commands/collaboration.py` | P2 | CLI surface |
| Reference server | `servers/sync_server.py` | P3 | Sync protocol |

---

## 11. Implementation Checklist

### Phase 0: Foundation (Weeks 1-2)
- [ ] Model Adapter base interface
- [ ] OpenAI-compatible adapter
- [ ] Ollama adapter
- [ ] Role router
- [ ] CLI argument parser
- [ ] REPL implementation
- [ ] Init command
- [ ] Basic error handling

### Phase 1-3: Core Subsystems (Weeks 3-10)
- [x] Context Management (existing `context.md`)
- [x] Memory System (existing `memory.md`)
- [x] Orchestrator (existing `orchestrator.md`)
- [x] Tool Bus (existing `tools.md`)
- [ ] Filesystem sandbox
- [ ] Process sandbox
- [ ] Checkpoint manager

### Phase 4: Security (Weeks 11-12)
- [ ] Permission checker
- [ ] Core integrity verification
- [ ] Security test suite

### Phase 5: Self-Improvement (Weeks 13-15)
- [ ] Trace collector
- [ ] Critic agent
- [ ] Meta-agent
- [ ] Patch validator
- [ ] Rollback manager
- [ ] Review CLI command

### Phase 6-7: Polish (Weeks 16-20)
- [ ] Heuristic extraction
- [ ] Skill library
- [ ] Capability negotiation
- [ ] Observability logger
- [ ] Debug CLI commands
- [ ] Performance optimizations

### Phase 8-10: Extensions (Weeks 21-26)
- [ ] JSON-RPC server
- [ ] VS Code extension
- [ ] Neovim plugin
- [ ] Full test suite
- [ ] Benchmark suite
- [ ] Documentation

### Phase 11: v1.0 Release
- [ ] Community skill sharing
- [ ] Provider quirk flags
- [ ] Final polish
- [ ] Release candidates
- [ ] v1.0 launch

---

## Summary

This document provides detailed implementation plans for all remaining NoMan subsystems not covered in the existing design documents (`context.md`, `memory.md`, `orchestrator.md`, `tools.md`).

**Key deliverables organized by priority:**

**P0 (Critical Path):**
1. Model Adapter — Enables multi-provider support
2. Security Sandboxing — Required for safe tool execution
3. CLI Surface — User interface
4. Error Handling — Production readiness

**P1 (High Priority):**
5. Self-Improvement — Core differentiator
6. Testing Framework — Quality assurance
7. Observability — Debugging and monitoring
8. Performance Optimization — Scalability

**P2 (Enhancements):**
9. Editor Integrations — UX improvement
10. Collaboration — Team features

All plans align with the implementation roadmap in NOMAN_DESIGN.md §12 and can be executed in parallel where dependencies allow.
