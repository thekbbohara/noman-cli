# NoMan CLI — Documentation

> A model-agnostic agentic coding CLI that handles complex tasks even with a low context window.

## Quick Start

1. **New to the project?** → Read [`ARCHITECTURE.md`](ARCHITECTURE.md) for system overview
2. **Ready to implement?** → Read [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) for build order
3. **Working on a subsystem?** → See [`subsystem/`](subsystem/) for deep-dive docs
4. **Need reference material?** → See [`appendix/`](appendix/) for glossary, risks, open questions

## Document Index

### Core Documents

| Document | Purpose |
|----------|---------|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | System design, principles, data flow, repository layout |
| [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) | What to build, in what order, with dependencies |

### Subsystem Deep-Dives

| Document | Subsystem | Status |
|----------|-----------|--------|
| [`subsystem/context.md`](subsystem/context.md) | Context Management (skeleton, PageRank, JIT) | Ready |
| [`subsystem/memory.md`](subsystem/memory.md) | Memory System (SQLite, tiered, embeddings) | Ready |
| [`subsystem/orchestrator.md`](subsystem/orchestrator.md) | Orchestrator (ReAct loop, budget, tools) | Ready |
| [`subsystem/tools.md`](subsystem/tools.md) | Tool Bus (registry, sandbox, execution) | Ready |

### Appendix

| Document | Purpose |
|----------|---------|
| [`appendix/glossary.md`](appendix/glossary.md) | Terminology and definitions |
| [`appendix/risk_analysis.md`](appendix/risk_analysis.md) | Technical, product, and ecosystem risks |
| [`appendix/open_questions.md`](appendix/open_questions.md) | Unresolved design decisions |

## Design Principles

1. **Context Frugality** — Operates efficiently within 4K–32K token windows
2. **Persistent Memory** — Learns continuously via SQLite-backed tiered memory
3. **Self-Improvement** — Autonomously rewrites prompts, heuristics, and skills
4. **Conflict-Free Updates** — Three-region layout (`core/`, `overlay/`, `user/`) prevents merge conflicts

## Repository Layout

```
noman-cli/
├── docs/              ← You are here
├── core/              ← Immutable agent code
├── overlay/           ← Agent-writable (self-modifications)
├── user/              ← User config and plugins
├── .noman/            ← Runtime data (never tracked)
├── tests/             ← Test suites
└── cli/               ← CLI entrypoint
```

---

*For implementation status and security considerations, see [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md).*
