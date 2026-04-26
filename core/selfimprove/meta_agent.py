"""MetaAgent — proposes and validates self-improvement actions."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

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

        # Low efficiency → optimization proposals.
        if score.efficiency < 70:
            proposals.append(self._propose_optimization_generic(score))

        # Low correctness → bug-fix proposals.
        if score.correctness < 60:
            proposals.append(self._propose_correctness(score))

        # High cost → token optimization.
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

    def _propose_skill_creation(self, trace: dict[str, Any], score: TraceScore) -> str | None:
        """
        Propose a skill creation as a draft in the skill queue.

        Returns draft_id if created, None if skipped (duplicate or score too low).
        """
        from core.selfimprove.skill_queue import SkillQueue

        # Skip if score is below threshold
        if score.skill_suggestion_score < 0.7:
            return None

        # Generate skill name from trace
        skill_name = self._infer_skill_name(trace)

        # Check against existing skills to avoid duplicates
        queue = SkillQueue()
        for existing in queue.list_pending():
            if existing.name == skill_name:
                logger.info("Skipping duplicate skill draft: %s", skill_name)
                return None

        # Extract steps from trace
        steps = self._extract_steps_from_trace(trace)
        pitfalls = self._extract_pitfalls_from_trace(trace)

        # Generate SKILL.md content
        content = self._generate_skill_md(skill_name, steps, pitfalls, score)

        # Add to queue as draft
        queue.add_draft(
            name=skill_name,
            description=f"Auto-detected from trace (score: {score.skill_suggestion_score:.2f})",
            content=content,
            trigger_reason=f"Skill worthiness score: {score.skill_suggestion_score:.2f}",
            score=score.skill_suggestion_score,
        )

        return f"Draft created for '{skill_name}' (score: {score.skill_suggestion_score:.2f})"

    def _infer_skill_name(self, trace: dict[str, Any]) -> str:
        """Infer a skill name from trace context."""
        turns = trace.get("turns", [])
        # Look for task descriptions or tool names that indicate the skill's purpose
        for turn in turns:
            if isinstance(turn, dict):
                result = turn.get("result", "")
                if isinstance(result, str) and len(result) > 10:
                    # Extract first meaningful phrase
                    words = result.split()[:5]
                    name = "_".join(w.lower().strip(".,!?") for w in words if w.isalnum())
                    if len(name) > 5:
                        return f"skill_{name}"
        return f"skill_trace_{len(turns)}steps"

    def _extract_steps_from_trace(self, trace: dict[str, Any]) -> list[str]:
        """Extract key steps from trace tool calls."""
        steps = []
        tool_calls = trace.get("tool_calls", [])
        for i, tc in enumerate(tool_calls[:10]):  # Limit to first 10
            if isinstance(tc, dict):
                tool = tc.get("tool", tc.get("name", "unknown"))
                args = tc.get("args", {})
                arg_str = ", ".join(f"{k}={v}" for k, v in list(args.items())[:3])
                steps.append(f"Call {tool}({arg_str})")
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

    def _generate_skill_md(
        self,
        name: str,
        steps: list[str],
        pitfalls: list[str],
        score: TraceScore,
    ) -> str:
        """Generate SKILL.md content from trace data."""
        return f"""---
name: {name}
description: Auto-detected skill (score: {score.skill_suggestion_score:.2f})
---
# {name.replace('skill_', '').title().replace('_', ' ')}

## Trigger
Auto-detected from trace analysis — load when facing similar patterns.

## Steps
{chr(10).join(f'{i+1}. {step}' for i, step in enumerate(steps))}

## Pitfalls
{chr(10).join(pitfalls)}

## Notes
- Generated automatically by MetaAgent
- Review before using — may need refinement
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
