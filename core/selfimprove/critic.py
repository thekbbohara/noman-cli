"""TraceCritic — heuristic scoring of execution traces."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TraceScore:
    """
    Structured result of a trace evaluation.

    Attributes:
        overall:        Overall score 0-100.
        efficiency:     Efficiency sub-score 0-100.
        correctness:    Correctness sub-score 0-100.
        cost:           Cost sub-score 0-100.
        strengths:      List of positive observations.
        weaknesses:     List of negative observations.
        suggestions:    List of actionable improvement suggestions.
    """

    overall: float = 0.0
    efficiency: float = 0.0
    correctness: float = 0.0
    cost: float = 0.0
    skill_suggestion_score: float = 0.0  # 0.0-1.0, how worthy is a skill draft
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        return {
            "overall": self.overall,
            "efficiency": self.efficiency,
            "correctness": self.correctness,
            "cost": self.cost,
            "strengths": self.strengths,
            "weaknesses": self.weaknesses,
            "suggestions": self.suggestions,
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


class TraceCritic:
    """
    Heuristic scoring engine for execution traces.

    Analyzes a trace dictionary and produces a structured score with
    feedback.  No LLM dependency — all scoring is rule-based.

    The trace dict should contain keys such as:
        - ``turns``: list of turn dicts, each with ``tool`` and ``result``.
        - ``tool_calls``: list of tool-call dicts (alternative format).
        - ``errors``: list of error dicts.
        - ``tokens``: total token count (optional).

    Attributes:
        max_turns_penalty:  Penalty per turn beyond the baseline.
        max_errors_penalty: Penalty per error.
        redundancy_threshold: Number of identical tool calls to flag.
    """

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
        """
        Score a trace dict and return a structured TraceScore.

        Args:
            trace:  Execution trace with keys ``turns``, ``tool_calls``,
                    ``errors``, ``tokens``, etc.

        Returns:
            A TraceScore with sub-scores and feedback.
        """
        stats = self._compute_stats(trace)

        efficiency = self._score_efficiency(stats)
        correctness = self._score_correctness(stats, trace)
        cost = self._score_cost(stats)
        skill_suggestion = self._score_skill_suggestion(stats, trace)

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
        )

    # ------------------------------------------------------------------
    # Internal scoring
    # ------------------------------------------------------------------

    def _compute_stats(self, trace: dict[str, Any]) -> _TraceStats:
        """Extract statistics from the trace."""
        turns = trace.get("turns", [])
        tool_calls = trace.get("tool_calls", [])
        errors = trace.get("errors", [])
        retries = trace.get("retries", [])
        tokens = trace.get("tokens", 0)

        # Count unique tool calls for redundancy detection.
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

        from collections import Counter

        call_counts = Counter(call_names)
        redundant_count = sum(c for c in call_counts.values() if c > self.redundancy_threshold)
        has_redundant = redundant_count > 0

        total_tool_calls = len(call_names)
        total_errors = len(errors)

        # Average turns per result (heuristic: turns / (turns - errors)).
        effective_turns = max(len(turns) - len(errors), 1)
        avg_per_result = len(turns) / effective_turns if effective_turns > 0 else 1.0

        return _TraceStats(
            total_turns=len(turns),
            tool_calls=total_tool_calls,
            errors=total_errors,
            retries=len(retries),
            total_tokens=tokens,
            avg_turns_per_result=avg_per_result,
            has_redundant_calls=has_redundant,
            redundant_call_count=redundant_count,
        )

    def _score_efficiency(self, stats: _TraceStats) -> float:
        """Score 0-100 based on efficiency metrics."""
        score = 100.0

        # Penalty for too many turns.
        turns_ratio = stats.total_turns / max(self.baseline_turns, 1.0)
        if turns_ratio > 1.0:
            excess = turns_ratio - 1.0
            score -= excess * self.max_turns_penalty * 10

        # Penalty for redundant tool calls.
        if stats.has_redundant_calls:
            score -= min(20.0, stats.redundant_call_count * 3.0)

        # Bonus for low avg turns per result (concise execution).
        if stats.avg_turns_per_result <= 1.5:
            score += 5.0

        # Penalty for retries.
        if stats.retries > 0:
            score -= stats.retries * 2.0

        return max(0.0, min(100.0, score))

    def _score_correctness(self, stats: _TraceStats, trace: dict[str, Any]) -> float:
        """Score 0-100 based on correctness indicators."""
        score = 100.0

        # Heavy penalty for errors.
        if stats.errors > 0:
            score -= stats.errors * self.max_errors_penalty

        # Check for error messages in turns.
        turns = trace.get("turns", [])
        for turn in turns:
            if isinstance(turn, dict):
                result = turn.get("result", "")
                if isinstance(result, str) and ("error" in result.lower() or "failed" in result.lower()):
                    if result.strip() not in ("", "None"):
                        score -= 3.0

        # Bonus for clean execution (no errors, few turns).
        if stats.errors == 0 and stats.total_turns <= self.baseline_turns:
            score += 10.0

        return max(0.0, min(100.0, score))

    def _score_cost(self, stats: _TraceStats) -> float:
        """
        Score 0-100 based on resource cost.

        Lower token usage → higher score.
        """
        score = 100.0
        tokens = stats.total_tokens

        # Heuristic: penalize high token counts.
        if tokens > 50000:
            score -= min(40.0, (tokens - 50000) / 5000.0)
        elif tokens > 20000:
            score -= min(20.0, (tokens - 20000) / 3000.0)
        elif tokens > 10000:
            score -= min(10.0, (tokens - 10000) / 5000.0)

         # Penalize excessive retries (wasted cost).
        if stats.retries > 0:
            score -= stats.retries * 3.0

        return max(0.0, min(100.0, score))

    def _score_skill_suggestion(self, stats: _TraceStats, trace: dict[str, Any]) -> float:
        """
        Score how worthy a skill draft would be (0.0-1.0).

        Signals:
        - User corrections: +0.4 (strongest signal)
        - Error overcome: +0.3
        - Iterative fix loop: +0.3
        - Complexity (tool diversity): +0.2
        - Penalty: low score if no friction signals
        """
        score = 0.0

        # Signal 1: User corrections (strongest signal)
        # Look for turns where result indicates user feedback
        turns = trace.get("turns", [])
        has_user_correction = False
        for turn in turns:
            if isinstance(turn, dict):
                result = turn.get("result", "")
                if isinstance(result, str):
                    lower = result.lower()
                    if any(w in lower for w in ["user", "correction", "fix", "change", "instead", "try", "note"]):
                        has_user_correction = True
                        break

        if has_user_correction:
            score += 0.4

        # Signal 2: Errors overcome (task succeeded despite errors)
        if stats.errors > 0:
            # Check if the trace eventually succeeded (not all turns errored)
            success_turns = [
                t for t in turns
                if isinstance(t, dict) and t.get("result", "")
                and not any(w in str(t.get("result", "")).lower() for w in ["error", "failed", "exception"])
            ]
            if success_turns:
                score += 0.3

        # Signal 3: Iterative fix loop (retries)
        if stats.retries > 0:
            score += 0.3 * min(1.0, stats.retries / 3.0)  # Cap at 0.3

        # Signal 4: Complexity (tool diversity)
        unique_tools = len(set(tc.get("tool", tc.get("name", "")) for tc in trace.get("tool_calls", [])))
        if unique_tools >= 5:
            score += 0.2 * min(1.0, unique_tools / 10.0)

        # Signal 5: Multi-step (many turns)
        if stats.total_turns > 10:
            score += 0.1 * min(1.0, (stats.total_turns - 10) / 10.0)

        # Normalize to 0.0-1.0
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
        # Strengths
        if stats.errors == 0:
            strengths.append("No errors encountered during execution")
        if stats.total_turns <= self.baseline_turns:
            strengths.append(f"Concise execution: {stats.total_turns} turns (baseline: {self.baseline_turns})")
        if cost > 80:
            strengths.append(f"Low resource cost: {stats.total_tokens} tokens")
        if not stats.has_redundant_calls:
            strengths.append("No redundant tool calls detected")

        # Weaknesses
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

        # Suggestions
        if stats.has_redundant_calls:
            suggestions.append(
                "Cache or memoize repeated tool calls to reduce redundancy"
            )
        if stats.errors > 0:
            suggestions.append(
                "Investigate error sources — consider pre-validation before tool use"
            )
        if stats.retries > 0:
            suggestions.append(
                "Reduce retries by improving initial argument quality"
            )
        if stats.total_turns > self.baseline_turns * 1.5:
            suggestions.append(
                "Consolidate steps — combine related operations into single calls"
            )
        if cost < 50:
            suggestions.append(
                "Consider context compression or chunking to reduce token usage"
            )


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
