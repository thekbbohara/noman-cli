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

| Task | File(s) | Priority | Dependencies | Change |
|------|---------|----------|--------------|--------|
| Trace collector | `core/selfimprove/traces.py` | P0 | Orchestrator | — |
| Trace storage | `.noman/traces/` schema | P0 | None | — |
| Critic agent | `core/selfimprove/critic.py` | P0 | Model adapter | — |
| Meta-agent | `core/selfimprove/meta_agent.py` | P0 | Critic | — |
| Patch validator | `core/selfimprove/validator.py` | P0 | Tools, Tests | — |
| **Safety guardrails** | `core/selfimprove/safety_guardrails.py` | **P0** | None | ↑ NEW - Critical security fix |
| Rollback manager | `core/selfimprove/rollback.py` | **P0** | Overlay arch | ↑ P1→P0 (must exist before self-mod) |
| Review CLI | `noman review` command | P1 | CLI surface | — |
| Unit tests | `tests/test_self_improve.py` | P1 | All components | — |
| **Adversarial tests** | `tests/test_self_improve_attacks.py` | **P0** | Safety guardrails | ↑ NEW - Test constraint bypass attempts |

### 2.8 Safety Guardrails (NEW - CRITICAL SECURITY FIX)

**Problem:** Original design allowed Meta-Agent to potentially modify its own constraints, creating a runaway self-improvement risk.

**Solution:** Immutable safety guardrails that CANNOT be modified by the Meta-Agent.

```python
# core/selfimprove/safety_guardrails.py

from dataclasses import dataclass, field
from typing import Set, FrozenSet
from enum import Enum

class ConstraintType(Enum):
    IMMUTABLE = "immutable"           # Can NEVER be changed
    USER_APPROVAL_REQUIRED = "user_approval"  # Requires explicit user OK
    THRESHOLD_PROTECTED = "threshold_protected"  # Requires high-score threshold

@dataclass(frozen=True)  # frozen=True makes it immutable
class SafetyConstraint:
    """A safety constraint that protects against harmful self-modifications."""
    id: str
    description: str
    constraint_type: ConstraintType
    protected_patterns: FrozenSet[str]  # Patterns that trigger protection
    can_modify_itself: bool = False     # Self-referential modification blocked
    
# CRITICAL: These constraints are defined in CORE code, NOT in overlay/
# They CANNOT be modified by the Meta-Agent
IMMUTABLE_CONSTRAINTS: FrozenSet[SafetyConstraint] = frozenset([
    SafetyConstraint(
        id="no_sandbox_disable",
        description="Cannot disable filesystem or network sandboxing",
        constraint_type=ConstraintType.IMMUTABLE,
        protected_patterns=frozenset([
            "FilesystemSandbox",
            "NetworkSandbox", 
            "validate_path",
            "is_host_allowed",
            "security/fs_sandbox",
            "security/network_sandbox",
        ]),
    ),
    SafetyConstraint(
        id="no_constraint_removal",
        description="Cannot remove or weaken safety constraints",
        constraint_type=ConstraintType.IMMUTABLE,
        protected_patterns=frozenset([
            "safety_guardrails",
            "IMMUTABLE_CONSTRAINTS",
            "ConstraintType",
            "SafetyConstraint",
        ]),
        can_modify_itself=False,  # THIS prevents self-modification
    ),
    SafetyConstraint(
        id="no_network_exfil",
        description="Cannot enable unrestricted network access",
        constraint_type=ConstraintType.IMMUTABLE,
        protected_patterns=frozenset([
            "deny_all_by_default=False",
            "allowed_hosts=set()",
            "block_outbound_data=False",
        ]),
    ),
    SafetyConstraint(
        id="no_arbitrary_code",
        description="Cannot enable arbitrary code execution",
        constraint_type=ConstraintType.IMMUTABLE,
        protected_patterns=frozenset([
            "exec(",
            "eval(",
            "__import__",
            "compile(",
            "unsafe_load_tool",
        ]),
    ),
    SafetyConstraint(
        id="max_patch_size",
        description="Patches cannot exceed size limits without approval",
        constraint_type=ConstraintType.THRESHOLD_PROTECTED,
        protected_patterns=frozenset(),
    ),
])

@dataclass
class ModificationRequest:
    """A proposed modification from the Meta-Agent."""
    change_type: str
    target_file: str
    patch: dict
    justification: str
    expected_score_delta: float

class SafetyGuardrailEnforcer:
    """Enforces safety constraints on all self-modification proposals."""
    
    def __init__(self):
        self.constraints = IMMUTABLE_CONSTRAINTS
        self.max_patch_lines = 50  # Hard limit without user approval
        self.high_confidence_threshold = 0.85
    
    def validate_modification(self, request: ModificationRequest) -> tuple[bool, str]:
        """
        Validate a proposed modification against all safety constraints.
        
        Returns:
            (is_allowed, rejection_reason)
        """
        # Check 1: Is Meta-Agent trying to modify guardrails itself?
        if self._is_self_modification_attempt(request):
            return False, (
                "CRITICAL VIOLATION: Cannot modify safety_guardrails.py itself. "
                "This is an immutable core security module."
            )
        
        # Check 2: Does patch contain forbidden patterns?
        violation = self._check_forbidden_patterns(request)
        if violation:
            return False, violation
        
        # Check 3: Is this trying to disable security features?
        if self._disables_security(request):
            return False, (
                "SECURITY VIOLATION: Cannot disable or weaken security features. "
                f"Sandboxing, network isolation, and integrity checks are mandatory."
            )
        
        # Check 4: Patch size limits
        if not self._within_size_limits(request):
            return False, (
                f"Patch exceeds maximum size ({self.max_patch_lines} lines). "
                f"Large changes require user review and explicit approval."
            )
        
        # Check 5: Protected files require user approval
        if self._touches_protected_files(request):
            return "requires_user_approval", (
                f"Modification touches protected files {request.target_file}. "
                f"User approval required for core system changes."
            )
        
        return True, "OK"
    
    def _is_self_modification_attempt(self, request: ModificationRequest) -> bool:
        """Detect if Meta-Agent is trying to modify its own constraints."""
        target = request.target_file.lower()
        
        # Direct attempt to modify guardrails
        if "safety_guardrails" in target:
            return True
        
        # Indirect attempt via patch content
        patch_content = str(request.patch).lower()
        for constraint in self.constraints:
            if not constraint.can_modify_itself:
                for pattern in constraint.protected_patterns:
                    if pattern.lower() in patch_content:
                        return True
        
        return False
    
    def _check_forbidden_patterns(self, request: ModificationRequest) -> str:
        """Check if patch contains forbidden patterns."""
        patch_str = str(request.patch)
        
        for constraint in self.constraints:
            if constraint.constraint_type == ConstraintType.IMMUTABLE:
                for pattern in constraint.protected_patterns:
                    if pattern in patch_str:
                        return (
                            f"VIOLATION: Patch contains forbidden pattern '{pattern}'. "
                            f"This would violate constraint '{constraint.id}': {constraint.description}"
                        )
        
        return ""
    
    def _disables_security(self, request: ModificationRequest) -> bool:
        """Detect attempts to disable security features."""
        patch_str = str(request.patch).lower()
        
        # Common patterns that would disable security
        dangerous_patterns = [
            "sandbox = none",
            "security_check = false",
            "validate = false",
            "allow_all = true",
            "disable_protection",
            "bypass_security",
        ]
        
        return any(pattern in patch_str for pattern in dangerous_patterns)
    
    def _within_size_limits(self, request: ModificationRequest) -> bool:
        """Check if patch is within size limits."""
        patch_content = str(request.patch)
        line_count = len(patch_content.splitlines())
        return line_count <= self.max_patch_lines
    
    def _touches_protected_files(self, request: ModificationRequest) -> bool:
        """Check if modification touches protected files."""
        protected_prefixes = [
            "core/security/",
            "core/selfimprove/safety",
            "core/tools/tool_bus",
            "core/adapters/token_validator",
        ]
        
        return any(
            request.target_file.startswith(prefix)
            for prefix in protected_prefixes
        )


# Usage in Meta-Agent
class MetaAgent:
    """Meta-Agent with enforced safety guardrails."""
    
    def __init__(self, ...):
        self.guardrails = SafetyGuardrailEnforcer()
    
    async def propose_improvement(self, trace, critic_feedback) -> dict:
        # Generate improvement proposal
        proposal = await self._analyze_and_propose(trace, critic_feedback)
        
        # CRITICAL: Validate against safety guardrails BEFORE returning
        mod_request = ModificationRequest(
            change_type=proposal["change_type"],
            target_file=proposal["target_file"],
            patch=proposal["patch"],
            justification=proposal["justification"],
            expected_score_delta=proposal["expected_score_delta"]
        )
        
        is_valid, reason = self.guardrails.validate_modification(mod_request)
        
        if not is_valid:
            # Log attempted violation
            logger.warning(f"Safety violation blocked: {reason}")
            raise SafetyViolationError(f"Proposed modification blocked: {reason}")
        
        if is_valid == "requires_user_approval":
            proposal["requires_user_approval"] = True
            proposal["approval_reason"] = reason
        
        return proposal


class SafetyViolationError(Exception):
    """Raised when a self-modification violates safety constraints."""
    pass
```

**Key Security Properties:**

1. **Self-Protecting**: `safety_guardrails.py` cannot modify itself (`can_modify_itself=False`)
2. **Immutable Constraints**: Core constraints are `FrozenSet` - cannot be changed at runtime
3. **Pattern Detection**: Blocks attempts to disable sandboxing, network isolation, or security checks
4. **Size Limits**: Prevents large, complex changes without review
5. **Protected Files**: Core security modules require explicit user approval
6. **Audit Logging**: All violation attempts are logged for review

---

