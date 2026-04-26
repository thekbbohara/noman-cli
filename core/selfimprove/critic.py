"""TraceCritic — weighted signal scoring of execution traces.

Hybrid approach combining:
- Friction signals (Noman-style): user corrections, backtracking, error overcome
- Value signals: complexity, novelty, user satisfaction
- Rate limiting to prevent junk skill spam

Scoring is a weighted sum of independent signals, each contributing 0.0-1.0.
Threshold >= 0.7 triggers a skill draft proposal.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any
from collections import Counter

logger = logging.getLogger(__name__)

# User correction patterns — signals that the user corrected the agent's approach
_CORRECTION_PATTERNS = frozenset([
    r"don't\s+do\s+\w+",
    r"don't\s+need",
    r"nope",
    r"not\s+quite",
    r"wrong",
    r"that's\s+not\s+right",
    r"you\s+did\s+it\s+wrong",
    r"incorrect",
    r"incorrectly",
    r"stop\s+doing",
    r"never\s+again",
    r"skip\s+the",
    r"just\s+do\s+",
    r"go\s+ahead\s+and",
    r"try\s+again",
    r"different\s+approach",
    r"change\s+your\s+mind",
    r"actually",
    r"wait",
    r"hold\s+on",
    r"nevermind",
    r"ignore\s+that",
    r"instead",  # "try X instead" is a correction signal
])

# Backtracking patterns — agent undid or reconsidered its own actions
_BACKTRACK_PATTERNS = frozenset([
    r"actually",
    r"wait",
    r"hold\s+on",
    r"let\s+me\s+reconsider",
    r"that\s+was\s+wrong",
    r"i\s+should\s+have",
    r"i\s+realized",
    r"on\s+second\s+thought",
    r"instead\s+of",
    r"rather\s+than",
    r"instead",
    r"reconsider",
    r"recalculate",
    r"revisit",
    r"go\s+back",
    r"step\s+back",
    r"rethink",
    r"reassess",
    r"reapproach",
    r"try\s+a\s+different",
    r"another\s+way",
    r"alternative\s+approach",
    r"maybe\s+I\s+should",
    r"perhaps\s+I\s+should",
])

# Satisfaction signals — user approved or was satisfied
_SATISFACTION_PATTERNS = frozenset([
    r"perfect",
    r"excellent",
    r"great\s+job",
    r"well\s+done",
    r"thanks",
    r"thank\s+you",
    r"appreciate",
    r"good\s+work",
    r"that\s+works",
    r"that\s+solved",
    r"fixed\s+it",
    r"resolved",
    r"done\s+perfectly",
    r"exactly\s+what",
    r"spot\s+on",
    r"exactly\s+right",
    r"right\s+away",
])

# Frustration signals — user was annoyed (penalty for junk skills)
_FRUSTRATION_PATTERNS = frozenset([
    r"why\s+are\s+you",
    r"you\s+are\s+stuck",
    r"you\s+don't\s+understand",
    r"you\s+can't",
    r"this\s+is\s+stupid",
    r"this\s+is\s+useless",
    r"stop\s+trying",
    r"give\s+up",
    r"i\s+give\s+up",
    r"frustrating",
    r"annoying",
    r"annoyed",
    r"why\s+you\s+so",
    r"you\s+dumb",
    r"you\s+idiot",
    r"you\s+useless",
    r"you\s+incompetent",
    r"terrible",
    r"awful",
    r"hate\s+this",
    r"worst\s+ever",
    r"worst",
])


@dataclass
class TraceScore:
    """Structured result of a trace evaluation.

    Attributes:
        overall:        Overall score 0-100.
        efficiency:     Efficiency sub-score 0-100.
        correctness:    Correctness sub-score 0-100.
        cost:           Cost sub-score 0-100.
        skill_suggestion_score: 0.0-1.0, how worthy is a skill draft
        strengths:      List of positive observations.
        weaknesses:     List of negative observations.
        suggestions:    List of actionable improvement suggestions.
        skill_signals:  Breakdown of individual skill-worthiness signals.
    """

    overall: float = 0.0
    efficiency: float = 0.0
    correctness: float = 0.0
    cost: float = 0.0
    skill_suggestion_score: float = 0.0
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    skill_signals: dict[str, float] = field(default_factory=dict)
    detected_domain: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall,
            "efficiency": self.efficiency,
            "correctness": self.correctness,
            "cost": self.cost,
            "skill_suggestion_score": self.skill_suggestion_score,
            "strengths": self.strengths,
            "weaknesses": self.weaknesses,
            "suggestions": self.suggestions,
            "skill_signals": self.skill_signals,
            "detected_domain": self.detected_domain,
        }


@dataclass
class _TraceStats:
    """Internal computed statistics from a trace."""

    total_turns: int = 0
    tool_calls: int = 0
    errors: int = 0
    retries: int = 0
    total_tokens: int = 0
    avg_turns_per_result: float = 1.0
    has_redundant_calls: bool = False
    redundant_call_count: int = 0
    unique_tools: int = 0
    max_retry_streak: int = 0
    has_user_correction: bool = False
    has_backtrack: bool = False
    has_satisfaction: bool = False
    has_frustration: bool = False
    correction_count: int = 0
    backtrack_count: int = 0
    satisfaction_count: int = 0
    frustration_count: int = 0
    complexity_score: float = 0.0
    novelty_score: float = 0.0
    _call_names: list[str] = field(default_factory=list)


class TraceCritic:
    """Heuristic scoring engine for execution traces.

    Hybrid scoring: friction signals (error overcome, user corrections)
    + value signals (complexity, novelty, satisfaction) to determine
    if a task was worthy of a skill draft.

    Domain-aware: detects the task domain from trace context and applies
    tuned thresholds per domain (e.g., browser automation needs lower
    friction threshold than code editing).
    """

    # Domain detection from tool patterns
    _DOMAIN_INDICATORS: dict[str, list[str]] = {
        "browser_automation": ["browser_", "playwright", "puppeteer"],
        "code_refactoring": ["patch", "write_file", "read_file", "search_files", "terminal"],
        "database": ["mysql_query", "mcp_mysql", "sqlite", "postgres"],
        "file_operations": ["read_file", "write_file", "search_files", "list_files"],
        "web_research": ["web_search", "browser_navigate", "browser_snapshot", "get_images"],
        "testing": ["execute_code", "pytest", "test_"],
        "git_operations": ["git_", "gh_", "gh repo"],
        "mcp_integration": ["mcp_", "read_resource", "list_resources"],
        "skill_creation": ["skill_manage", "skill_view", "skill_list"],
        "communication": ["send_message", "text_to_speech", "speech_to_text"],
        "cron_management": ["cronjob", "schedule"],
        "delegation": ["delegate_task", "spawn"],
        "image_generation": ["image_generate", "vision_analyze", "get_images"],
        "devops": ["terminal", "docker", "kubectl", "systemctl"],
    }

    # Per-domain threshold adjustments (applied to final score)
    # Higher multiplier = domain produces more skill-worthy patterns
    _DOMAIN_MULTIPLIERS: dict[str, float] = {
        "browser_automation": 1.3,      # Browser tasks often produce reusable patterns
        "code_refactoring": 1.2,
        "web_research": 1.2,
        "database": 1.1,
        "mcp_integration": 1.1,
        "skill_creation": 1.4,          # Skill creation about skill creation
        "communication": 1.0,
        "testing": 1.0,
        "git_operations": 0.9,
        "file_operations": 0.8,         # Generic file ops are less skill-worthy
        "devops": 1.1,
        "delegation": 1.0,
        "cron_management": 1.0,
        "image_generation": 0.9,
    }

    def __init__(
        self,
        max_turns_penalty: float = 0.5,
        max_errors_penalty: float = 5.0,
        redundancy_threshold: int = 3,
        baseline_turns: float = 5.0,
    ) -> None:
        self.max_turns_penalty = max_turns_penalty
        self.max_errors_penalty = max_errors_penalty
        self.redundancy_threshold = redundancy_threshold
        self.baseline_turns = baseline_turns

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score(self, trace: dict[str, Any]) -> TraceScore:
        """Score a trace dict and return a structured TraceScore."""
        stats = self._compute_stats(trace)

        efficiency = self._score_efficiency(stats)
        correctness = self._score_correctness(stats, trace)
        cost = self._score_cost(stats)

        # Detect domain from tool calls for skill suggestion scoring
        call_names = stats.__dict__.get("_call_names", [])
        domain = self._detect_domain(call_names)
        skill_suggestion = self._score_skill_suggestion(stats, trace, domain)
        # Apply domain multiplier
        skill_suggestion = self._apply_domain_adjustment(skill_suggestion, domain)

        overall = (efficiency + correctness + cost) / 3.0

        strengths: list[str] = []
        weaknesses: list[str] = []
        suggestions: list[str] = []

        self._build_feedback(stats, efficiency, correctness, cost, strengths, weaknesses, suggestions)

        return TraceScore(
            overall=round(overall, 1),
            efficiency=round(efficiency, 1),
            correctness=round(correctness, 1),
            cost=round(cost, 1),
            skill_suggestion_score=round(skill_suggestion, 2),
            strengths=strengths,
            weaknesses=weaknesses,
            suggestions=suggestions,
            skill_signals=stats.__dict__.copy(),
            detected_domain=domain,
        )

    # ------------------------------------------------------------------
    # Signal computation
    # ------------------------------------------------------------------

    def _compute_stats(self, trace: dict[str, Any]) -> _TraceStats:
        """Extract statistics from the trace."""
        turns = trace.get("turns", [])
        tool_calls = trace.get("tool_calls", [])
        errors = trace.get("errors", [])
        retries = trace.get("retries", [])
        tokens = trace.get("tokens", 0)
        user_messages = trace.get("user_messages", [])
        agent_messages = trace.get("agent_messages", [])

        # Count unique tool calls
        call_names: list[str] = []
        for t in turns:
            if isinstance(t, dict):
                name = t.get("tool", t.get("name", ""))
                if name:
                    call_names.append(name)
        for tc in tool_calls:
            if isinstance(tc, dict):
                name = tc.get("tool", tc.get("name", ""))
                if name:
                    call_names.append(name)

        call_counts = Counter(call_names)
        unique_tools = len(call_counts)
        redundant_count = sum(c for c in call_counts.values() if c > self.redundancy_threshold)
        has_redundant = redundant_count > 0

        # Max retry streak (consecutive retries)
        max_retry_streak = 0
        current_streak = 0
        for r in retries:
            if isinstance(r, dict):
                current_streak += 1
                max_retry_streak = max(max_retry_streak, current_streak)
            else:
                current_streak = 0

        # Analyze text for correction/backtrack/satisfaction/frustration patterns
        has_correction = False
        has_backtrack = False
        has_satisfaction = False
        has_frustration = False
        correction_count = 0
        backtrack_count = 0
        satisfaction_count = 0
        frustration_count = 0

        all_text = []
        for msg in user_messages:
            if isinstance(msg, str):
                all_text.append(msg)
        for msg in agent_messages:
            if isinstance(msg, str):
                all_text.append(msg)

        text = " ".join(all_text).lower()

        # Check user messages for corrections (stronger signal from user, not agent)
        for msg in user_messages:
            if isinstance(msg, str):
                lower = msg.lower()
                for pattern in _CORRECTION_PATTERNS:
                    if re.search(pattern, lower):
                        has_correction = True
                        correction_count += 1
                        break
                for pattern in _BACKTRACK_PATTERNS:
                    if re.search(pattern, lower):
                        has_backtrack = True
                        backtrack_count += 1
                        break
                for pattern in _SATISFACTION_PATTERNS:
                    if re.search(pattern, lower):
                        has_satisfaction = True
                        satisfaction_count += 1
                        break
                for pattern in _FRUSTRATION_PATTERNS:
                    if re.search(pattern, lower):
                        has_frustration = True
                        frustration_count += 1
                        break

        # Also check agent messages for backtracks (agent realizing it went wrong)
        for msg in agent_messages:
            if isinstance(msg, str):
                lower = msg.lower()
                for pattern in _BACKTRACK_PATTERNS:
                    if re.search(pattern, lower):
                        has_backtrack = True
                        backtrack_count += 1
                        break

        # ALSO check turn results for corrections (some traces embed user feedback in turn results)
        # This is important for tests and traces where user_messages isn't populated
        for turn in turns:
            if isinstance(turn, dict):
                result = turn.get("result", "")
                if isinstance(result, str) and result.strip():
                    lower = result.lower()
                    # Check for correction-like patterns in turn results
                    for pattern in _CORRECTION_PATTERNS:
                        if re.search(pattern, lower):
                            has_correction = True
                            correction_count += 1
                            break
                    for pattern in _BACKTRACK_PATTERNS:
                        if re.search(pattern, lower):
                            has_backtrack = True
                            backtrack_count += 1
                            break
                    for pattern in _SATISFACTION_PATTERNS:
                        if re.search(pattern, lower):
                            has_satisfaction = True
                            satisfaction_count += 1
                            break
                    for pattern in _FRUSTRATION_PATTERNS:
                        if re.search(pattern, lower):
                            has_frustration = True
                            frustration_count += 1
                            break

        # Complexity: weighted by tool diversity AND task scope
        complexity_score = self._compute_complexity(unique_tools, len(turns), len(errors), len(retries))

        # Novelty: how many unique tool combinations we've seen
        novelty_score = self._compute_novelty(call_names, unique_tools)

        effective_turns = max(len(turns) - len(errors), 1)
        avg_per_result = len(turns) / effective_turns if effective_turns > 0 else 1.0

        return _TraceStats(
            total_turns=len(turns),
            tool_calls=len(call_names),
            errors=len(errors),
            retries=len(retries),
            total_tokens=tokens,
            avg_turns_per_result=avg_per_result,
            has_redundant_calls=has_redundant,
            redundant_call_count=redundant_count,
            unique_tools=unique_tools,
            max_retry_streak=max_retry_streak,
            has_user_correction=has_correction,
            has_backtrack=has_backtrack,
            has_satisfaction=has_satisfaction,
            has_frustration=has_frustration,
            correction_count=correction_count,
            backtrack_count=backtrack_count,
            satisfaction_count=satisfaction_count,
            frustration_count=frustration_count,
            complexity_score=complexity_score,
            novelty_score=novelty_score,
            _call_names=call_names,  # Store for domain detection
        )

    def _compute_complexity(self, unique_tools: int, turns: int, errors: int, retries: int) -> float:
        """Compute complexity score 0.0-1.0 based on task difficulty indicators."""
        score = 0.0
        # Tool diversity (weight: 0.3)
        score += min(1.0, unique_tools / 8.0) * 0.3
        # Task length (weight: 0.2) — longer tasks tend to be more complex
        if turns > 10:
            score += min(1.0, (turns - 10) / 20.0) * 0.2
        # Error recovery (weight: 0.3) — overcoming errors shows complexity
        if errors > 0 or retries > 0:
            score += min(1.0, (errors + retries) / 5.0) * 0.3
        # Retry streak (weight: 0.2) — consecutive retries show stubborn problem
        if retries > 0:
            score += min(1.0, retries / 3.0) * 0.2
        return min(1.0, score)

    def _compute_novelty(self, call_names: list[str], unique_tools: int) -> float:
        """Compute novelty score 0.0-1.0. How unique is this tool combination?"""
        if not call_names:
            return 0.0
        # Higher unique tool count = more novel
        return min(1.0, unique_tools / 10.0)

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _detect_domain(self, call_names: list[str]) -> str:
        """Detect the primary domain from tool call names.

        Uses pattern matching against known domain indicators.
        Returns the domain with the highest indicator match count.
        Falls back to 'general' if no domain matches well.
        """
        calls_lower = [c.lower() for c in call_names]
        best_domain = "general"
        best_score = 0

        for domain, indicators in self._DOMAIN_INDICATORS.items():
            score = 0
            for indicator in indicators:
                for call in calls_lower:
                    if indicator in call:
                        score += 1
                        break  # One match per indicator is enough
            if score > best_score:
                best_score = score
                best_domain = domain

        return best_domain

    def _apply_domain_adjustment(self, raw_score: float, domain: str) -> float:
        """Apply domain-specific multiplier to the raw skill suggestion score."""
        multiplier = self._DOMAIN_MULTIPLIERS.get(domain, 1.0)
        adjusted = raw_score * multiplier
        # Clamp to [0.0, 1.0]
        return max(0.0, min(1.0, adjusted))

    def _score_efficiency(self, stats: _TraceStats) -> float:
        """Score 0-100 based on efficiency metrics."""
        score = 100.0

        turns_ratio = stats.total_turns / max(self.baseline_turns, 1.0)
        if turns_ratio > 1.0:
            excess = turns_ratio - 1.0
            score -= excess * self.max_turns_penalty * 10

        if stats.has_redundant_calls:
            score -= min(20.0, stats.redundant_call_count * 3.0)

        if stats.avg_turns_per_result <= 1.5:
            score += 5.0

        if stats.retries > 0:
            score -= stats.retries * 2.0

        return max(0.0, min(100.0, score))

    def _score_correctness(self, stats: _TraceStats, trace: dict[str, Any]) -> float:
        """Score 0-100 based on correctness indicators."""
        score = 100.0

        if stats.errors > 0:
            score -= stats.errors * self.max_errors_penalty

        turns = trace.get("turns", [])
        for turn in turns:
            if isinstance(turn, dict):
                result = turn.get("result", "")
                if isinstance(result, str) and ("error" in result.lower() or "failed" in result.lower()):
                    if result.strip() not in ("", "None"):
                        score -= 3.0

        if stats.errors == 0 and stats.total_turns <= self.baseline_turns:
            score += 10.0

        return max(0.0, min(100.0, score))

    def _score_cost(self, stats: _TraceStats) -> float:
        """Score 0-100 based on resource cost."""
        score = 100.0
        tokens = stats.total_tokens

        if tokens > 50000:
            score -= min(40.0, (tokens - 50000) / 5000.0)
        elif tokens > 20000:
            score -= min(20.0, (tokens - 20000) / 3000.0)
        elif tokens > 10000:
            score -= min(10.0, (tokens - 10000) / 5000.0)

        if stats.retries > 0:
            score -= stats.retries * 3.0

        return max(0.0, min(100.0, score))

    def _score_skill_suggestion(self, stats: _TraceStats, trace: dict[str, Any], domain: str = "general") -> float:
        """
        Score how worthy a skill draft would be (0.0-1.0).

        HYBRID SIGNALS (weighted sum):

        FRICTION SIGNALS (Noman-style):
        - User corrections: up to 0.4 (strongest signal)
        - Error overcome: up to 0.3
        - Backtracking: up to 0.15
        - Retry streak: up to 0.10

        VALUE SIGNALS (Hermes-style, but smarter):
        - Complexity: up to 0.15
        - Novelty: up to 0.10
        - Multi-step bonus: up to 0.05

        PENALTIES:
        - Frustration: -0.15 (user was annoyed, likely junk)
        - Satisfaction: -0.05 (task went smoothly, probably doesn't need a skill)
        - No friction at all: -0.05 (simple task, probably doesn't need a skill)

        FINAL: clamped to [0.0, 1.0], then domain-adjusted.
        """
        score = 0.0

        # === FRICTION SIGNALS ===

        # Signal 1: User corrections (strongest)
        if stats.has_user_correction:
            correction_bonus = min(0.4, stats.correction_count * 0.15)
            score += correction_bonus

        # Signal 2: Error overcome (task succeeded despite errors)
        if stats.errors > 0:
            success_turns = [
                t for t in trace.get("turns", [])
                if isinstance(t, dict) and t.get("result", "")
                and not any(w in str(t.get("result", "")).lower()
                           for w in ["error", "failed", "exception"])
            ]
            if success_turns:
                error_bonus = min(0.3, stats.errors * 0.12)
                score += error_bonus

        # Signal 3: Backtracking (agent reconsidered approach)
        if stats.has_backtrack and stats.backtrack_count >= 2:
            score += min(0.15, stats.backtrack_count * 0.05)

        # Signal 4: Retry streak (consecutive retries show persistent problem)
        if stats.max_retry_streak >= 2:
            score += min(0.10, stats.max_retry_streak * 0.03)

        # === VALUE SIGNALS ===

        # Signal 5: Complexity (weighted tool diversity + task difficulty)
        if stats.complexity_score >= 0.3:
            score += 0.15 * min(1.0, stats.complexity_score)

        # Signal 6: Novelty (unique tool combinations)
        if stats.novelty_score >= 0.3:
            score += 0.10 * stats.novelty_score

        # Signal 7: Multi-step bonus (many turns without friction)
        if stats.total_turns > 8 and not stats.has_user_correction:
            score += 0.05 * min(1.0, (stats.total_turns - 8) / 10.0)

        # === PENALTIES ===

        # Penalty: Frustration detected (user was annoyed — likely junk pattern)
        if stats.has_frustration:
            score -= 0.15 * min(1.0, stats.frustration_count / 2.0)

        # Penalty: Satisfaction detected (task went smoothly — probably doesn't need a skill)
        if stats.has_satisfaction:
            score -= 0.05 * min(1.0, stats.satisfaction_count / 2.0)

        # Penalty: No friction at all (simple task, nothing worth remembering)
        if not stats.has_user_correction and not stats.has_backtrack and stats.errors == 0:
            score -= 0.05

        return max(0.0, min(1.0, score))

    def _build_feedback(
        self,
        stats: _TraceStats,
        efficiency: float,
        correctness: float,
        cost: float,
        strengths: list[str],
        weaknesses: list[str],
        suggestions: list[str],
    ) -> None:
        """Populate strengths, weaknesses, and suggestions lists."""
        if stats.errors == 0:
            strengths.append("No errors encountered during execution")
        if stats.total_turns <= self.baseline_turns:
            strengths.append(f"Concise execution: {stats.total_turns} turns (baseline: {self.baseline_turns})")
        if cost > 80:
            strengths.append(f"Low resource cost: {stats.total_tokens} tokens")
        if not stats.has_redundant_calls:
            strengths.append("No redundant tool calls detected")

        if stats.errors > 0:
            weaknesses.append(f"{stats.errors} error(s) encountered")
        if stats.has_redundant_calls:
            weaknesses.append(
                f"Redundant tool calls detected ({stats.redundant_call_count} excess calls)"
            )
        if stats.retries > 0:
            weaknesses.append(f"{stats.retries} retry(s) indicate instability")
        if stats.total_turns > self.baseline_turns * 2:
            weaknesses.append(
                f"Excessive turns: {stats.total_turns} vs baseline {self.baseline_turns}"
            )
        if cost < 50:
            weaknesses.append(f"High token usage: {stats.total_tokens} tokens")

        if stats.has_redundant_calls:
            suggestions.append("Cache or memoize repeated tool calls to reduce redundancy")
        if stats.errors > 0:
            suggestions.append("Investigate error sources — consider pre-validation before tool use")
        if stats.retries > 0:
            suggestions.append("Reduce retries by improving initial argument quality")
        if stats.total_turns > self.baseline_turns * 1.5:
            suggestions.append("Consolidate steps — combine related operations into single calls")
        if cost < 50:
            suggestions.append("Consider context compression or chunking to reduce token usage")


def create_critic(
    max_turns_penalty: float = 0.5,
    max_errors_penalty: float = 5.0,
    redundancy_threshold: int = 3,
    baseline_turns: float = 5.0,
) -> TraceCritic:
    """Factory function to create a TraceCritic with custom parameters."""
    return TraceCritic(
        max_turns_penalty=max_turns_penalty,
        max_errors_penalty=max_errors_penalty,
        redundancy_threshold=redundancy_threshold,
        baseline_turns=baseline_turns,
    )
