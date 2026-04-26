"""
Self-improvement subsystem for noman-cli.

Provides:
    - RollbackManager:  create/restore rollback points for self-modifications.
    - TraceCritic:      heuristic scoring of execution traces (domain-aware).
    - MetaAgent:        propose and validate self-improvement actions.
    - SkillQueue:       draft management with domain-level approval tracking.
    - CrossSession:     detect recurring patterns across recent sessions.
    - SkillIndex:       BM25 index over skill catalog.
    - SkillSemantic:    embedding-based skill relevance matching.
    - SkillDependencies: DAG resolver for skill load order.
    - SkillMetadata:    usage tracking + effectiveness scoring.
    - SkillLoader:      session-aware loader with token budget management.
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
from core.selfimprove.cross_session import (
    SessionPattern,
    detect_cross_session_patterns,
    format_patterns,
)
from core.selfimprove.skill_index import SkillBM25Index, SkillEntry, build_skill_index
from core.selfimprove.skill_semantic import SkillSemanticMatcher, EmbeddingProvider
from core.selfimprove.skill_dependencies import SkillDependencyGraph, DependencyResult
from core.selfimprove.skill_metadata import SkillMetadata, SkillMetadataStore
from core.selfimprove.skill_loader import (
    SkillLoader,
    SkillTokenBudget,
    LoadedSkill,
    SkillLoadResult,
    get_skill_loader,
)

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
    "SessionPattern",
    "detect_cross_session_patterns",
    "format_patterns",
    "SkillBM25Index",
    "SkillEntry",
    "build_skill_index",
    "SkillSemanticMatcher",
    "EmbeddingProvider",
    "SkillDependencyGraph",
    "DependencyResult",
    "SkillMetadata",
    "SkillMetadataStore",
    "SkillLoader",
    "SkillTokenBudget",
    "LoadedSkill",
    "SkillLoadResult",
    "get_skill_loader",
]
