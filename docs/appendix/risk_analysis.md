# Risk Analysis & Mitigation

> *Parent: [ARCHITECTURE.md](../ARCHITECTURE.md)*

---

## Technical Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Tree-sitter parsing too slow for large repos | Medium | High | Incremental parsing, background workers, caching |
| PageRank computation expensive on every file change | Medium | Medium | Incremental graph updates, debounced recomputation |
| SQLite + sqlite-vec performance degrades with large memory | Low | High | Regular vacuum, partition old episodic memory, index optimization |
| Local models produce poor tool-calling output | High | High | Fallback to stronger models, better prompt engineering, few-shot examples |
| Self-improvement makes things worse | Medium | High | Conservative auto-promote thresholds, easy rollback, human approval for major changes |
| Sandboxing breaks legitimate tool functionality | Medium | Medium | Extensive allowlist testing, escape hatch for trusted users |

## Product Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Users don't trust agent with write access | High | High | Default to read-only mode, clear audit trail, easy undo |
| Learning curve too steep for new users | Medium | Medium | Interactive tutorial, sensible defaults, `noman explain` mode |
| Performance perceived as slow vs. competitors | Medium | High | Aggressive caching, streaming responses, progress indicators |
| Feature creep dilutes focus | Medium | Medium | Strict adherence to non-goals, community-driven prioritization |

## Ecosystem Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Major LLM provider changes API breaking compatibility | Low | High | Abstraction layer, multi-provider support, rapid adapter updates |
| Local model ecosystem fragments | Medium | Medium | Stick to OpenAI-compat standard, community-maintained adapters |
| Security vulnerability in dependency chain | Medium | High | Regular audits, pinned dependencies, minimal attack surface |

---

*See also: [Open Questions](open_questions.md) for unresolved design decisions.*
