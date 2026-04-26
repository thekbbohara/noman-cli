.PHONY: install dev lint typecheck test test-cov clean help

.DEFAULT_GOAL := help

help: ## Show this help message
	@echo "NoMan CLI — Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Install package in development mode
	pip install -e ".[dev]"

dev: ## Run tests in watch mode
	python -m pytest tests/ -v --forked -x -W

lint: ## Run ruff linter
	.venv/bin/ruff check .

lint-fix: ## Run ruff linter with auto-fix
	.venv/bin/ruff check . --fix

typecheck: ## Run mypy type checking
	.venv/bin/mypy .

test: ## Run test suite
	.venv/bin/python -m pytest tests/ -v --tb=short

test-cov: ## Run tests with coverage report
	.venv/bin/python -m pytest tests/ -v --tb=short --cov=cli --cov=core --cov-report=term-missing

clean: ## Remove build artifacts and caches
	find . -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name '.mypy_cache' -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name '.ruff_cache' -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name '.pytest_cache' -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name '.coverage' -exec rm -rf {} + 2>/dev/null || true
	rm -rf build/ dist/ *.egg-info .noman/memory.db 2>/dev/null || true
