"""
Session-aware skill loader with token budget management.

This is the core orchestrator that:
1. Finds relevant skills for the current task
2. Resolves dependencies
3. Loads skills within token budget
4. Tracks usage for personalization
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .skill_index import SkillBM25Index, SkillEntry, build_skill_index
from .skill_semantic import SkillSemanticMatcher, SemanticMatchResult
from .skill_dependencies import SkillDependencyGraph, DependencyResult
from .skill_metadata import SkillMetadataStore, METADATA_PATH


@dataclass
class LoadedSkill:
    """A skill that has been loaded into context."""
    skill_id: str
    content: str
    token_count: int
    deps_satisfied: bool
    deps_missing: list[str] = field(default_factory=list)
    load_order_index: int = 0


@dataclass
class SkillLoadResult:
    """Result of skill loading."""
    loaded: list[LoadedSkill]
    errors: list[str] = field(default_factory=list)
    token_usage: int = 0
    budget_remaining: int = 0
    auto_loaded: list[str] = field(default_factory=list)
    skipped_low_relevance: list[str] = field(default_factory=list)
    skipped_budget: list[str] = field(default_factory=list)


class SkillTokenBudget:
    """
    Token budget manager for skill loading.
    
    Ensures skills don't exceed the token budget for the prompt.
    Gracefully degrades by picking highest-scoring skills only.
    """

    def __init__(self, budget: int = 4000):
        self.budget = budget
        self.used = 0
        self.remaining = budget

    def add(self, content: str) -> bool:
        """
        Add skill content to budget.
        Returns True if fits, False if over budget.
        """
        # Rough token estimate: ~4 chars per token
        tokens = len(content) // 4
        if self.used + tokens > self.budget:
            return False
        self.used += tokens
        self.remaining = self.budget - self.used
        return True

    def remaining_for(self, content: str) -> bool:
        """Check if content fits in remaining budget."""
        tokens = len(content) // 4
        return self.used + tokens <= self.budget


class SkillLoader:
    """
    Session-aware skill loader with relevance scoring.
    
    The killer feature: skills are loaded on-demand with semantic
    relevance, not dumped blindly at session start.
    """

    def __init__(self, budget: int = 4000):
        self.budget = budget
        self.index = build_skill_index()
        self.semantic = SkillSemanticMatcher(self.index)
        self.dependencies = SkillDependencyGraph()
        self.metadata = SkillMetadataStore()
        self._loaded_skills: dict[str, LoadedSkill] = {}
        self._load_dependencies()

    def _load_dependencies(self):
        """Build dependency graph from SKILL.md frontmatter."""
        # Register all skills from index
        for skill_id in self.index.get_all_ids():
            self.dependencies.add_skill(skill_id)

        # Parse SKILL.md files for dependency declarations
        skill_dir = Path.home() / ".hermes" / "skills"
        for skill_md in skill_dir.rglob("SKILL.md"):
            try:
                content = skill_md.read_text()
                name_match = __import__('re').search(
                    r'^\s*name:\s*(.+)$', content, __import__('re').MULTILINE
                )
                if not name_match:
                    continue
                name = name_match.group(1).strip().strip('"').strip("'")

                deps_match = __import__('re').search(
                    r'dependencies:\s*\n(?:\s*(?:required|optional):\s*\n)?(?:\s*[-*]\s*(.+)\n)*',
                    content, __import__('re').MULTILINE | __import__('re').DOTALL
                )
                if deps_match:
                    # Extract required and optional deps
                    required = []
                    optional = []
                    in_required = False
                    in_optional = False
                    for line in content.split('\n'):
                        stripped = line.strip()
                        if stripped == 'required:':
                            in_required = True
                            in_optional = False
                            continue
                        elif stripped == 'optional:':
                            in_required = False
                            in_optional = True
                            continue
                        elif stripped.startswith('prerequisites:') or stripped.startswith('---'):
                            in_required = False
                            in_optional = False
                            continue
                        if in_required and stripped.startswith('- '):
                            dep = stripped[2:].strip().strip('"').strip("'")
                            if dep:
                                required.append(dep)
                        if in_optional and stripped.startswith('- '):
                            dep = stripped[2:].strip().strip('"').strip("'")
                            if dep:
                                optional.append(dep)

                    if name in self.index.get_all_ids():
                        self.dependencies.add_skill(name, required, optional)
            except Exception:
                continue

    def match_skills(self, task_context: str, max_results: int = 10) -> list[dict]:
        """
        Find the most relevant skills for the current task.

        Combines BM25 lexical matching + semantic embedding scoring
        with personalization factors.

        Args:
            task_context: The current task description
            max_results: Maximum number of skills to return

        Returns:
            List of dicts with skill info and scores
        """
        # Step 1: BM25 search
        bm25_results = self.index.search(task_context, top_n=max_results * 2)
        bm25_map = {r.skill_id: r for r in bm25_results}

        # Step 2: Semantic search
        semantic_results = self.semantic.score_skills(task_context, top_n=max_results * 2)
        semantic_map = {r.skill_id: r for r in semantic_results}

        # Step 3: Combine scores (weighted sum)
        bm25_weight = 0.6
        semantic_weight = 0.4

        all_ids = set(bm25_map.keys()) | set(semantic_map.keys())
        combined = {}

        for sid in all_ids:
            bm25_score = bm25_map[sid].score if sid in bm25_map else 0.0
            semantic_score = semantic_map[sid].score if sid in semantic_map else 0.0

            # Don't normalize BM25 to 0-1 — use raw scores blended with semantic
            # BM25 scores are already corpus-relative; normalize semantic only
            max_sem = max(r.score for r in semantic_results) if semantic_results else 1.0
            norm_sem = semantic_score / max_sem if max_sem > 0 else 0.0

            combined_score = bm25_weight * bm25_score + semantic_weight * norm_sem

            # Personalization: boost effectiveness
            effectiveness = self.metadata.get_effectiveness(sid)
            combined_score *= (1.0 + effectiveness * 0.3)

            # Personalization: freshness boost
            freshness = self.metadata.get_freshness_boost(sid)
            combined_score *= (1.0 + freshness * 0.2)

            # Personalization: penalize discarded skills
            meta = self.metadata.get(sid)
            discard_penalty = 1.0 - (meta.discarded_count * 0.15)
            discard_penalty = max(0.1, discard_penalty)
            combined_score *= discard_penalty

            combined[sid] = combined_score

        # Step 4: Sort and format results
        sorted_skills = sorted(combined.items(), key=lambda x: x[1], reverse=True)[:max_results]

        results = []
        for sid, score in sorted_skills:
            entry = self.index.get_skill(sid)
            if not entry:
                continue

            # Get the actual SKILL.md content
            content = self._get_skill_content(sid)
            token_count = len(content) // 4 if content else 0

            # Check dependencies
            dep_result = self.dependencies.check_deps(sid, set(self._loaded_skills.keys()))
            deps_satisfied = dep_result.status in ("ok", "optional_missing")

            reason_parts = []
            if sid in bm25_map:
                reason_parts.append(f"bm25:{bm25_map[sid].score:.3f}")
            if sid in semantic_map:
                reason_parts.append(f"semantic:{semantic_map[sid].score:.3f}")
            reason = " | ".join(reason_parts) if reason_parts else "matched"

            results.append({
                "skill_id": sid,
                "name": entry.name,
                "description": entry.description,
                "category": entry.category,
                "score": round(score, 4),
                "token_count": token_count,
                "reason": reason,
                "deps_satisfied": deps_satisfied,
                "deps_missing": dep_result.missing_deps if not deps_satisfied else [],
                "effectiveness": effectiveness,
                "loaded_count": self.metadata.get_loaded_count(sid),
                "content": content,  # Pre-fetched content
            })

        return results

    def load_skill(self, skill_id: str) -> LoadedSkill | None:
        """
        Load a single skill into context.
        
        Checks dependencies first. Records usage metadata.

        Returns LoadedSkill if successful, None if failed.
        """
        # Check dependencies
        dep_result = self.dependencies.check_deps(skill_id, set(self._loaded_skills.keys()))
        if dep_result.status == "missing":
            return None

        # Get content
        content = self._get_skill_content(skill_id)
        if not content:
            return None

        # Check budget
        budget = SkillTokenBudget(self.budget - self._current_usage())
        if not budget.add(content):
            return None

        # Load it
        loaded = LoadedSkill(
            skill_id=skill_id,
            content=content,
            token_count=len(content) // 4,
            deps_satisfied=True,
            deps_missing=dep_result.missing_deps if dep_result.status == "optional_missing" else [],
        )
        self._loaded_skills[skill_id] = loaded

        # Record usage
        self.metadata.record_load(skill_id)

        return loaded

    def load_all_relevant(self, task_context: str, max_skills: int = 3,
                         max_tokens: int = 4000) -> SkillLoadResult:
        """
        Auto-load the most relevant skills for the current task.

        The key innovation: skills are loaded on-demand with relevance
        scoring, not dumped blindly.

        Args:
            task_context: The current task description
            max_skills: Maximum number of skills to auto-load
            max_tokens: Token budget for skill content

        Returns:
            SkillLoadResult with loaded skills, errors, and stats
        """
        # Find relevant skills
        candidates = self.match_skills(task_context, max_results=max_skills * 3)

        loaded = []
        errors = []
        auto_loaded = []
        skipped_low_relevance = []
        skipped_budget = []
        budget = SkillTokenBudget(max_tokens)

        for candidate in candidates:
            if len(loaded) >= max_skills:
                break

            sid = candidate["skill_id"]

            # Skip already loaded
            if sid in self._loaded_skills:
                continue

            # Skip if deps not satisfied
            if not candidate["deps_satisfied"]:
                errors.append(f"Skill '{sid}': {', '.join(candidate['deps_missing'])}")
                continue

            # Skip low relevance (< 0.3)
            if candidate["score"] < 0.3:
                skipped_low_relevance.append(sid)
                continue

            # Skip if doesn't fit budget
            if not budget.add(candidate["content"] or ""):
                skipped_budget.append(sid)
                continue

            # Load it
            result = self.load_skill(sid)
            if result:
                loaded.append(result)
                auto_loaded.append(sid)
            else:
                errors.append(f"Failed to load '{sid}'")

        # Track session
        self._current_usage = budget.used

        return SkillLoadResult(
            loaded=loaded,
            errors=errors,
            token_usage=budget.used,
            budget_remaining=budget.remaining,
            auto_loaded=auto_loaded,
            skipped_low_relevance=skipped_low_relevance,
            skipped_budget=skipped_budget,
        )

    def load_skill_by_name(self, name: str) -> str:
        """
        Load a skill by name. Returns content or error message.
        Replacement for skill_view.
        """
        # Find the skill in the index
        entry = self.index.get_skill(name)
        if not entry:
            # Try partial match
            for sid in self.index.get_all_ids():
                if name.lower() in sid.lower() or name.lower() in entry.name.lower():
                    entry = self.index.get_skill(sid)
                    break

        if not entry:
            return f"Skill '{name}' not found"

        # Check dependencies
        dep_result = self.dependencies.check_deps(name, set(self._loaded_skills.keys()))
        if dep_result.status == "missing":
            missing = dep_result.missing_deps
            dep_names = ", ".join(missing)
            return (
                f"Skill '{name}' has missing required dependencies: {dep_names}\n"
                f"→ Load these first: {', '.join(f'skill_load({d})' for d in missing)}"
            )

        # Get content
        content = self._get_skill_content(name)
        if not content:
            return f"Skill '{name}' content not found"

        # Load it
        loaded = self.load_skill(name)
        if not loaded:
            return f"Failed to load skill '{name}' (budget exceeded)"

        # Record session tracking
        self._loaded_skills[name] = loaded

        # Format output
        output_lines = []
        output_lines.append(f"=== Skill: {entry.name} ===")
        if entry.category:
            output_lines.append(f"Category: {entry.category}")
        if entry.description:
            output_lines.append(f"Description: {entry.description}")
        if dep_result.status == "optional_missing":
            output_lines.append(
                f"Note: optional dependencies not loaded: {', '.join(dep_result.optional_deps)}"
            )
        output_lines.append("")
        output_lines.append(content)
        return "\n".join(output_lines)

    def format_match_results(self, candidates: list[dict]) -> str:
        """Format match results for display to the agent."""
        if not candidates:
            return "No relevant skills found for this task."

        lines = [f"Found {len(candidates)} relevant skill(s):"]
        lines.append("")

        for i, c in enumerate(candidates, 1):
            status_icon = "✓" if c["deps_satisfied"] else "✗"
            lines.append(f"  [{i}] {status_icon} {c['name']}")
            lines.append(f"      Score: {c['score']:.3f} | "
                        f"Tokens: {c['token_count']} | "
                        f"Effectiveness: {c['effectiveness']:.2f}")
            if c['description']:
                lines.append(f"      {c['description'][:80]}")
            if not c['deps_satisfied']:
                lines.append(f"      ⚠ Missing: {', '.join(c['deps_missing'])}")
            lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_skill_content(self, skill_id: str) -> str | None:
        """Get the SKILL.md content for a skill."""
        entry = self.index.get_skill(skill_id)
        if not entry:
            return None

        # Check if already loaded
        loaded = self._loaded_skills.get(skill_id)
        if loaded:
            return loaded.content

        # Try SKILL.md on disk
        if entry.file_path:
            path = Path(entry.file_path)
            if path.exists():
                return path.read_text()

        # Try ~/.hermes/skills/<skill_id>/SKILL.md
        home_skill_dir = Path.home() / ".hermes" / "skills"
        alt_path = home_skill_dir / skill_id / "SKILL.md"
        if alt_path.exists():
            return alt_path.read_text()

        return None

    def _current_usage(self) -> int:
        """Get current token usage from loaded skills."""
        return sum(s.token_count for s in self._loaded_skills.values())

    def expire_session_skills(self, hours: float = 2.0):
        """Expire skills that haven't been used recently."""
        now = time.time()
        threshold = now - (hours * 3600)
        to_expire = []

        for sid, loaded in self._loaded_skills.items():
            meta = self.metadata.get(sid)
            if meta.last_loaded < threshold:
                to_expire.append(sid)

        for sid in to_expire:
            # Record session end
            self.metadata.record_session_end(sid, 0)
            del self._loaded_skills[sid]

    def save(self):
        """Save all metadata."""
        self.metadata.save()


# Singleton instance for module-level access
_loader_instance: Optional[SkillLoader] = None


def get_skill_loader(budget: int = 4000) -> SkillLoader:
    """Get or create the global skill loader instance."""
    global _loader_instance
    if _loader_instance is None:
        _loader_instance = SkillLoader(budget=budget)
    return _loader_instance
