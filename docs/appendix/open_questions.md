# Open Questions

> *Parent: [ARCHITECTURE.md](../ARCHITECTURE.md)*

The following are unresolved and should be decided before Phase 2:

1. **Embedding model lock-in.** If a user swaps embedding models mid-life, all stored vectors become meaningless. Options: store embedding model version per row and re-embed on mismatch, or forbid swaps post-init. Leaning toward the former with lazy re-embedding on access.

2. **Critic bias.** The critic is itself an LLM — can it reliably score traces produced by an equally-capable LLM? May need human-labeled ground truth for bootstrapping, or a deterministic component (tests passing / linter clean) weighted into the score.

3. **Overlay portability.** Should `overlay/` be shareable across users ("download community skills")? Great for flywheel, risky for prompt injection. Probably yes with GPG/SSH signing and explicit user opt-in.

4. **Windows support.** Tree-sitter and sqlite-vec both have Windows wheels now, but `fork()`-style subprocess sandboxing doesn't. WSL-only for v0.1, native Windows post-v1 using Job Objects + AppContainer.

5. **Team sync architecture.** Should team collaboration use a central server or P2P sync? Central is easier for conflict resolution; P2P is more aligned with local-first ethos. Leaning toward hybrid: optional central relay with end-to-end encryption.

6. **Monetization path.** If this project becomes popular, what's the sustainable business model? Options: enterprise features (team sync, audit logs), hosted sync service, premium skill marketplace, consulting. Should not compromise core principles.
