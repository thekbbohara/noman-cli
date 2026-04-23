## 2. Self-Improvement Architecture

### 2.1 Purpose

The Self-Improvement system enables NoMan to autonomously optimize its own prompts, heuristics, and skills based on performance traces. It consists of two agents: the Trace Critic (scores executions) and the Meta-Agent (proposes improvements).

### 2.2 Key Components

| Component | Responsibility | Trigger |
|-----------|---------------|---------|
| **Trace Collector** | Capture full execution traces (prompts, tool calls, results) | Every session |
| **Trace Critic** | Score traces on success, efficiency, correctness | Post-session |
| **Meta-Agent** | Analyze low-scoring traces, propose patches | Periodic or on-demand |
| **Patch Validator** | Test proposed changes before promotion | Before overlay update |
| **Rollback Manager** | Revert bad self-modifications | On user request or auto-detect |

### 2.3 Trace Schema

```json
{
  "trace_id": "uuid4",
  "session_id": "uuid4",
  "timestamp": "ISO8601",
  "task": "User's original prompt",
  "turns": [
    {
      "turn_id": 1,
      "role": "assistant",
      "prompt_tokens": 3421,
      "completion_tokens": 156,
      "thought": "I need to read the auth module first...",
      "tool_call": {
        "name": "read_lines",
        "args": {"path": "src/auth.py", "start": 1, "end": 50}
      },
      "tool_result": "...",
      "duration_ms": 2341
    }
  ],
  "outcome": {
    "success": true,
    "user_confirmed": true,
    "tests_passed": true,
    "total_tokens": 12453,
    "total_turns": 5,
    "duration_sec": 23.4
  },
  "context_snapshot": {
    "skeleton_size": 2341,
    "symbols_loaded": ["authenticate", "validate_token"],
    "memories_retrieved": 3
  }
}
```

### 2.4 Critic Scoring System

```python
# core/selfimprove/critic.py

from dataclasses import dataclass
from enum import Enum

class ScoreCategory(Enum):
    SUCCESS = "success"          # Did it work?
    EFFICIENCY = "efficiency"    # Token/time efficiency
    CORRECTNESS = "correctness"  # Code quality, no bugs
    CLARITY = "clarity"          # Clear explanations

@dataclass
class TraceScore:
    trace_id: str
    overall: float               # Weighted average 0.0-1.0
    categories: dict             # {category: score}
    feedback: str                # Natural language explanation
    suggested_improvements: list # ["Reduce tool calls", "Better prompt structure"]

class TraceCritic:
    """Scores execution traces using LLM + deterministic metrics."""
    
    def __init__(self, model_adapter, config: dict):
        self.model = model_adapter
        self.config = config
        self.weights = config.get("score_weights", {
            "success": 0.4,
            "efficiency": 0.25,
            "correctness": 0.25,
            "clarity": 0.1
        })
    
    async def score_trace(self, trace: dict) -> TraceScore:
        # Deterministic scores
        success_score = 1.0 if trace["outcome"]["success"] else 0.0
        efficiency_score = self._calc_efficiency_score(trace)
        
        # LLM-based scores (correctness, clarity)
        llm_scores = await self._llm_evaluate(trace)
        
        # Weighted average
        overall = (
            success_score * self.weights["success"] +
            efficiency_score * self.weights["efficiency"] +
            llm_scores["correctness"] * self.weights["correctness"] +
            llm_scores["clarity"] * self.weights["clarity"]
        )
        
        return TraceScore(
            trace_id=trace["trace_id"],
            overall=overall,
            categories={
                "success": success_score,
                "efficiency": efficiency_score,
                "correctness": llm_scores["correctness"],
                "clarity": llm_scores["clarity"]
            },
            feedback=llm_scores["feedback"],
            suggested_improvements=llm_scores["suggestions"]
        )
    
    def _calc_efficiency_score(self, trace: dict) -> float:
        # Compare against baseline for similar tasks
        # Return 1.0 for excellent, 0.0 for terrible
        ...
```

### 2.5 Meta-Agent Prompt Template

```markdown
# Meta-Agent: Self-Improvement Analysis

You are analyzing low-scoring execution traces to propose improvements.

## Current System State
- Active prompts: {current_prompts}
- Active heuristics: {active_heuristics}
- Available skills: {available_skills}

## Trace Under Analysis
{trace_json}

## Critic Scores
- Overall: {overall_score}
- Success: {success_score}
- Efficiency: {efficiency_score}
- Correctness: {correctness_score}
- Clarity: {clarity_score}

## Critic Feedback
{critic_feedback}

## Your Task

1. **Root Cause Analysis**: Why did this trace score poorly?
   - Was the prompt unclear?
   - Were wrong tools selected?
   - Was context missing?
   - Was memory retrieval ineffective?

2. **Propose Specific Changes**: Generate ONE of:
   - A prompt patch (modify existing prompt in core/prompts/)
   - A new heuristic (add to overlay/heuristics/)
   - A skill extraction (distill successful pattern)
   - A tool improvement suggestion

3. **Justify Impact**: Explain why this change will improve future scores.

## Output Format

```json
{
  "change_type": "prompt_patch|heuristic|skill_extraction",
  "target_file": "path/to/file",
  "patch": {
    "before": "...",
    "after": "..."
  },
  "justification": "...",
  "expected_score_delta": 0.15
}
```
```

### 2.6 Patch Validation Pipeline

```
1. Meta-Agent proposes patch
   ↓
2. Patch Validator receives proposal
   ↓
3. Syntactic validation
   ├─► Valid JSON/YAML?
   ├─► Valid Python (if code)?
   └─► Follows schema?
   ↓
4. Semantic validation
   ├─► Doesn't break existing tools?
   ├─► Doesn't remove critical prompts?
   └─► Passes unit tests?
   ↓
5. Shadow testing (optional for major changes)
   ├─► Run historical traces with old vs new
   └─► Compare scores
   ↓
6. Decision
   ├─► Auto-promote (if score delta > threshold)
   ├─► Queue for review (if borderline)
   └─► Reject (if regression)
   ↓
7. Apply to overlay/ (with rollback point)
```

### 2.7 Implementation Tasks

| Task | File(s) | Priority | Dependencies |
|------|---------|----------|--------------|
| Trace collector | `core/selfimprove/traces.py` | P0 | Orchestrator |
| Trace storage | `.noman/traces/` schema | P0 | None |
| Critic agent | `core/selfimprove/critic.py` | P0 | Model adapter |
| Meta-agent | `core/selfimprove/meta_agent.py` | P0 | Critic |
| Patch validator | `core/selfimprove/validator.py` | P0 | Tools, Tests |
| Rollback manager | `core/selfimprove/rollback.py` | P1 | Overlay arch |
| Review CLI | `noman review` command | P1 | CLI surface |
| Unit tests | `tests/test_self_improve.py` | P1 | All components |

---

