# NoMan CLI

A model-agnostic agentic coding CLI with a Textual-based TUI. NoMan can run tasks autonomously, maintain context across sessions, manage memory, and self-improve over time.

## Installation

```bash
pip install -e .
```

Or with uv:

```bash
uv pip install -e .
```

## Quick Start

### Task Mode

Run a single task:

```bash
noman "Add error handling to the login module"
```

### REPL Mode

Interactive session:

```bash
noman
```

### Doctor

Check configuration and connectivity:

```bash
noman doctor
```

## Commands

| Command | Description |
|---------|-------------|
| `noman <task>` | Run a task (default mode) |
| `noman` | Start REPL/TUI session |
| `noman doctor` | Health check: config, providers, memory |
| `noman init` | Scaffold `.noman/` directory with config template |
| `noman review [file] [-n N]` | Show git diffs (file or last N commits) |
| `noman rollback [-n N] [-l] [--to ID]` | List or restore previous self-modifications |
| `noman memory list [-t tier] [-s scope]` | List memory entries |
| `noman memory get <tier> <scope> <key>` | Get a memory entry |
| `noman memory set <tier> <scope> <key> <value>` | Store a memory entry |
| `noman memory delete <tier> <scope> <key>` | Delete a memory entry |
| `noman skill list` | List all skills |
| `noman skill get <name>` | Get skill content |
| `noman skill set <name> <content>` | Set skill content |
| `noman skill add <name> <file>` | Add skill from file |
| `noman stats` | Show execution statistics |
| `noman emergency stop` | Emergency stop all agent operations |
| `noman --help` | Show help |

### Flags

| Flag | Description |
|------|-------------|
| `-p, --provider <name>` | Override provider |
| `-m, --max-calls <N>` | Max tool calls per turn |
| `--debug` | Enable debug logging |
| `--version` | Show version |

## Configuration

Run `noman init` to create `~/.noman/config.toml`, or create it manually:

```toml
[model]
default = "claude"
token_budget = 8000

[[providers]]
id = "claude"
type = "anthropic"
api_key = "${ANTHROPIC_API_KEY}"
model = "claude-sonnet-4-20250514"

[[providers]]
id = "openai"
type = "openai"
api_key = "${OPENAI_API_KEY}"
model = "gpt-4o"
```

### Provider Types

| Type | Compatible With |
|------|----------------|
| `openai` | OpenAI, Ollama, Groq, Azure OpenAI |
| `anthropic` | Anthropic Claude |

### Environment Variables

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `OPENAI_API_KEY` | OpenAI API key |
| `NOMAN_DEBUG` | Set to "1" for debug logging |
| `NOMAN_EMERGENCY_STOP` | Set to "1" to halt agent operations |

## Architecture

- **Orchestrator**: ReAct loop with tool execution, budget guard, session persistence
- **Adapters**: OpenAI-compatible and Anthropic providers with role-based routing
- **Memory**: SQLite-backed tiered storage (episodic, semantic, procedural)
- **Context**: Skeleton maps with centrality scoring, JIT loading
- **Tools**: 35+ tools (file ops, git, search, docker, etc.)
- **Security**: Filesystem sandbox, network sandbox, tool signing
- **Self-Improvement**: Trace critic, meta-agent, rollback manager
- **TUI**: Textual-based REPL with diff view, model switching, history

## Testing

```bash
python -m pytest tests/ -v
```

## Directory Structure

```
noman-cli/
├── cli/                    # CLI entry point, parser, TUI
│   ├── main.py             # Entry point with all commands
│   ├── parser.py           # Argument parser
│   ├── tui.py              # Textual TUI app
│   └── config_validator.py # Config validation
├── core/
│   ├── adapters/           # Model providers (OpenAI, Anthropic)
│   ├── context/            # Context management
│   ├── errors/             # Error hierarchy, circuit breakers
│   ├── memory/             # Memory system
│   ├── orchestrator/       # ReAct loop orchestrator
│   ├── security/           # Sandboxing, signing
│   ├── selfimprove/        # Self-improvement system
│   ├── tools/              # Tool bus + tool handlers
│   └── utils/              # Utilities (retry, rate limiter, etc.)
├── docs/                   # Documentation
├── tests/                  # Test suite
│   ├── unit/               # Unit tests
│   ├── adversarial/        # Injection tests
│   └── chaos/              # Failure mode tests
├── pyproject.toml
└── user/config.toml        # User config template
```
