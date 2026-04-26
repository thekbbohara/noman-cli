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
| Purpose & README | 5/5 | 5/5 | Root README.md created; pypi discoverability fixed |
| Setup Reproducibility | 5/5 | 5/5 | .env.example, pyproject.toml dev deps, Makefile |
| Build Command | 5/5 | 5/5 | `pip install -e .` works |
| Test Command | 5/5 | 5/5 | 274/274 passing |
| Lint/Format | 3/5 | 3/5 | 33 ruff errors remain (all E501 line length — cosmetic) |
| Type/Static Checks | 2/5 | 5/5 | mypy clean (0 errors) — fixed Textual overrides, union-attr, missing method |
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
| `ruff check .` | 33 errors (all E501 line length — cosmetic, not auto-fixable) |
| `mypy .` | 0 errors — clean |

## Completed Improvements (Ralph Loop)

### STORY-1: mypy union-attr in core/memory/store.py
- Added `_require_conn()` helper that asserts connection is available
- Replaced all `self._conn` in public methods with `self._require_conn()`
- Result: 0 mypy errors in store.py

### STORY-2/6: Textual override fixes + Session | None guard
- Fixed `TrackedRichLog.write()` return type → `RichLog`
- Fixed `TrackedRichLog.clear()` signature to match Textual stubs
- Added `scroll_end` parameter to `clear()` and `notify()` severity `'information'`
- Added `_require_conn()` pattern for safe database access
- Added None guard in `_execute_turn_with_tools()` for `_current_session`

### STORY-3/5: ChangeType StrEnum + AVAILABLE_TOOLS/SYSTEM_PROMPT rename
- Changed `ChangeType` from `(str, Enum)` to `StrEnum`
- Renamed `AVAILABLE_TOOLS` → `available_tools`, `SYSTEM_PROMPT` → `system_prompt`
- Updated test references in `test_orchestrator.py`

### Bonus: Fixed missing `_propose_bug_fix` method
- Added the missing method that was called but never defined
- Returns `ImprovementProposal` with `BUG_FIX` change type

### Other: Root README.md + pyproject.toml readme
- Created root `README.md` for pypi discoverability
- Uncommented `readme` field in pyproject.toml

### Duplicate imports removed
- Fixed 5 F811 errors in `test_selfimprove.py`

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
