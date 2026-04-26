"""MetaAgent — proposes and validates self-improvement actions."""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any
from collections import Counter

from core.errors import SelfModificationError
from core.selfimprove.critic import TraceCritic, TraceScore
from core.selfimprove.safety_guardrails import SafetyGuardrails

logger = logging.getLogger(__name__)


class ChangeType(StrEnum):
    """Types of self-improvement changes the MetaAgent can propose."""

    PROMPT_TWEAK = "prompt_tweak"
    HEURISTIC_ADDITION = "heuristic_addition"
    HEURISTIC_MODIFICATION = "heuristic_modification"
    HEURISTIC_DELETION = "heuristic_deletion"
    SKILL_SUGGESTION = "skill_suggestion"
    NEW_TOOL = "new_tool"
    CONFIG_UPDATE = "config_update"
    BUG_FIX = "bug_fix"
    OPTIMIZATION = "optimization"


@dataclass
class ImprovementProposal:
    """
    A validated self-improvement proposal.

    Attributes:
        proposal_id:  Unique identifier for this proposal.
        change_type:  Category of the proposed change.
        description:  Human-readable description of the change.
        target_file:  File path the change targets (if applicable).
        old_content:  Current content (for diffs).
        new_content:  Proposed new content (for diffs).
        confidence:   Confidence score 0.0-1.0.
        requires_approval:  Whether human approval is required.
        reasoning:  Explanation of why this change is proposed.
        trace_score:  The TraceScore that informed this proposal.
    """

    proposal_id: str
    change_type: ChangeType
    description: str
    target_file: str
    old_content: str
    new_content: str
    confidence: float
    requires_approval: bool = False
    reasoning: str = ""
    trace_score: TraceScore | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        return {
            "proposal_id": self.proposal_id,
            "change_type": self.change_type.value,
            "description": self.description,
            "target_file": self.target_file,
            "old_content": self.old_content,
            "new_content": self.new_content,
            "confidence": self.confidence,
            "requires_approval": self.requires_approval,
            "reasoning": self.reasoning,
        }


@dataclass
class ImprovementResult:
    """
    Container for a set of validated improvement proposals.

    Attributes:
        proposals:  List of validated ImprovementProposal objects.
        guardrail_violations:  List of proposals rejected by safety guardrails.
    """

    proposals: list[ImprovementProposal] = field(default_factory=list)
    guardrail_violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        return {
            "proposals": [p.to_dict() for p in self.proposals],
            "guardrail_violations": self.guardrail_violations,
            "total_proposals": len(self.proposals),
            "violations_count": len(self.guardrail_violations),
        }


# ------------------------------------------------------------------
# BM25-lite: simple token-based text similarity for skill name inference
# ------------------------------------------------------------------

def _tokenize(text: str) -> set[str]:
    """Simple tokenizer: lowercase, split on non-alphanumeric."""
    return set(re.findall(r'[a-z0-9_]+', text.lower()))


def _bm25_score(query_tokens: set[str], doc_text: str, k1: float = 1.5, b: float = 0.75) -> float:
    """Simple BM25-like scoring for a single query against a document string."""
    doc_tokens = _tokenize(doc_text)
    if not doc_tokens or not query_tokens:
        return 0.0

    doc_len = len(doc_tokens)
    idf_cache: dict[str, float] = {}

    score = 0.0
    for token in query_tokens:
        # IDF: 1 if term never seen (sparse), else log(1 + freq/doc_count)
        if token not in idf_cache:
            tf = 1 if token in doc_tokens else 0
            idf_cache[token] = 1.0 + (1.0 / (tf + 1))

        # TF-IDF with BM25 normalization
        tf = 1  # token appears once in query
        numerator = tf * (k1 + 1)
        denominator = tf + k1 * (1 - b + b * doc_len / 100)
        score += idf_cache[token] * numerator / denominator

    return score


def _search_existing_skills(query: str, max_results: int = 5) -> list[tuple[str, str, float]]:
    """Search existing skills on disk for the best name match.

    Returns list of (skill_name, description, score) sorted by relevance.
    Uses BM25-lite scoring against skill names and descriptions.
    """
    skill_dir = Path.home() / ".hermes/skills"
    if not skill_dir.exists():
        return []

    query_tokens = _tokenize(query)
    results = []

    for item in sorted(skill_dir.iterdir()):
        if not item.is_dir() or item.name.startswith("."):
            continue
        skill_file = item / "SKILL.md"
        if not skill_file.exists():
            continue

        content = skill_file.read_text()[:500]
        # Score against name and description
        name_score = _bm25_score(query_tokens, item.name)
        desc_score = _bm25_score(query_tokens, content)
        total_score = name_score * 1.5 + desc_score  # Name match weighted higher
        if total_score > 0.1:
            results.append((item.name, content[:100], total_score))

    results.sort(key=lambda x: x[2], reverse=True)
    return results[:max_results]


class MetaAgent:
    """
    Proposes self-improvements based on trace critic scores.

    Takes execution traces, scores them via TraceCritic, and generates
    improvement proposals (prompt tweaks, heuristic additions, skill
    suggestions) that are validated against SafetyGuardrails before
    being returned.

    Attributes:
        guardrails:  SafetyGuardrails instance for validating proposals.
        critic:      TraceCritic instance for scoring traces.
        max_proposals:  Maximum number of proposals per analysis.
    """

    def __init__(
        self,
        guardrails: SafetyGuardrails | None = None,
        critic: TraceCritic | None = None,
        max_proposals: int = 5,
    ) -> None:
        self.guardrails = guardrails or SafetyGuardrails()
        self.critic = critic or TraceCritic()
        self.max_proposals = max_proposals

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, trace: dict[str, Any]) -> ImprovementResult:
        """
        Analyze a trace and return validated improvement proposals.

        Args:
            trace:  Execution trace dict with ``turns``, ``tool_calls``,
                    ``errors``, ``tokens``, etc.

        Returns:
            An ImprovementResult containing validated proposals and
            any guardrail violations.
        """
        score = self.critic.score(trace)
        proposals: list[ImprovementProposal] = []
        violations: list[str] = []

        # Generate proposals based on score dimensions.
        proposals = self._generate_proposals(score)

        # Validate each proposal through guardrails.
        validated: list[ImprovementProposal] = []
        for proposal in proposals:
            try:
                self._validate_proposal(proposal)
                validated.append(proposal)
            except SelfModificationError as exc:
                violations.append(f"Proposal '{proposal.proposal_id}' rejected: {exc}")
                logger.debug("Guardrail rejection: %s", exc)

        # Check for skill-worthy traces
        if score.skill_suggestion_score >= 0.7:
            skill_id = self._propose_skill_creation(trace, score)
            if skill_id:
                logger.info("Skill draft queued: %s", skill_id)

        return ImprovementResult(proposals=validated, guardrail_violations=violations)

    def propose_for_file(
        self,
        trace: dict[str, Any],
        target_file: str,
    ) -> ImprovementResult:
        """
        Generate proposals specifically targeting one file.

        Args:
            trace:  Execution trace dict.
            target_file:  File path to generate proposals for.

        Returns:
            An ImprovementResult with proposals targeting the given file.
        """
        score = self.critic.score(trace)
        proposals: list[ImprovementProposal] = []

        if score.correctness < 60:
            proposals.extend(
                self._propose_bug_fix(target_file, score)
            )

        if score.efficiency < 70:
            proposals.extend(
                self._propose_optimization(target_file, score)
            )

        if score.cost < 60:
            proposals.extend(
                self._propose_prompt_tweak(target_file, score)
            )

        # Validate through guardrails.
        validated: list[ImprovementProposal] = []
        for proposal in proposals:
            try:
                self._validate_proposal(proposal)
                validated.append(proposal)
            except SelfModificationError:
                pass

        return ImprovementResult(proposals=validated)

    # ------------------------------------------------------------------
    # Internal proposal generators
    # ------------------------------------------------------------------

    def _generate_proposals(self, score: TraceScore) -> list[ImprovementProposal]:
        """Generate improvement proposals based on a TraceScore."""
        proposals: list[ImprovementProposal] = []

        # Low efficiency -> optimization proposals.
        if score.efficiency < 70:
            proposals.append(self._propose_optimization_generic(score))

        # Low correctness -> bug-fix proposals.
        if score.correctness < 60:
            proposals.append(self._propose_correctness(score))

        # High cost -> token optimization.
        if score.cost < 60:
            proposals.append(self._propose_cost_reduction(score))

        # General improvements for all traces.
        proposals.extend(self._propose_heuristics(score))

        # Cap proposals.
        return proposals[: self.max_proposals]

    def _propose_prompt_tweak(
        self, target_file: str, score: TraceScore
    ) -> list[ImprovementProposal]:
        """Generate a prompt tweak proposal."""
        prompt_id = f"prompt_{uuid.uuid4().hex[:8]}"
        old = 'System: "Be concise and efficient."'
        new = 'System: "Be concise and efficient. Avoid redundant tool calls."'
        return [
            ImprovementProposal(
                proposal_id=prompt_id,
                change_type=ChangeType.PROMPT_TWEAK,
                description="Add redundancy-avoidance instruction to system prompt",
                target_file=target_file,
                old_content=old,
                new_content=new,
                confidence=0.75,
                requires_approval=True,
                reasoning=f"Score {score.overall:.0f}/100 suggests prompt-level inefficiency. "
                          f"Adding anti-redundancy instruction may reduce wasted tool calls.",
                trace_score=score,
            )
        ]

    def _propose_bug_fix(
        self, target_file: str, score: TraceScore
    ) -> list[ImprovementProposal]:
        """Generate a bug fix proposal."""
        fix_id = f"fix_{uuid.uuid4().hex[:8]}"
        return [
            ImprovementProposal(
                proposal_id=fix_id,
                change_type=ChangeType.BUG_FIX,
                description="Review and fix correctness issues in trace",
                target_file=target_file,
                old_content="",
                new_content="",
                confidence=0.6,
                requires_approval=True,
                reasoning=f"Correctness score {score.correctness:.0f}/100 indicates "
                          f"execution errors. Reviewing trace for bugs is recommended.",
                trace_score=score,
            )
        ]

    def _propose_optimization(
        self, target_file: str, score: TraceScore
    ) -> list[ImprovementProposal]:
        """Generate an optimization proposal for a specific file."""
        opt_id = f"opt_{uuid.uuid4().hex[:8]}"
        return [
            ImprovementProposal(
                proposal_id=opt_id,
                change_type=ChangeType.OPTIMIZATION,
                description=f"Optimize code in {target_file}",
                target_file=target_file,
                old_content="",
                new_content=f"# TODO: Optimize based on efficiency score {score.efficiency:.0f}",
                confidence=0.6,
                reasoning=f"Efficiency score {score.efficiency:.0f}/100 is below threshold. "
                          f"Profile and optimize {target_file}.",
                trace_score=score,
            )
        ]

    def _propose_optimization_generic(self, score: TraceScore) -> ImprovementProposal:
        """Generate a generic optimization proposal."""
        opt_id = f"opt_{uuid.uuid4().hex[:8]}"
        return ImprovementProposal(
            proposal_id=opt_id,
            change_type=ChangeType.OPTIMIZATION,
            description="General workflow optimization",
            target_file="core/orchestrator/core.py",
            old_content="",
            new_content="# TODO: Optimize orchestration loop based on efficiency score "
                       f"{score.efficiency:.0f}/100",
            confidence=0.65,
            reasoning=f"Overall efficiency score {score.efficiency:.0f}/100 indicates "
                      f"room for workflow optimization.",
            trace_score=score,
        )

    def _propose_correctness(self, score: TraceScore) -> ImprovementProposal:
        """Generate a correctness-focused proposal."""
        fix_id = f"fix_{uuid.uuid4().hex[:8]}"
        return ImprovementProposal(
            proposal_id=fix_id,
            change_type=ChangeType.BUG_FIX,
            description="Improve error handling in tool execution",
            target_file="core/tools/bus.py",
            old_content="",
            new_content="# TODO: Add pre-validation for tool arguments to reduce errors",
            confidence=0.7,
            reasoning=f"Correctness score {score.correctness:.0f}/100 is below threshold. "
                      f"Adding pre-validation may reduce runtime errors.",
            trace_score=score,
        )

    def _propose_cost_reduction(self, score: TraceScore) -> ImprovementProposal:
        """Generate a cost-reduction proposal."""
        cost_id = f"cost_{uuid.uuid4().hex[:8]}"
        return ImprovementProposal(
            proposal_id=cost_id,
            change_type=ChangeType.PROMPT_TWEAK,
            description="Reduce token usage via prompt optimization",
            target_file="core/context/manager.py",
            old_content="",
            new_content="# TODO: Compress context windows to reduce token cost",
            confidence=0.6,
            reasoning=f"Cost score {score.cost:.0f}/100 indicates high token usage. "
                      f"Context compression may help.",
            trace_score=score,
        )

    def _propose_heuristics(self, score: TraceScore) -> list[ImprovementProposal]:
        """Generate heuristic addition/modification proposals."""
        proposals: list[ImprovementProposal] = []

        if score.efficiency < 80:
            h_id = f"heur_{uuid.uuid4().hex[:8]}"
            proposals.append(
                ImprovementProposal(
                    proposal_id=h_id,
                    change_type=ChangeType.HEURISTIC_ADDITION,
                    description="Add tool-call deduplication heuristic",
                    target_file="core/utils/step_pruner.py",
                    old_content="",
                    new_content="# heuristic: deduplicate consecutive identical tool calls",
                    confidence=0.7,
                    reasoning="Deduplication heuristics can reduce redundant work.",
                    trace_score=score,
                )
            )

        if score.correctness < 85:
            h_id = f"heur_{uuid.uuid4().hex[:8]}"
            proposals.append(
                ImprovementProposal(
                    proposal_id=h_id,
                    change_type=ChangeType.HEURISTIC_ADDITION,
                    description="Add error-pattern detection heuristic",
                    target_file="core/utils/step_pruner.py",
                    old_content="",
                    new_content="# heuristic: detect recurring error patterns across turns",
                    confidence=0.65,
                    reasoning="Error-pattern heuristics can help prevent repeated failures.",
                    trace_score=score,
                )
            )

        return proposals

    # ------------------------------------------------------------------
    # SKILL CREATION — improved version
    # ------------------------------------------------------------------

    def _propose_skill_creation(self, trace: dict[str, Any], score: TraceScore) -> str | None:
        """
        Propose a skill creation as a draft in the skill queue.

        Uses domain-aware thresholds: domains with high approval rates
        use lower thresholds (more permissive), while low-rate domains
        use higher thresholds (more conservative).

        Returns draft_id if created, None if skipped (duplicate, low score, or rate-limited).
        """
        from core.selfimprove.skill_queue import SkillQueue

        # Skip if score is below threshold
        queue = SkillQueue()
        recommended_threshold = queue.get_recommended_threshold(score.detected_domain)

        if score.skill_suggestion_score < recommended_threshold:
            return None

        # Rate limit: max 2 skill drafts per session
        pending = queue.list_pending()
        if len(pending) >= 2:
            logger.info("Rate limited: %d pending drafts, skipping new skill proposal", len(pending))
            return None

        # Generate skill name and content — use improved inference
        skill_name = self._infer_skill_name(trace, score)
        if not skill_name:
            return None

        # Extract rich trace analysis
        steps = self._extract_steps_from_trace(trace)
        pitfalls = self._extract_pitfalls_from_trace(trace)
        corrections = self._extract_corrections_from_trace(trace)
        approach = self._extract_approach_from_trace(trace)
        conditions = self._extract_trigger_conditions(trace)

        # Generate enriched SKILL.md content
        content = self._generate_skill_md(skill_name, steps, pitfalls, corrections, score, approach, conditions)

        # Add to queue as draft (duplicate check happens in add_draft)
        draft_id = queue.add_draft(
            name=skill_name,
            description=f"Auto-detected from {score.detected_domain} trace (score: {score.skill_suggestion_score:.2f})",
            content=content,
            trigger_reason=f"Skill worthiness: {score.skill_suggestion_score:.2f} | {score.strengths[:2]}",
            score=score.skill_suggestion_score,
        )

        if draft_id:
            logger.info("Skill draft queued: %s — %s", draft_id, skill_name)
        return draft_id

    def _infer_skill_name(self, trace: dict[str, Any], score: TraceScore) -> str | None:
        """Infer a skill name from trace context using multiple heuristics.

        Priority:
        1. BM25 search against existing skills (best match + suffix)
        2. User message keywords (most reliable)
        3. Correction text (what the user wanted)
        4. Turn result keywords (task description)
        5. Tool call patterns
        6. Domain-aware fallback

        Returns None if no reasonable name can be inferred.
        """
        turns = trace.get("turns", [])
        user_messages = trace.get("user_messages", [])
        tool_calls = trace.get("tool_calls", [])
        domain = score.detected_domain

        # Strategy 1: BM25 search against existing skills
        # Build a query from trace context
        query_parts = []
        for msg in user_messages:
            if isinstance(msg, str) and len(msg) > 10:
                query_parts.append(msg)
        for turn in turns:
            if isinstance(turn, dict):
                result = turn.get("result", "")
                if isinstance(result, str) and len(result) > 10:
                    query_parts.append(result)

        if query_parts:
            query = " ".join(query_parts)[:500]
            matches = _search_existing_skills(query)
            if matches:
                best_name, best_desc, best_score = matches[0]
                # Check if the best match is a good fit (high enough score)
                if best_score > 2.0:
                    # Check if adding a suffix makes it more specific
                    # Extract last meaningful word from query
                    words = _tokenize(query)
                    long_words = [w for w in words if len(w) > 4 and w.isalpha()]
                    if long_words:
                        last_word = long_words[-1]
                        candidate = f"skill_{best_name}_{last_word}"
                        # Check this candidate doesn't already exist
                        candidate_path = Path.home() / ".hermes/skills" / candidate
                        if not candidate_path.exists():
                            return candidate
                    return f"skill_{best_name}"

        # Strategy 2: Extract from user messages (most reliable indicator of intent)
        for msg in user_messages:
            if isinstance(msg, str) and len(msg) > 10:
                words = _tokenize(msg.lower())
                # Prefer longer, meaningful words
                meaningful = [w for w in words if len(w) > 4 and w.isalpha()]
                if meaningful:
                    # Pick the most "actionable" word (last meaningful one)
                    return f"skill_{meaningful[-1]}"

        # Strategy 3: Extract from correction text
        for turn in turns:
            if isinstance(turn, dict):
                result = turn.get("result", "")
                if isinstance(result, str):
                    lower = result.lower()
                    if any(w in lower for w in ["fix", "change", "instead", "try", "note", "actually"]):
                        words = _tokenize(lower)
                        meaningful = [w for w in words if len(w) > 3 and w.isalpha()]
                        if meaningful:
                            return f"skill_{meaningful[-1]}"

        # Strategy 4: Extract from tool call patterns
        tool_names = []
        for tc in tool_calls:
            if isinstance(tc, dict):
                name = tc.get("tool", tc.get("name", ""))
                if name:
                    tool_names.append(name)
        if tool_names:
            counts = Counter(tool_names)
            unique_tools = [t for t, c in counts.items() if c == 1]
            if unique_tools:
                name = unique_tools[0].replace("-", "_").replace(" ", "_")
                if len(name) > 5:
                    return f"skill_{name}"
            first = tool_names[0].replace("-", "_").replace(" ", "_")
            return f"skill_{first}"

        # Strategy 5: Domain-aware fallback
        domain_names = {
            "browser_automation": "browser-automation",
            "code_refactoring": "code-refactoring",
            "database": "database-query",
            "web_research": "web-research",
            "mcp_integration": "mcp-integration",
            "skill_creation": "skill-management",
            "communication": "cross-platform-communication",
            "testing": "test-automation",
            "git_operations": "git-workflow",
            "devops": "devops-automation",
            "file_operations": "file-operations",
        }
        fallback = domain_names.get(domain, "general-task")
        return f"skill-{fallback}"

    def _extract_approach_from_trace(self, trace: dict[str, Any]) -> list[str]:
        """Extract the *approach* taken in the trace — not just tool calls but the pattern.

        Analyzes the trace to understand the methodology, not just the mechanics.
        Returns a list of approach descriptions.
        """
        turns = trace.get("turns", [])
        errors = trace.get("errors", [])
        corrections = self._extract_corrections_from_trace(trace)

        approach = []

        # Detect approach patterns
        tool_types = set()
        for t in turns:
            if isinstance(t, dict):
                tool = t.get("tool", "")
                if "browser" in tool.lower():
                    tool_types.add("browser_interaction")
                elif "terminal" in tool.lower():
                    tool_types.add("shell_command")
                elif "file" in tool.lower() or "patch" in tool.lower():
                    tool_types.add("file_modification")
                elif "search" in tool.lower():
                    tool_types.add("information_retrieval")
                elif "query" in tool.lower() or "mysql" in tool.lower():
                    tool_types.add("database_operation")
                elif "mcp" in tool.lower():
                    tool_types.add("mcp_integration")

        if tool_types:
            approach.append(f"Approach: Multi-step workflow using {', '.join(sorted(tool_types))}")

        # Did we recover from errors?
        if errors:
            approach.append(f"Recovered from {len(errors)} error(s) during execution")

        # Did we follow user corrections?
        if corrections:
            approach.append(f"Incorporated {len(corrections)} user correction(s) to refine approach")

        # Did we need to iterate?
        if len(turns) > 3:
            approach.append(f"Required {len(turns)} steps to reach solution (iterative refinement)")

        if not approach:
            approach.append("Standard single-pass approach")

        return approach

    def _extract_trigger_conditions(self, trace: dict[str, Any]) -> list[str]:
        """Extract conditions under which this pattern should be triggered.

        Analyzes the trace to identify the *when* and *why* this skill applies.
        """
        turns = trace.get("turns", [])
        tool_calls = trace.get("tool_calls", [])
        errors = trace.get("errors", [])

        conditions = []

        # What tools were used? -> when to trigger
        tool_names = set()
        for tc in tool_calls:
            if isinstance(tc, dict):
                name = tc.get("tool", "")
                if name:
                    tool_names.add(name)

        if tool_names:
            conditions.append(f"Trigger: When using tools [{', '.join(sorted(tool_names))}]")

        # Were there errors that needed handling?
        error_messages = [e.get("message", str(e)) for e in errors if isinstance(e, dict)]
        if error_messages:
            conditions.append(f"Need to handle: {'; '.join(error_messages[:3])}")

        # Was there a specific user request?
        user_messages = trace.get("user_messages", [])
        for msg in user_messages:
            if isinstance(msg, str) and len(msg) > 10:
                conditions.append(f"Context: {msg[:80]}")
                break

        if not conditions:
            conditions.append("Trigger: When facing similar tool call patterns")

        return conditions

    def _extract_steps_from_trace(self, trace: dict[str, Any]) -> list[str]:
        """Extract key steps from trace tool calls.

        Improved version: groups related tool calls and describes the *intent*
        of each step, not just the raw tool name.
        """
        tool_calls = trace.get("tool_calls", [])
        turns = trace.get("turns", [])

        steps = []
        seen_tools = set()

        for i, tc in enumerate(tool_calls[:15]):
            if not isinstance(tc, dict):
                continue
            tool = tc.get("tool", tc.get("name", "unknown"))
            args = tc.get("args", {})

            # Group consecutive calls to the same tool
            if tool in seen_tools and len(seen_tools) > 3:
                # Skip duplicates if we already have enough steps
                continue

            # Format args meaningfully
            arg_parts = []
            for k, v in list(args.items())[:3]:
                val_str = str(v)
                if len(val_str) > 50:
                    val_str = val_str[:50] + "..."
                arg_parts.append(f"{k}={val_str}")

            step_text = f"Call {tool}({', '.join(arg_parts)})"

            # Add context from turn result
            if i < len(turns) and isinstance(turns[i], dict):
                result = turns[i].get("result", "")
                if isinstance(result, str) and result.strip() and result not in ("", "None"):
                    # If result indicates success, summarize it
                    result_lower = result.lower()
                    if not any(w in result_lower for w in ["error", "failed", "exception"]):
                        # Summarize the result
                        summary = result[:80]
                        step_text += f" -> {summary}"

            steps.append(step_text)
            seen_tools.add(tool)

        return steps if steps else ["Multiple tool calls executed"]

    def _extract_pitfalls_from_trace(self, trace: dict[str, Any]) -> list[str]:
        """Extract pitfalls/errors from trace."""
        pitfalls = []
        errors = trace.get("errors", [])
        for err in errors[:5]:
            if isinstance(err, dict):
                msg = err.get("message", str(err))
                pitfalls.append(f"- {msg}")
        return pitfalls if pitfalls else ["None detected"]

    def _extract_corrections_from_trace(self, trace: dict[str, Any]) -> list[str]:
        """Extract user corrections from trace."""
        corrections = []
        user_messages = trace.get("user_messages", [])
        for msg in user_messages:
            if isinstance(msg, str):
                lower = msg.lower()
                if any(w in lower for w in ["don't", "instead", "try", "fix", "change", "actually", "wait"]):
                    if len(msg) > 10:
                        corrections.append(msg[:100])
        return corrections[:5]

    def _generate_skill_md(
        self,
        name: str,
        steps: list[str],
        pitfalls: list[str],
        corrections: list[str],
        score: TraceScore,
        approach: list[str],
        conditions: list[str],
    ) -> str:
        """Generate enriched SKILL.md content from trace data.

        Produces a well-structured skill document with:
        - Clear trigger conditions
        - Step-by-step approach
        - Known pitfalls and corrections
        - Domain context
        """
        corrections_section = ""
        if corrections:
            corrections_section = "## Corrections\n\nThe user corrected the agent on these points:\n\n" + "\n".join(
                f"- {c}" for c in corrections
            ) + "\n"

        conditions_section = "## When to Use\n\n" + "\n".join(f"- {c}" for c in conditions) + "\n"

        approach_section = "## Approach\n\n" + "\n".join(f"- {a}" for a in approach) + "\n"

        return f"""---
name: {name}
description: Auto-detected skill ({score.detected_domain}, score: {score.skill_suggestion_score:.2f})
---

# {name.replace('skill_', '').title().replace('_', ' ')}

## Trigger
Auto-detected from {score.detected_domain} trace analysis. Load when facing similar patterns.

## Conditions
{conditions_section}## Approach
{approach_section}## Steps
{chr(10).join(f'{i+1}. {step}' for i, step in enumerate(steps))}

## Pitfalls
{chr(10).join(pitfalls)}

{corrections_section}## Notes
- Generated automatically by MetaAgent
- Review before using — may need refinement
- Score: {score.skill_suggestion_score:.2f}/1.0
- Domain: {score.detected_domain}
"""

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate_proposal(self, proposal: ImprovementProposal) -> None:
        """
        Validate a proposal through safety guardrails.

        Raises:
            SelfModificationError:  If the proposal violates any guardrail.
        """
        # Check target path immutability.
        self.guardrails.validate_target(proposal.target_file)

        # Check if change type requires human approval.
        needs_approval = self.guardrails.requires_approval(
            change_type=proposal.change_type.value,
            diff_percent=self._estimate_diff_percent(proposal),
        )
        proposal.requires_approval = needs_approval

    def _estimate_diff_percent(self, proposal: ImprovementProposal) -> float:
        """Estimate the diff percentage between old and new content."""
        old_len = len(proposal.old_content)
        new_len = len(proposal.new_content)
        if old_len == 0:
            return 100.0  # New file = 100% change.
        diff = abs(new_len - old_len)
        return (diff / old_len) * 100.0
