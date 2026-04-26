"""
Self-improvement subsystem for noman-cli.

Provides:
    - RollbackManager:  create/restore rollback points for self-modifications.
    - TraceCritic:      heuristic scoring of execution traces.
    - MetaAgent:        propose and validate self-improvement actions.
"""

from __future__ import annotations

from core.selfimprove.critic import TraceCritic, TraceScore, create_critic
from core.selfimprove.meta_agent import (
    ChangeType,
    ImprovementProposal,
    ImprovementResult,
    MetaAgent,
)
from core.selfimprove.rollback import RollbackManager
from core.selfimprove.executor import ChangeExecutor, ExecutionResult
from core.selfimprove.change_tracker import ChangeTracker
from core.selfimprove.diff_preview import format_diff
from core.selfimprove.skill_queue import SkillQueue, SkillDraft

__all__ = [
    "ChangeType",
    "ChangeExecutor",
    "ChangeTracker",
    "ExecutionResult",
    "ImprovementProposal",
    "ImprovementResult",
    "MetaAgent",
    "RollbackManager",
    "SkillDraft",
    "SkillQueue",
    "TraceCritic",
    "TraceScore",
    "create_critic",
    "format_diff",
]
