"""Skills Hub: Browse, install, search, and publish skills.

Provides a centralized skill registry system with:
- Remote registry (noman-skills.dev or custom)
- Local skill store
- BM25 + semantic skill search
- Skill installation with dependency resolution
- Skill publishing with integrity verification
- Auto-update for outdated skills
"""

from __future__ import annotations

from core.skills.hub import SkillsHub
from core.skills.search import SkillSearch
from core.skills.installer import SkillInstaller
from core.skills.publisher import SkillPublisher
from core.skills.registry import SkillsRegistry, SkillEntry

__all__ = [
    "SkillsHub",
    "SkillSearch",
    "SkillInstaller",
    "SkillPublisher",
    "SkillsRegistry",
    "SkillEntry",
]
