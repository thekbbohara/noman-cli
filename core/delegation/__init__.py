"""Delegation module for spawning independent workers."""

from __future__ import annotations

from core.delegation.manager import DelegationManager
from core.delegation.worker import Worker
from core.delegation.session import WorkerSession
from core.delegation.context import ContextPropagator
from core.delegation.results import ResultAggregator

__all__ = [
    "DelegationManager",
    "Worker",
    "WorkerSession",
    "ContextPropagator",
    "ResultAggregator",
]
