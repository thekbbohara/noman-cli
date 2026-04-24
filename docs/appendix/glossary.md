# Glossary

> *Parent: [ARCHITECTURE.md](../ARCHITECTURE.md)*

| Term | Definition |
|------|------------|
| **Context Frugality** | Design principle of minimizing token usage through selective loading |
| **Overlay Architecture** | Three-region repo layout (`core/`, `overlay/`, `user/`) enabling conflict-free self-modification |
| **Skeleton Map** | Compressed representation of repo structure (signatures only, no bodies) |
| **PageRank Symbols** | Symbol importance ranking based on call/import graph centrality |
| **JIT Loading** | Just-in-time fetching of code content only when needed |
| **Tiered Memory** | Memory split into episodic (traces), semantic (facts), procedural (skills) |
| **Fact Extraction** | Process of distilling session traces into atomic, durable facts |
| **Trace Critic** | Agent that scores execution traces on success, efficiency, correctness |
| **Meta-Agent** | Agent that analyzes critic scores and proposes prompt/tool improvements |
| **Skill** | Reusable task trajectory distilled from successful past executions |
| **Heuristic** | Localized rule-of-thumb triggered by specific contexts |
| **Tool Bus** | Discovery, registration, and execution layer for agent tools |
| **Model Adapter** | Abstraction layer normalizing different LLM provider APIs |
| **Role Routing** | Using different models for planner, executor, critic roles |
| **Capability Negotiation** | Startup probing of provider capabilities and quirks |
