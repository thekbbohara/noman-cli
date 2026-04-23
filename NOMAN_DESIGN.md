# NoMan CLI — Design Document

> *A model-agnostic agentic coding CLI. Handles complex tasks even with a low context window — works equally well against a 7B local model or a frontier cloud endpoint.*

**Version:** 0.1 (Design Draft)
**Status:** Proposal
**Binary:** `noman`

---

## 1. Vision & Principles

NoMan is a terminal-based coding agent built on three non-negotiable principles:

1. **Context Frugality** — Design for a 4K–32K token window as the common case. Never read a whole file if a signature will do. Never dump logs when atomic facts will do. The same discipline that makes a 7B local model viable also makes a frontier model cheaper and faster.
2. **Persistent Memory** — The agent gets smarter the longer you use it. Memory is local, portable, and git-versionable — independent of which model is wired up behind it.
3. **Self-Improvement** — The agent rewrites its own prompts, heuristics, and skills based on what actually worked. The user can push upstream changes without ever hitting a merge conflict with the agent's learnings.

The guiding design tension throughout this document: **every feature must justify its token cost, and every self-modification must be isolatable from upstream code.**

---

## 2. System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      noman CLI (entrypoint)                 │
└─────────────────┬───────────────────────────────────────────┘
                  │
     ┌────────────▼────────────┐
     │     Orchestrator        │  ← ReAct loop + budget guard
     └─┬──────┬──────┬──────┬──┘
       │      │      │      │
   ┌───▼──┐ ┌─▼──┐ ┌─▼───┐ ┌▼──────┐
   │ A.   │ │ B. │ │ C.  │ │ Tool  │
   │Ctx   │ │Mem │ │Self │ │Bus    │
   │Mgmt  │ │    │ │Impr │ │       │
   └──────┘ └────┘ └─────┘ └───────┘
       │      │      │        │
       └──────┴──────┴────────┘
                  │
       ┌──────────▼──────────┐
       │  Model Adapter      │  ← OpenAI-compat (primary) / native backends
       └─────────────────────┘
```

Three subsystems (A, B, C) map directly to the three principles. Everything else is plumbing.

---

## 3. Repository Layout — The Overlay Architecture

This is the answer to *"how does self-modification not conflict with my upstream pushes?"* The repo is split into three physical regions with different mutability rules:

```
noman/
├── core/                    ← IMMUTABLE. Agent cannot write here.
│   ├── orchestrator/        ← ReAct loop, budget, tool dispatch
│   ├── context/             ← Tree-sitter, PageRank, JIT loader
│   ├── memory/              ← SQLite substrate, tiered memory API
│   ├── selfimprove/         ← Trace critic, meta-agent, heuristic gen
│   ├── adapters/            ← Model backends
│   └── prompts/             ← Baseline system prompts (read-only)
│
├── overlay/                 ← AGENT-WRITABLE. Not tracked upstream.
│   ├── prompts/             ← Prompt patches that override core/prompts
│   ├── skills/              ← Auto-generated SKILL.md files
│   ├── heuristics/          ← "Rules of thumb" YAML
│   └── tools/               ← Agent-authored tool definitions
│
├── user/                    ← USER-WRITABLE. Tracked in user's fork.
│   ├── plugins/             ← User-added features
│   ├── config.toml          ← User preferences
│   └── prompts/             ← User prompt customizations
│
└── .noman/                  ← RUNTIME. Never tracked.
    ├── memory.db            ← SQLite (see §5)
    ├── traces/              ← Execution traces
    └── cache/
```

**Conflict resolution is structural, not semantic.** Upstream only ever touches `core/`. The agent only ever writes to `overlay/`. You only ever write to `user/`. Three disjoint trees, zero merge conflicts by construction.

**Gitignore strategy:**

- Root `.gitignore` lists `overlay/` and `.noman/` — so upstream clones never carry agent state.
- Overlay has its own `overlay/.git` (separate repo) so users can optionally version their agent's evolution independently.
- `user/` is tracked only in the user's fork.

**Precedence order at load time** (later overrides earlier): `core/prompts → user/prompts → overlay/prompts`. The agent's own learnings win, but the user can pin something by adding it to `user/` with a priority flag.

---

## 4. Subsystem A — Context Management

Goal: give a 7B–14B local model the *illusion* of whole-repo awareness using <8K tokens.

### A.1 Tree-sitter Skeleton Map

Never parse files eagerly. On repo init, walk the tree and extract only:

- Function and method signatures (name, params, return type if typed)
- Class headers (name, bases, decorators)
- Top-level constants and type aliases
- Docstrings (first line only)

Store as a compact newline-delimited format — roughly 1 line per symbol, ~15 tokens. A 50k-LOC repo compresses to ~4–8k tokens of skeleton, which fits in-context as a durable map.

```
src/auth/session.py:
  class SessionManager(BaseStore):
  def create_session(user_id: int, ttl: int=3600) -> Session
  def revoke(session_id: str) -> bool
```

Re-parse happens incrementally on file save via `watchdog`, not on every turn.

### A.2 PageRank Symbol Ranking

Not every symbol deserves equal attention. Build a directed call/import graph from the tree-sitter parse and run PageRank on it. The top-N symbols (by rank) are surfaced first; low-rank symbols are hidden behind a `search_symbols` tool.

This matters more than it sounds. In a typical repo, ~10% of symbols receive ~80% of references. Feeding the model a rank-ordered skeleton means the *central* abstractions are always visible, and peripheral utility functions only surface when the agent searches for them.

### A.3 Just-in-Time Loading

The agent never reads a full file unless it is genuinely editing every line. Standard tools:

- `read_lines(path, start, end)` — grep/tail-style line ranges
- `read_symbol(path, symbol_name)` — tree-sitter-powered, fetches just the function/class body
- `search(query, scope)` — ripgrep across skeleton first, content second

### A.4 Token Budget Enforcement

The orchestrator tracks a running token count per turn and enforces hard caps:

| Context slot       | Default budget | Behavior at cap               |
| ------------------ | -------------- | ----------------------------- |
| System + skeleton  | 3000           | Truncate low-rank symbols     |
| Conversation recap | 1500           | Summarize oldest 50%          |
| Tool results       | 2000           | Reject new calls, ask to narrow |
| Working reasoning  | 1500           | Force a checkpoint/commit     |

When any slot saturates, the orchestrator triggers the **compaction** routine: serialize current state into a one-paragraph recap, push the raw trace to episodic memory, and start the next turn fresh.

---

## 5. Subsystem B — Hierarchical Persistent Memory (Local First)

### B.1 Substrate

Single SQLite database at `.noman/memory.db` with two extensions:

- **`sqlite-vec`** — vector search over embeddings
- **FTS5** — keyword/BM25 full-text search

Why SQLite: one file, no daemon, git-diffable if needed, sub-10ms query latency, and embedding dimensions can be whatever the local embedder emits. A user can literally `scp` their brain to another machine.

Embedding model: default to a small local one (e.g., `nomic-embed-text` via Ollama or `all-MiniLM-L6-v2` via `fastembed`). Configurable.

### B.2 Tiered Memory

Memory is split by *what kind of information it is*, which governs TTL, retrieval strategy, and prompt slot.

**Episodic** — recent interaction traces, command outputs, error logs.
- TTL: 7 days, then summarized and demoted
- Retrieval: time-decayed vector search, triggered when user's query resembles a past failure
- Use case: "last time I ran migrations it failed because of X"

**Semantic** — distilled project-wide and architectural facts.
- TTL: indefinite, invalidated by Fact Extraction (below)
- Retrieval: structured query first (e.g., `facts WHERE scope='project' AND key='style_convention'`), vector fallback
- Example entries: `{scope: project, key: style, value: "snake_case for functions"}`, `{scope: project, key: test_framework, value: "pytest with fixtures in conftest.py"}`

**Procedural (Skill Library)** — successful task trajectories promoted into reusable skills.
- When a task completes successfully and the critic rates it well, the meta-agent distills the trace into an `overlay/skills/<name>.md` file.
- Each skill has a trigger description (when to use it) and a body (how it's done).
- On future turns, the agent reads skill descriptions first and only loads full bodies if a match.
- This is structurally identical to how Anthropic's skill system works, and it's the right pattern.

### B.3 Fact Extraction (not raw log dumps)

The footgun this avoids: naive memory systems accumulate every log line forever, poisoning retrieval with noise.

Instead, a background process runs after each session with a dedicated prompt:

```
Given this session trace, emit a list of atomic facts as:
  ADD    {scope, key, value}    — new knowledge
  UPDATE {scope, key, new_value} — refinement
  DELETE {scope, key}           — invalidated
Only emit high-confidence, project-durable facts.
```

Examples of what gets extracted:
- `ADD {scope: file, key: "src/api.py::auth_middleware", value: "requires X-User-Id header"}`
- `UPDATE {scope: project, key: "python_version", new_value: "3.12"}`
- `DELETE {scope: file, key: "src/legacy.py::*"}` (file was deleted)

**Conflict rule:** if a file moves or an API changes, the agent *updates its belief* rather than keeping conflicting records. Stale facts are the #1 cause of hallucinated context.

### B.4 Memory Access Tools

Exposed to the agent as first-class tools:

- `remember(scope, key, value)` — write a semantic fact
- `recall(query, tier='auto', k=5)` — read
- `forget(scope, key)` — explicit invalidation
- `skill_list()` / `skill_load(name)` — procedural tier

The `auto` tier is a routed search: if query looks like a factual lookup, hit semantic first; if it's experiential ("have I done X before"), hit episodic; for "how do I do X" patterns, hit procedural.

---

## 6. Subsystem C — Self-Improvement Architecture

This is where the agent earns the "No Man" name — no human in the loop for its own upkeep.

### C.1 Trace Intelligence Layer

Every session produces a **trace**: ordered list of (thought, tool call, observation, reasoning step) tuples. Traces are stored in `.noman/traces/`.

After the session, an internal **Critic agent** scores the trace on several axes:

| Axis          | Rubric                                                    |
| ------------- | --------------------------------------------------------- |
| Task success  | Did the user confirm completion / did tests pass?         |
| Token efficiency | Tokens used vs. minimum plausible                      |
| Tool economy  | Redundant or contradictory tool calls?                    |
| Dead ends     | Number of backtracks                                      |
| Hallucinations | Claims contradicted by later tool output                |

Scores are normalized to [0, 1] and written back into the trace record. Low scores are what drive the next layer.

### C.2 Recursive Prompt Optimization

Periodically (configurable: every N sessions or when aggregate score drops), a **Meta-agent** runs:

1. Load the N lowest-scoring recent traces.
2. Cluster by failure mode (prompt ambiguity, tool misuse, context overflow, etc.).
3. For each cluster, diagnose the root cause — is it a prompt issue or a tool-definition issue?
4. Propose a patch:
   - For prompt issues → write a diff against the relevant `core/prompts/*.md` into `overlay/prompts/`.
   - For tool issues → write a wrapper or new signature into `overlay/tools/`.
5. A/B test: next K sessions alternate old vs. new. If new wins by margin, promote; else roll back.

The rollback mechanism is critical. Self-improvement that can't undo itself is self-destruction. Every promoted change is a discrete file in `overlay/` with a `created_at` and `parent_hash` — trivially revertable with `noman rollback <n>`.

### C.3 Heuristic Extraction

Distinct from full prompt rewrites, heuristics are small, localized "rules of thumb" extracted from reflective analysis of task outcomes.

After a task where the critic noticed a pattern (e.g., "agent defined a type alias without checking the existing `types.py`, which already had it"), the reflector emits:

```yaml
# overlay/heuristics/type_aliases.yaml
id: heu_042
trigger: "about to define a type alias or typedef"
rule: "Always check types.py and any existing __types.py modules for duplicates first"
source_trace: traces/2026-04-22T14:30.jsonl
confidence: 0.8
```

Heuristics are injected into the prompt at relevant moments only — not globally. The trigger is vector-matched against the agent's current thought before being surfaced. This keeps them cheap.

### C.4 Safety Rails on Self-Modification

Because the agent can rewrite its own prompts and generate tools, three guardrails are mandatory:

1. **Sandboxed codegen** — agent-authored tools run in a subprocess with restricted filesystem access (no writes outside `overlay/` and the user's working repo).
2. **Signed core** — on startup, hash `core/` against a manifest. If the hash differs, refuse to run agent-generated modifications until user acknowledges (protects against supply-chain tampering).
3. **Human-approval threshold** — for structural changes (new tool, prompt replacement >20% diff), queue for user approval in `overlay/pending/` rather than auto-promoting. Surface with `noman review`.

---

## 7. The Conflict-Free Update Flow

The end-to-end story for *"user pushes upstream, agent keeps its learnings"*:

```
┌─────────────┐   git pull upstream main   ┌──────────────┐
│ core/       │ ─────────────────────────▶ │ core/        │ (clean merge, always)
└─────────────┘                            └──────────────┘
┌─────────────┐                            ┌──────────────┐
│ user/       │ ─── user's own commits ──▶ │ user/        │ (user's normal git flow)
└─────────────┘                            └──────────────┘
┌─────────────┐                            ┌──────────────┐
│ overlay/    │ ─── untouched by pull ───▶ │ overlay/     │ (agent's private state)
└─────────────┘                            └──────────────┘
```

Because the three trees never overlap, `git pull` on upstream is always a fast-forward on `core/`. The agent's learned behaviors, prompts, skills, and heuristics all live in `overlay/`, which upstream never touches.

**Edge case: upstream changes break an overlay patch.** E.g., `core/prompts/planner.md` is rewritten, and the overlay had a patch against the old version. Solution: overlay patches are anchored by *semantic section* (YAML front-matter keys), not line numbers. On upstream update, `noman doctor` detects broken anchors and either re-applies semantically or quarantines the patch to `overlay/quarantine/` with a diagnostic. Agent re-derives from scratch on next trigger. Nothing is silently corrupted.

---

## 8. Tool Bus

Tools are the agent's hands. Spec:

```python
@tool(name="read_symbol", cost_estimate=200)
def read_symbol(path: str, symbol: str) -> str:
    """Return the source of a named function/class using tree-sitter."""
    ...
```

Every tool declares a `cost_estimate` (expected tokens of output). The orchestrator uses these for pre-call budget checks.

**Core tools (minimum viable set):**

- Context: `skeleton`, `search_symbols`, `read_symbol`, `read_lines`, `grep`
- Filesystem: `list_dir`, `write_file`, `edit_file` (diff-based), `delete_file`
- Execution: `run_shell` (sandboxed), `run_tests`, `lint`
- Memory: `remember`, `recall`, `forget`, `skill_load`
- Meta: `reflect`, `propose_heuristic` (used by self-improvement layer)

Users and the agent can both add tools. User tools live in `user/plugins/tools/`; agent-authored tools live in `overlay/tools/`. Both are auto-discovered at startup via a simple registry pattern.

---

## 9. Model Adapter

The single contract every backend honors is the **OpenAI Chat Completions API** (`/v1/chat/completions` with tool-calling). This is the industry's de facto lingua franca — Ollama, llama.cpp, vLLM, LM Studio, LocalAI, Together, Groq, Anthropic (via proxy or the `openai` SDK compatibility mode), DeepSeek, Gemini, Mistral, and OpenAI itself all expose or can be wrapped behind this shape. By centering on it, adding a new provider becomes a config-file change, not code.

### 9.1 Provider Configuration

A backend is just a named `(base_url, api_key, model_name)` triple. Zero-code registration:

```toml
# user/config.toml

[model.default]
provider = "local_ollama"

[providers.local_ollama]
base_url = "http://localhost:11434/v1"
api_key = "ollama"                      # any non-empty string
model   = "qwen2.5-coder:7b"
context_window = 32768

[providers.groq_fast]
base_url = "https://api.groq.com/openai/v1"
api_key  = "${GROQ_API_KEY}"
model    = "llama-3.3-70b-versatile"
context_window = 131072

[providers.claude_cloud]
base_url = "https://api.anthropic.com/v1"    # via Anthropic's OpenAI-compat endpoint
api_key  = "${ANTHROPIC_API_KEY}"
model    = "claude-sonnet-4-5"
context_window = 200000

[providers.openai_gpt]
base_url = "https://api.openai.com/v1"
api_key  = "${OPENAI_API_KEY}"
model    = "gpt-4.1"
context_window = 1000000
```

A user can switch providers with `noman --provider groq_fast "do X"` or pin a default. No recompile, no plugin install.

### 9.2 What the Adapter Actually Handles

Being "OpenAI-compatible" is a useful floor, not a ceiling. The adapter absorbs the messy reality:

- **Tool-calling dialect drift.** Some providers return clean `tool_calls` arrays; others (especially smaller local models) emit tool calls as inline JSON in content, or in XML, or in a custom format. The adapter has per-provider parsers that normalize everything to the OpenAI schema before it reaches the orchestrator.
- **Context window introspection.** The declared `context_window` in config is a ceiling; some backends expose the real number via a `/models` endpoint. The adapter prefers the reported value and warns on mismatch.
- **Streaming.** All providers stream, but chunk shapes differ (SSE framing, delta fields). Normalized to a single async iterator of typed events.
- **Embeddings.** Same pattern: a separate `[embeddings]` config block points to any OpenAI-compatible `/v1/embeddings` endpoint (Ollama, OpenAI, Voyage, a local sentence-transformers server, etc.). The memory subsystem is agnostic to which.
- **Quirk flags.** Per-provider boolean flags for known footguns (`no_system_role`, `needs_tool_examples`, `strips_thinking`, `max_tool_calls_per_turn`). These drive prompt template selection without forking code paths.

### 9.3 Role-Based Routing

Different stages of a NoMan turn have wildly different needs. You don't need GPT-4.1 to decide which file to open. The adapter exposes four logical roles that can map to different providers:

| Role       | What it does                                    | Typical choice                          |
| ---------- | ----------------------------------------------- | --------------------------------------- |
| `planner`  | Decomposes the task, picks tools                | Strong reasoning model                  |
| `executor` | Grunt tool-calling, narrow reads/edits          | Cheap/fast (local 7B, Groq, Haiku)      |
| `critic`   | Scores traces post-hoc (§6.1)                   | Medium, separate from executor to reduce bias |
| `embedder` | Produces vectors for memory retrieval           | Any embedding endpoint                  |

```toml
[model]
planner  = "claude_cloud"
executor = "local_ollama"
critic   = "groq_fast"
embedder = "local_embed"
```

All four can point to the same provider for simple setups. This is the mechanism that lets NoMan stay cheap and local by default while seamlessly escalating to frontier models for hard steps. It's also why the token-frugal context management in §4 pays off regardless of backend: the planner's prompt is smaller, so even expensive models stay cheap.

### 9.4 Capability Negotiation

At startup, the adapter probes each configured provider:

1. Hits the `/models` endpoint (if present) to confirm the model exists.
2. Sends a one-turn tool-calling probe to check the dialect.
3. Caches the result in `.noman/cache/capabilities.json` with a TTL.

Probe failure doesn't kill startup — the provider is marked degraded and the user sees a warning in `noman doctor`. This means you can declare five providers in config and only have two reachable, and NoMan picks up the rest when they come online.

---

## 10. CLI Surface

```
noman init              # scaffold .noman/, build initial skeleton
noman                   # interactive REPL
noman "do X"            # one-shot
noman review            # review pending agent self-modifications
noman rollback [N]      # revert the last N overlay changes
noman doctor            # health check: DB integrity, broken patches, etc.
noman memory <subcmd>   # ls / search / export / import
noman skill <subcmd>    # ls / show / disable
noman stats             # token usage, success rates, memory size
```

Config lives at `user/config.toml`:

```toml
[model]
default  = "local_ollama"    # see §9 for full provider config
# optional role overrides:
# planner  = "claude_cloud"
# executor = "local_ollama"
# critic   = "groq_fast"

[budget]
system_skeleton    = 3000
conversation_recap = 1500
tool_results       = 2000

[self_improvement]
enabled = true
critic_role = "critic"            # which model role runs the critic
auto_promote_threshold = 0.15     # min score delta to auto-promote
require_approval_for = ["new_tool", "prompt_replace"]
```

---

## 11. Implementation Roadmap

| Phase | Scope                                                                 | Exit criterion                                         |
| ----- | --------------------------------------------------------------------- | ------------------------------------------------------ |
| 0     | CLI skeleton, OpenAI-compat adapter, ReAct loop, basic tools (read/write/shell) | `noman "write hello world"` works against any OpenAI-compat endpoint |
| 1     | Tree-sitter skeleton + PageRank + JIT loading                         | 50k-LOC repo stays under 8k tokens of context          |
| 2     | SQLite memory, tiered retrieval, fact extraction                      | Agent correctly recalls a fact across sessions         |
| 3     | Overlay architecture, load-order precedence, `noman doctor`           | Upstream pull + agent edits = zero conflicts           |
| 4     | Capability negotiation + role routing (planner/executor/critic split) | Same task runs locally or mixed local+cloud with no code change |
| 5     | Trace critic, meta-agent, prompt optimization, rollback               | Demonstrate a prompt self-patch that improves score    |
| 6     | Heuristic extraction + skill library promotion                        | Agent produces a reusable skill from a successful task |
| 7     | Provider-specific quirk flags, polish, community skill sharing        | Ship v1.0                                              |

---

## 12. Open Questions

These are unresolved and should be decided before Phase 2:

1. **Embedding model lock-in.** If a user swaps embedding models mid-life, all stored vectors become meaningless. Options: store embedding model version per row and re-embed on mismatch, or forbid swaps post-init. Leaning toward the former.
2. **Critic bias.** The critic is itself an LLM — can it reliably score traces produced by an equally-capable LLM? May need human-labeled ground truth for bootstrapping, or a deterministic component (tests passing / linter clean) weighted into the score.
3. **Overlay portability.** Should `overlay/` be shareable across users ("download community skills")? Great for flywheel, risky for prompt injection. Probably yes with signing.
4. **Windows support.** Tree-sitter and sqlite-vec both have Windows wheels now, but `fork()`-style subprocess sandboxing doesn't. WSL-only for v0.1, native Windows post-v1.

---

## 13. Summary

NoMan is four ideas in a trench coat:

1. **Don't waste tokens** — skeleton + PageRank + JIT loading makes a small-context model feel like it has a 200k window. The same discipline makes a large-context model cheap.
2. **Remember, don't re-learn** — SQLite + tiered memory + fact extraction means the agent gets sharper over time without retraining.
3. **Improve without colliding** — overlay architecture makes self-modification structurally disjoint from upstream code, so `git pull` is always clean.
4. **Speak one dialect, route many models** — OpenAI-compatible is the universal interface. Role-based routing (planner/executor/critic) means you pay frontier prices only where it matters.

The whole design is defensive about three failure modes that kill most agent projects: context blowup, state corruption on update, and vendor lock-in. Getting those three right buys everything else.
