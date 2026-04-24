# REPL TUI Design — NoMan CLI

**Version:** 1.0
**Status:** Approved for Implementation
**Date:** 2026-04-24

---

## 1. Overview

Interactive REPL with a full TUI powered by `textual`. Replaces the stub message currently shown when running `noman` with no arguments.

---

## 2. User Experience

### 2.1 Idle State
- Empty prompt waiting for input (no menu by default)
- User types a task and presses Enter
- Single empty output area (hidden until needed)

### 2.2 Running State
- **Header:** Turn count, tokens used, status (thinking → executing → done)
- **Output area:** Scrollable log of LLM responses and tool calls
- Prompt at bottom accepts new input after completion

### 2.3 Idle → Running Transition
1. User types task and presses Enter
2. Header appears with status "initializing"
3. Output area populates as task runs

---

## 3. Technical

### 3.1 Framework
- `textual` >= 0.50

### 3.2 Layout

```
┌─────────────────────────────────────┐
│ NoMan v0.0.01                    │  ← Header (dark bg, light text)
│ Turn 2 | 4.2K tokens | running   │
├─────────────────────────────────────┤
│                                     │
│ [scrollable output area]               │
│ - LLM responses                    │
│ - tool calls                     │
│ - observations                  │
│                                     │
├─────────────────────────────────────┤
│ > _                            │  ← Input (prompt)
└─────────────────────────────────────┘
```

### 3.3 Components
- `Header`: Static text + dynamic status fields
- `OutputLog`: ScrollView with auto-scroll to bottom
- `Input`: TextInput bound to Enter key

### 3.4 State Machine
| State | Header | Output | Input |
|-------|-------|--------|-------|
| idle | "NoMan vX" | hidden | visible |
| initializing | status | reveals | hidden |
| running | status | live | hidden |
| done | "complete" | visible | visible |

---

## 4. Integration with Existing Code

- Reuse orchestrator creation from `cli/main.py:_create_orchestrator()`
- Reuse `Orchestrator.run()` for task execution
- Handle KeyboardInterrupt to stop task cleanly

---

## 5. Out of Scope

- Command palette (can add later)
- Context preview panel
- Tabs or split views

---

## 6. Acceptance Criteria

1. `noman` (no args) opens TUI, shows prompt
2. Typing a task and pressing Enter runs it
3. Header shows turn count and token usage
4. Output scrolls as task runs
5. After completion, prompt returns for next task
6. Ctrl+C stops running task gracefully