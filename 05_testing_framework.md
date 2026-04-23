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

