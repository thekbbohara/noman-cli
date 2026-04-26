# NoMan CLI

A model-agnostic agentic coding CLI with a Textual-based TUI. NoMan can run tasks autonomously, maintain context across sessions, manage memory, and self-improve over time.

## Features

- **Multi-provider**: Anthropic Claude, OpenAI, and any OpenAI-compatible API (Ollama, Groq, Azure)
- **TUI/REPL**: Textual-based interactive interface with session history, model switching, and diff view
- **Task mode**: Run single tasks non-interactively
- **Session persistence**: Context survives across sessions via SQLite-backed memory
- **Self-improvement**: Trace analysis, meta-agent proposals, rollback management
- **Security**: Filesystem sandbox, network sandbox, tool signing, safety guardrails
- **35+ tools**: File ops, git, search, docker, cron, browser, and more

## Tech Stack

| Category | Technology |
|---|---|
| Language | Python 3.11+ |
| Build | Hatchling |
| Linter | Ruff |
| Type Checker | mypy |
| TUI | Textual |
| Test | pytest + pytest-asyncio |

## Requirements

- Python 3.11 or later
- API key for your chosen provider (ANTHROPIC_API_KEY or OPENAI_API_KEY)

## Quick Start

```bash
# Install
pip install -e .

# Run a task
noman "Add error handling to the login module"

# Start interactive TUI
noman

# Check configuration and connectivity
noman doctor
```

## Configuration

Run `noman init` to scaffold `~/.noman/config.toml`, or create it manually:

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

See `.env.example` for all supported environment variables.

## Commands

| Command | Description |
|---|---|
| `noman <task>` | Run a task (default mode) |
| `noman` | Start REPL/TUI session |
| `noman doctor` | Health check: config, providers, memory |
| `noman init` | Scaffold `.noman/` directory |
| `noman review [file] [-n N]` | Show git diffs |
| `noman rollback [-n N]` | List or restore previous modifications |
| `noman memory <subcmd>` | Manage memory entries |
| `noman skill <subcmd>` | Manage skills |
| `noman stats` | Show execution statistics |
| `noman emergency stop` | Halt all agent operations |

## Testing

```bash
pytest tests/ -v
pytest tests/ -v --cov=cli --cov=core --cov-report=term-missing
```

## Project Structure

```
noman-cli/
├── cli/                    # CLI entry point, parser, TUI
├── core/
│   ├── adapters/           # Model providers
│   ├── context/            # Context management
│   ├── errors/             # Error hierarchy, circuit breakers
│   ├── memory/             # Memory system
│   ├── orchestrator/       # ReAct loop orchestrator
│   ├── security/           # Sandboxing, signing
│   ├── selfimprove/        # Self-improvement system
│   ├── tools/              # Tool bus + tool handlers
│   └── utils/              # Utilities
├── docs/                   # Documentation
├── tests/                  # Test suite
├── pyproject.toml
└── user/                   # Config templates
```

## Common Commands

```bash
make lint      # Run ruff check
make lint-fix  # Run ruff check --fix
make typecheck # Run mypy
make test      # Run pytest
make test-cov  # Run pytest with coverage
make dev       # Start TUI in dev mode
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup and guidelines.

## License

MIT
