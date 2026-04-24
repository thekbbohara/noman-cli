# NoMan CLI — Design Document Audit & Fixes

> **Date:** 2026-04-24
> **Auditor:** Cline
> **Status:** ISSUES FOUND — Consolidation Required

---

## Executive Summary

The noman-cli design documentation is comprehensive (~120K words across 18 files) but has significant organizational problems that will slow down implementation and confuse contributors. This audit identifies the issues and provides a remediation plan.

---

## 1. Critical Issues Found

### 1.1 Duplicate Content (SEVERITY: HIGH)

| File | Size | Content | Problem |
|------|------|---------|---------|
| `REMAINING_PLANS.md` | 55KB | Monolithic plan with sections 1-10 + dependencies | Overlaps with `01_model_adapter.md` through `10_collaboration_multi_user.md` |
| `REMAINING_PLANS_FIXED.md` | 78KB | Same as above but with security fixes + sections 11-12 + corrected priorities | Same overlap, PLUS divergence from REMAINING_PLANS.md creates confusion |
| `01_model_adapter.md` | 13KB | Section 1 extracted | Same content in REMAINING_PLANS.md |
| `02_self_improvement.md` | 17KB | Section 2 extracted | Same content in REMAINING_PLANS.md |
| ... | ... | ... | ... |
| `10_collaboration_multi_user.md` | 10KB | Section 10 extracted | Same content in REMAINING_PLANS.md |

**Impact:** Developers reading different files get different versions of the same design. The FIXED version has security corrections that the numbered files may or may not have.

### 1.2 Content Drift Between Versions (SEVERITY: HIGH)

`REMAINING_PLANS_FIXED.md` is NOT a pure superset of `REMAINING_PLANS.md`. Key differences:

| Aspect | REMAINING_PLANS.md | REMAINING_PLANS_FIXED.md |
|--------|-------------------|-------------------------|
| Section 3.2.3 (Network Sandbox) | Empty/placeholder | **FULLY IMPLEMENTED** with deny-all policy, metadata service blocking, private IP protection |
| Section 3.5 (Tool Bus Security) | Empty `pass` for signature verification | **SECURITY HARDENED** with whitelist-only loading |
| Section 3.6 (Git Safety) | Not present | **NEW** - SafeGitOperations with protected branches |
| Section 3.7 Implementation Tasks | Mixed priorities | **CORRECTED** - Tool signing P2→P0, Security tests P1→P0 |
| Section 5.5 (Adversarial Testing) | Listed as P2 | **UPGRADED TO P0** with full test suites |
| Section 8.4 (Circuit Breakers) | Not present | **NEW** - CircuitBreaker + ErrorBoundary |
| Section 8.5 (Disaster Recovery) | Not present | **NEW** - Full recovery plan with kill switches |
| Section 9.5 (Rate Limiting) | Different implementation | **NEW** - QuotaConfig + RateLimiter + QuotaManager |
| Section 12 (Dependency Graph) | Not present | **NEW** - Week-by-week build order |

**Impact:** The FIXED version has critical security fixes that MUST be used. Keeping the old version risks someone implementing the wrong (insecure) version.

### 1.3 Fragmented Master Design (SEVERITY: MEDIUM)

`NOMAN_DESIGN.md` (47KB) is the "master" document but references subsystems that are documented in separate files:
- `context.md` (30KB) — detailed context management
- `memory.md` (31KB) — detailed memory system
- `orchestrator.md` (29KB) — detailed orchestrator
- `tools.md` (46KB) — detailed tool bus

These detailed documents contain implementation code and schemas that aren't in NOMAN_DESIGN.md. A developer reading only NOMAN_DESIGN.md would miss critical implementation details.

### 1.4 Inconsistent File Naming (SEVERITY: LOW)

- Numbered files: `01_model_adapter.md` (underscore)
- Top-level files: `NOMAN_DESIGN.md` (no numbers)
- Mixed: `context.md`, `memory.md` (no numbers, not in REMAINING_PLANS)
- The numbered files correspond to sections in REMAINING_PLANS but aren't clearly labeled as such

### 1.5 Missing Consolidated Implementation Guide (SEVERITY: MEDIUM)

There's no single file that answers: "What should I implement first, and in what order?"
- REMAINING_PLANS_FIXED.md has a dependency graph (§12) but it's buried
- Each subsystem file has its own task list
- No unified priority view across all subsystems

---

## 2. Security Issues in "Non-Fixed" Versions

The following security vulnerabilities exist in REMAINING_PLANS.md and/or the numbered files that are FIXED in REMAINING_PLANS_FIXED.md:

| # | Vulnerability | Location (Old) | Fix (New) |
|---|--------------|----------------|-----------|
| 1 | Empty network sandbox (`pass`) | `03_security_sandboxing.md` §3.2.3 | Full deny-all implementation with metadata service blocking |
| 2 | Pickle-based cache (arbitrary code exec) | `09_performance_optimization.md` §9.1 | JSON-only serialization |
| 3 | String-based command filtering (bypassable) | `03_security_sandboxing.md` §3.2 | AST-based validation with regex layers |
| 4 | No tool signature verification | `03_security_sandboxing.md` §3.5 | ed25519 manifest signing |
| 5 | Meta-agent can modify its own constraints | `02_self_improvement.md` §2.7 | Immutable FrozenSet constraints + self-protection |
| 6 | No rate limiting (DoS vulnerability) | Not present | Full quota management per minute/hour/day |
| 7 | No circuit breakers (cascading failures) | Not present | CircuitBreaker + ErrorBoundary per subsystem |
| 8 | No disaster recovery plan | Not present | Full recovery with backup strategy + kill switches |

**RECOMMENDATION:** Delete REMAINING_PLANS.md and all numbered files that don't have the fixes. Keep only REMAINING_PLANS_FIXED.md as the canonical implementation plan.

---

## 3. Recommended Directory Restructure

```
noman-cli/
├── docs/
│   ├── README.md                          ← Start here: project overview
│   ├── ARCHITECTURE.md                    ← System overview (from NOMAN_DESIGN.md §1-3)
│   ├── IMPLEMENTATION_PLAN.md             ← Canonical plan (from REMAINING_PLANS_FIXED.md)
│   ├── SECURITY.md                        ← Security model + threat model
│   ├── subsystem/
│   │   ├── context.md                     ← From context.md
│   │   ├── memory.md                      ← From memory.md
│   │   ├── orchestrator.md                ← From orchestrator.md
│   │   ├── tools.md                       ← From tools.md
│   │   ├── model_adapter.md               ← From 01_model_adapter.md (fixed version)
│   │   ├── self_improvement.md            ← From 02_self_improvement.md (fixed version)
│   │   ├── security_sandboxing.md         ← From 03_security_sandboxing.md (fixed version)
│   │   ├── cli_surface.md                 ← From 04_cli_surface.md
│   │   ├── testing_framework.md           ← From 05_testing_framework.md (fixed version)
│   │   ├── observability.md               ← From 06_observability_debugging.md
│   │   ├── editor_integrations.md         ← From 07_editor_integrations.md
│   │   ├── error_handling.md              ← From 08_error_handling_recovery.md (fixed version)
│   │   ├── performance.md                 ← From 09_performance_optimization.md (fixed version)
│   │   └── collaboration.md               ← From 10_collaboration_multi_user.md (fixed version)
│   └── appendix/
│       ├── glossary.md                    ← From NOMAN_DESIGN.md §15
│       ├── risk_analysis.md               ← From NOMAN_DESIGN.md §13
│       └── open_questions.md              ← From NOMAN_DESIGN.md §14
├── core/                                   ← IMPLEMENTATION: Core code (immutable)
├── overlay/                                ← IMPLEMENTATION: Agent-writable
├── user/                                   ← IMPLEMENTATION: User config
├── .noman/                                 ← IMPLEMENTATION: Runtime data
├── tests/                                  ← IMPLEMENTATION: Test suites
├── cli/                                    ← IMPLEMENTATION: CLI entrypoint
├── extensions/                             ← IMPLEMENTATION: Editor plugins
└── pyproject.toml / setup.py               ← IMPLEMENTATION: Package config
```

---

## 4. Consolidation Action Items

### Phase 1: Cleanup ✅ COMPLETED
- [x] Audit all files and identify duplicates
- [x] Delete `REMAINING_PLANS.md` (superseded by FIXED version)
- [x] Delete numbered files `01_model_adapter.md` through `10_collaboration_multi_user.md` (content is in REMAINING_PLANS_FIXED.md)
- [x] Create `docs/` directory structure
- [x] Move `NOMAN_DESIGN.md` → `docs/ARCHITECTURE.md`
- [x] Move `REMAINING_PLANS_FIXED.md` → `docs/IMPLEMENTATION_PLAN.md`
- [x] Move `context.md`, `memory.md`, `orchestrator.md`, `tools.md` → `docs/subsystem/`

### Phase 2: Merge & Deduplicate ✅ COMPLETED
- [x] Extract glossary from NOMAN_DESIGN.md → `docs/appendix/glossary.md`
- [x] Extract risk analysis from NOMAN_DESIGN.md → `docs/appendix/risk_analysis.md`
- [x] Extract open questions from NOMAN_DESIGN.md → `docs/appendix/open_questions.md`
- [x] Create `docs/README.md` as entrypoint
- [x] Fix `.gitignore` to NOT ignore `*.md` files

### Phase 3: Implementation Setup (Next Session)
- [ ] Create `pyproject.toml` with dependencies
- [ ] Scaffold `core/`, `cli/`, `tests/` directories
- [ ] Set up basic project structure

---

## 5. Quick Reference: File Purposes After Cleanup

| File | Purpose | Reader |
|------|---------|--------|
| `docs/README.md` | Project intro, quickstart | Everyone |
| `docs/ARCHITECTURE.md` | System design, principles, data flow | New contributors |
| `docs/IMPLEMENTATION_PLAN.md` | What to build, in what order | Implementers |
| `docs/SECURITY.md` | Threat model, sandboxing, guardrails | Security reviewers |
| `docs/subsystem/*.md` | Deep-dive per subsystem | Implementers working on specific area |
| `docs/appendix/*.md` | Reference material | As needed |

---

## 6. Files to DELETE

The following files are duplicates or superseded and should be removed:

```bash
# Superseded by REMAINING_PLANS_FIXED.md
REMAINING_PLANS.md
01_model_adapter.md
02_self_improvement.md
03_security_sandboxing.md
04_cli_surface.md
05_testing_framework.md
06_observability_debugging.md
07_editor_integrations.md
08_error_handling_recovery.md
09_performance_optimization.md
10_collaboration_multi_user.md
```

The following files should be MOVED:
```bash
NOMAN_DESIGN.md → docs/ARCHITECTURE.md
REMAINING_PLANS_FIXED.md → docs/IMPLEMENTATION_PLAN.md
context.md → docs/subsystem/context.md
memory.md → docs/subsystem/memory.md
orchestrator.md → docs/subsystem/orchestrator.md
tools.md → docs/subsystem/tools.md
```

---

*End of audit. Proceed to Phase 1 cleanup.*
