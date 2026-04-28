"""Integration tests for skills hub."""

import pytest


async def test_skills_hub():
    """Test SkillsHub."""
    from core.skills.hub import SkillsHub
    hub = SkillsHub()
    assert hub is not None


async def test_skill_search():
    """Test SkillSearch."""
    from core.skills.search import SkillSearch
    search = SkillSearch()
    assert search is not None


async def test_skill_installer():
    """Test SkillInstaller."""
    from core.skills.installer import SkillInstaller
    installer = SkillInstaller()
    assert installer is not None


async def test_skill_registry():
    """Test SkillsRegistry."""
    from core.skills.registry import SkillsRegistry
    registry = SkillsRegistry()
    assert registry is not None
