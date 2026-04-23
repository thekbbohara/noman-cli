# Running NoMan CLI (Phase 0)

## Prerequisites
The virtual environment is already set up in `.venv/`.

## Activate environment
```bash
source .venv/bin/activate
```

## Run tests
```bash
PYTHONPATH=. pytest tests/ -v
```

## Run the CLI
```bash
# REPL mode
PYTHONPATH=. python -m cli.main

# Task mode
PYTHONPATH=. python -m cli.main "refactor auth module"

# Commands
PYTHONPATH=. python -m cli.main doctor
PYTHONPATH=. python -m cli.main emergency stop
PYTHONPATH=. python -m cli.main rollback --n 3
```

## Or use the entrypoint script directly
```bash
PYTHONPATH=. python cli/main.py doctor
```
