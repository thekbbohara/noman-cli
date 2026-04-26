# Contributing to NoMan CLI

Thank you for your interest in NoMan CLI! This document covers how to get started and contribute.

## Development Setup

```bash
# Clone the repo
git clone https://github.com/kb26/noman-cli.git
cd noman-cli

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate

# Install in development mode with dev dependencies
pip install -e ".[dev]"

# Run tests
python -m pytest tests/ -v
```

## Code Style

- **Line length**: 100 characters
- **Linter**: Ruff (auto-fixable with `ruff check . --fix`)
- **Type checker**: mypy (`mypy .`)
- **Docstrings**: Google-style preferred (D101-D107 docstring checks are intentionally disabled)

## Project Structure

```
noman-cli/
├── cli/                    # CLI entry point, parser, TUI
├── core/
│   ├── adapters/           # Model providers (OpenAI, Anthropic)
│   ├── context/            # Context management
│   ├── errors/             # Error hierarchy
│   ├── memory/             # Memory system
│   ├── orchestrator/       # ReAct loop orchestrator
│   ├── security/           # Sandboxing, signing
│   ├── selfimprove/        # Self-improvement
│   ├── tools/              # Tool bus + handlers
│   └── utils/              # Utilities
├── docs/                   # Documentation (versioned)
├── tests/                  # Test suite
├── pyproject.toml
└── user/                   # User overlay files
```

## Testing

Run the full suite:

```bash
python -m pytest tests/ -v
```

With coverage:

```bash
python -m pytest tests/ -v --cov=cli --cov=core --cov-report=term-missing
```

## Making Changes

1. Create a feature branch from `main`
2. Make your changes
3. Run `ruff check . --fix` and `mypy .`
4. Ensure all tests pass
5. Submit a pull request

## Pull Request Guidelines

- Include a clear description of what changed
- Reference any relevant issues
- Add/update tests for new functionality
- Update documentation if behavior changes
