# Superproject Upgrade — noman-cli

## Audit Date
2026-04-26 (updated)

## Detected Stack

| Category | Value |
|---|---|
| Language | Python 3.11+ |
| Build | Hatchling |
| Package Manager | pip / uv |
| Linter | Ruff |
| Type Checker | mypy |
| Test Framework | pytest (asyncio auto) |
| TUI Framework | Textual |
| License | MIT |
| Version | 0.1.0 |

## Scorecard

| Area | Before | After | Notes |
|---|---:|---:|---|
| Purpose & README | 5/5 | 4/5 | docs/README.md exists but no root README.md (pypi discoverability gap) |
| Setup Reproducibility | 5/5 | 5/5 | .env.example, pyproject.toml dev deps, Makefile |
| Build Command | 5/5 | 5/5 | `pip install -e .` works |
| Test Command | 5/5 | 5/5 | 274/274 passing |
| Lint/Format | 3/5 | 3/5 | 41 ruff errors remain (mostly E501 line length) |
| Type/Static Checks | 2/5 | 2/5 | 20 mypy errors (mostly Textual override signature issues) |
| Architecture Clarity | 5/5 | 5/5 | Excellent docs/ARCHITECTURE.md, docs/subsystem/ |
| Error Handling | 4/5 | 4/5 | Circuit breakers, guardrails present |
| Security Hygiene | 4/5 | 4/5 | .env.example, SECURITY.md, sandboxing, no secrets committed |
| Environment Config | 3/5 | 3/5 | .env.example good, config.toml documented |
| CI/CD | 2/5 | 2/5 | GitHub Actions exists (lint + mypy + pytest on 3.11-3.13) |
| Developer Experience | 4/5 | 4/5 | Makefile, hatch scripts, 35+ tools |
| Release Hygiene | 2/5 | 2/5 | CHANGELOG.md exists; no versioning automation |
| Maintainability | 5/5 | 5/5 | 274 passing tests, good structure |
| **Total** | **47/65** | **47/65** | No change this pass — audit only |

## Current Verification

| Command | Result |
|---|---|
| `pytest tests/ -v` | 274 passed |
| `ruff check .` | 41 errors (30 E501 line length, 5 F811 redefinition, 2 N802 naming, 2 UP042, 2 others) |
| `mypy .` | 20 errors (10 union-attr on sqlite3.Connection, 6 Textual override issues, 4 other) |

## Remaining Recommendations

### Quick Wins (low risk, high impact)
1. **Create root README.md** — link to or inline the docs/README.md content for pypi/npm discoverability
2. **Uncomment `readme` in pyproject.toml** — point to docs/README.md
3. **Fix duplicate imports in test_selfimprove.py** — 5 F811 errors from double imports

### Medium Priority
4. **Fix mypy union-attr errors in core/memory/store.py** — add null checks for `self._conn` before `.execute()`/`.commit()` calls (10 errors)
5. **Fix Textual RichLog override signatures in cli/tui.py** — 6 errors from overriding `write`, `clear`, `write_markup` with incompatible signatures
6. **Fix ChangeType inheritance** — use `StrEnum` instead of `(str, Enum)` (core/selfimprove/meta_agent.py:18)
7. **Fix AVAILABLE_TOOLS/SYSTEM_PROMPT naming** — rename to `available_tools`/`system_prompt` per N802

### Lower Priority
8. **Fix E501 line length violations** — 30 remaining, mostly in cli/tui.py (UI strings) and tests
9. **Add pre-commit hooks** — ruff + mypy for local enforcement
10. **Add Dockerfile** — reproducible dev environment
11. **Integration tests** — only 2 exist; add provider integration smoke tests
12. **Automated releases** — version bumping/tagging automation
13. **TypedDict/dataclass migration** — adapter configs still use dict-based patterns

## Files Changed This Pass

- `SUPERPROJECT.md` — updated scorecard and recommendations based on fresh audit

## Maintainer Notes

- The project has been previously audited; this pass confirms the scorecard is stable
- 274 tests all pass — this is the project's strongest asset
- The main gaps are: missing root README.md, 41 lint errors, 20 type errors
- CI runs on push/PR but mypy is failing in CI (20 errors) — needs fixing before merge
- The `readme` field in pyproject.toml is commented out — should point to docs/README.md
