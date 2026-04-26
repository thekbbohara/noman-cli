"""
Skill dependency graph resolver.

Parses SKILL.md frontmatter for dependency declarations and builds
a DAG (directed acyclic graph) to determine correct load order.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional
from collections import deque


@dataclass
class DependencyResult:
    """Result of dependency resolution."""
    skill_id: str
    status: str  # "ok", "missing", "circular", "optional_missing"
    missing_deps: list[str] = field(default_factory=list)
    optional_deps: list[str] = field(default_factory=list)
    load_order: list[str] = field(default_factory=list)
    error: str = ""


class SkillDependencyGraph:
    """
    Build and resolve skill dependency DAG.
    
    Parses SKILL.md frontmatter for:
      dependencies:
        required: [dep1, dep2]
        optional: [dep3]
    
    Provides topological sort for correct load order.
    Detects circular dependencies and reports missing ones.
    """

    def __init__(self):
        self._graph: dict[str, list[str]] = {}  # skill -> required deps
        self._optional: dict[str, list[str]] = {}  # skill -> optional deps
        self._all_skills: set[str] = set()

    def add_skill(self, skill_id: str, required_deps: list[str] = None,
                  optional_deps: list[str] = None):
        """Register a skill with its dependencies."""
        self._all_skills.add(skill_id)
        if skill_id not in self._graph:
            self._graph[skill_id] = required_deps or []
        if skill_id not in self._optional:
            self._optional[skill_id] = optional_deps or []

    def has_skill(self, skill_id: str) -> bool:
        return skill_id in self._all_skills

    def get_required_deps(self, skill_id: str) -> list[str]:
        return self._graph.get(skill_id, [])

    def get_optional_deps(self, skill_id: str) -> list[str]:
        return self._optional.get(skill_id, [])

    def detect_circular(self) -> list[list[str]]:
        """
        Detect all circular dependency cycles using DFS.
        Returns list of cycles (each cycle is a list of skill IDs).
        """
        cycles = []
        visited = set()
        rec_stack = set()

        def _dfs(node, path):
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for neighbor in self._graph.get(node, []):
                if neighbor not in visited:
                    if neighbor in self._all_skills:
                        _dfs(neighbor, path)
                elif neighbor in rec_stack:
                    # Found cycle
                    cycle_start = path.index(neighbor)
                    cycle = path[cycle_start:] + [neighbor]
                    cycles.append(cycle)

            path.pop()
            rec_stack.discard(node)

        for skill in self._all_skills:
            if skill not in visited:
                _dfs(skill, [])

        return cycles

    def resolve_load_order(self, target_skills: list[str]) -> list[str]:
        """
        Resolve load order for a list of skills using topological sort.
        
        Returns skills in correct load order (dependencies first).
        """
        required = set()

        # BFS to find all required transitive deps
        queue = deque()
        for skill in target_skills:
            queue.append(skill)
            required.add(skill)

        while queue:
            skill = queue.popleft()
            for dep in self._graph.get(skill, []):
                if dep not in required:
                    required.add(dep)
                    queue.append(dep)

        # Topological sort of required set
        in_degree = {s: 0 for s in required}
        for s in required:
            for dep in self._graph.get(s, []):
                if dep in in_degree:
                    in_degree[s] = in_degree.get(s, 0)  # ensure key exists

        # Recount with proper scope
        adj = {s: [] for s in required}
        in_deg = {s: 0 for s in required}
        for s in required:
            for dep in self._graph.get(s, []):
                if dep in required:
                    adj[dep].append(s)
                    in_deg[s] += 1

        # Kahn's algorithm
        queue = deque([s for s in required if in_deg[s] == 0])
        order = []

        while queue:
            node = queue.popleft()
            order.append(node)
            for neighbor in adj.get(node, []):
                in_deg[neighbor] -= 1
                if in_deg[neighbor] == 0:
                    queue.append(neighbor)

        if len(order) != len(required):
            # Circular dependency detected — return what we have + remaining
            missing = required - set(order)
            order.extend(sorted(missing))

        return order

    def check_deps(self, skill_id: str, loaded_skills: set[str]) -> DependencyResult:
        """
        Check if a skill's dependencies are satisfied.
        
        Args:
            skill_id: Skill to check
            loaded_skills: Set of currently loaded skill IDs
            
        Returns:
            DependencyResult with status and details
        """
        required = self._graph.get(skill_id, [])
        optional = self._optional.get(skill_id, [])

        missing_required = [d for d in required if d not in loaded_skills]
        missing_optional = [d for d in optional if d not in loaded_skills]

        if missing_required:
            return DependencyResult(
                skill_id=skill_id,
                status="missing",
                missing_deps=missing_required,
                optional_deps=missing_optional,
                error=f"Missing required dependencies: {', '.join(missing_required)}"
            )

        if missing_optional:
            return DependencyResult(
                skill_id=skill_id,
                status="optional_missing",
                optional_deps=missing_optional,
                error=f"Optional dependencies not loaded: {', '.join(missing_optional)}"
            )

        return DependencyResult(
            skill_id=skill_id,
            status="ok",
            load_order=[skill_id]
        )
