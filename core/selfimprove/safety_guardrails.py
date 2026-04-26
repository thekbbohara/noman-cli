"""Immutable guardrails that prevent the meta-agent from modifying itself."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from core.errors import SelfModificationError

logger = logging.getLogger(__name__)


# These paths/modules are NEVER allowed as targets of self-improvement.
_IMMUTABLE_PATHS: frozenset[str] = frozenset(
    {
        "core/errors",
        "core/security",
        "core/selfimprove/safety_guardrails",
        "user/config.toml",
    }
)

# These tool names cannot be generated or modified by the agent.
_IMMUTABLE_TOOLS: frozenset[str] = frozenset(
    {"rollback", "emergency_stop", "emergency_disable_self_improve"}
)


@dataclass(frozen=True)
class SafetyGuardrails:
    """Immutable constraints on self-modification."""

    immutable_paths: frozenset[str] = field(default_factory=lambda: _IMMUTABLE_PATHS)
    immutable_tools: frozenset[str] = field(default_factory=lambda: _IMMUTABLE_TOOLS)
    max_prompt_diff_percent: int = 20  # >20% diff requires human approval
    require_human_approval_for: frozenset[str] = frozenset(
        {"new_tool", "prompt_replace", "heuristic_delete"}
    )

    def validate_target(self, target: str) -> None:
        """Raise SelfModificationError if *target* is immutable."""
        import os

        normalized = os.path.normpath(target)
        for forbidden in self.immutable_paths:
            norm_forbidden = os.path.normpath(forbidden)
            # Exact match or the forbidden path is a parent directory
            if normalized == norm_forbidden or normalized.startswith(norm_forbidden + os.sep):
                raise SelfModificationError(
                    f"Target '{target}' is in immutable path '{forbidden}'"
                )
        logger.debug("Guardrail OK: %s is mutable", target)

    def validate_tool_name(self, name: str) -> None:
        """Raise SelfModificationError if *name* is an immutable tool."""
        if name in self.immutable_tools:
            raise SelfModificationError(
                f"Tool '{name}' is immutable and cannot be modified"
            )

    def requires_approval(self, change_type: str, diff_percent: float = 0.0) -> bool:
        """Return True if this change needs human approval."""
        if change_type in self.require_human_approval_for:
            return True
        if diff_percent > self.max_prompt_diff_percent:
            return True
        return False
