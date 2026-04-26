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

__all__ = [
    "ChangeType",
    "ImprovementProposal",
    "ImprovementResult",
    "MetaAgent",
    "RollbackManager",
    "TraceCritic",
    "TraceScore",
    "create_critic",
]
