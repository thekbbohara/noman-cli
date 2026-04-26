#!/usr/bin/env python3
"""
Migration script for skill metadata system.

Initializes ~/.noman/skill_metadata.json with default metadata
for all skills in the catalog. Run once after deploying this system.

Usage:
    python -m core.selfimprove.migrate_skills
    # or
    noman-cli migrate-skills
"""

import json
from pathlib import Path

from core.tools.tools_catalog import SKILLS
from core.selfimprove.skill_metadata import SkillMetadata, SkillMetadataStore

METADATA_PATH = Path.home() / ".noman" / "skill_metadata.json"


def migrate():
    """Run the migration."""
    store = SkillMetadataStore()
    
    # Initialize metadata for all catalog skills
    for skill in SKILLS:
        meta = store.get(skill.name)
        if meta.loaded_count == 0:
            # Only initialize if not already tracked
            meta = SkillMetadata()
            meta.semantic_tags = _extract_tags(skill)
            meta.usage_categories = [skill.category] if skill.category else []
            store._data[skill.name] = meta
    
    # Write to disk
    store._dirty = True
    store.save()
    
    print(f"Migrated {len(SKILLS)} skills to metadata store")
    print(f"Metadata file: {METADATA_PATH}")
    
    # Show stats
    loaded = sum(1 for m in store._data.values() if m.loaded_count > 0)
    print(f"Already loaded: {loaded}")
    print(f"Never loaded: {len(SKILLS) - loaded}")


def _extract_tags(skill) -> list[str]:
    """Extract semantic tags from skill description."""
    desc = skill.description.lower()
    tags = []
    
    # Keywords from description
    keywords = {
        "spotify": "spotify", "play": "music", "music": "music",
        "search": "search", "download": "download", "gif": "gif",
        "video": "video", "animation": "animation", "image": "image",
        "git": "git", "github": "github", "repository": "git",
        "docker": "docker", "container": "docker",
        "mysql": "database", "postgres": "database", "database": "database",
        "test": "testing", "pytest": "testing", "qa": "testing",
        "code": "code-review", "review": "code-review",
        "deploy": "deployment", "deploy": "devops",
        "scrape": "scraping", "crawl": "scraping",
        "web": "web-automation", "browser": "web-automation",
        "email": "email", "mail": "email",
        "prompt": "prompting", "agent": "agent",
        "skill": "skill-management", "improve": "self-improvement",
    }
    
    for word, tag in keywords.items():
        if word in desc:
            tags.append(tag)
    
    # Category as tag
    if skill.category:
        tags.append(skill.category)
    
    return tags


if __name__ == "__main__":
    migrate()
