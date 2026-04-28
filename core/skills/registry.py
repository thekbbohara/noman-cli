"""SkillsRegistry: Local and remote skill registry.

Manages skill metadata, versions, integrity, and discovery
across local and remote registries.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

logger = logging.getLogger(__name__)


@dataclass
class SkillEntry:
    """A single skill entry in the registry.

    Attributes:
        name: Skill name (unique identifier).
        version: Current version (semver).
        description: Short description.
        author: Author name/identifier.
        tags: List of tags for categorization.
        keywords: Keywords for search.
        source: Source URL (GitHub, registry, etc.).
        integrity: Integrity hash (sha256).
        dependencies: List of required skill names.
        min_noman_version: Minimum noman-cli version required.
        installed_at: When it was installed.
        updated_at: Last update timestamp.
        active: Whether the skill is active.
        metadata: Additional metadata.
    """

    name: str
    version: str = "0.0.1"
    description: str = ""
    author: str = ""
    tags: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    source: str = ""
    integrity: str = ""
    dependencies: list[str] = field(default_factory=list)
    min_noman_version: str = ""
    installed_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))
    updated_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))
    active: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "tags": self.tags,
            "keywords": self.keywords,
            "source": self.source,
            "integrity": self.integrity,
            "dependencies": self.dependencies,
            "min_noman_version": self.min_noman_version,
            "installed_at": self.installed_at,
            "updated_at": self.updated_at,
            "active": self.active,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillEntry:
        """Create from dictionary."""
        return cls(
            name=data["name"],
            version=data.get("version", "0.0.1"),
            description=data.get("description", ""),
            author=data.get("author", ""),
            tags=data.get("tags", []),
            keywords=data.get("keywords", []),
            source=data.get("source", ""),
            integrity=data.get("integrity", ""),
            dependencies=data.get("dependencies", []),
            min_noman_version=data.get("min_noman_version", ""),
            installed_at=data.get("installed_at", ""),
            updated_at=data.get("updated_at", ""),
            active=data.get("active", True),
            metadata=data.get("metadata", {}),
        )

    @property
    def is_outdated(self) -> bool:
        """Check if the installed version differs from source version."""
        if not self.source or not self.integrity:
            return False
        return self.installed_at != self.updated_at


class SkillsRegistry:
    """Manages local and remote skill registries.

    Supports:
    - Local registry at ~/.noman/skills/index.json
    - Remote registry (noman-skills.dev or custom URL)
    - Skill discovery and indexing
    - Version tracking and update detection
    - Integrity verification
    """

    DEFAULT_REGISTRY_URL = "https://registry.noman-skills.dev"

    def __init__(
        self,
        local_dir: Path | None = None,
        remote_url: str | None = None,
    ) -> None:
        self._local_dir = local_dir or Path.home() / ".noman" / "skills"
        self._local_dir.mkdir(parents=True, exist_ok=True)
        self._remote_url = remote_url or self.DEFAULT_REGISTRY_URL
        self._local_index: dict[str, SkillEntry] = {}
        self._remote_index: dict[str, SkillEntry] = {}
        self._load_local_index()

    @property
    def local_index(self) -> dict[str, SkillEntry]:
        """Get the local registry index."""
        return dict(self._local_index)

    @property
    def remote_index(self) -> dict[str, SkillEntry]:
        """Get the remote registry index."""
        return dict(self._remote_index)

    # -- Local Registry --

    def register(self, skill: SkillEntry) -> None:
        """Register a skill in the local registry.

        Args:
            skill: SkillEntry to register.
        """
        self._local_index[skill.name] = skill
        self._save_local_index()
        logger.info(f"Registered skill: {skill.name} v{skill.version}")

    def unregister(self, name: str) -> bool:
        """Unregister a skill from the local registry.

        Args:
            name: Skill name.

        Returns:
            True if unregistered, False if not found.
        """
        if name in self._local_index:
            del self._local_index[name]
            self._save_local_index()
            logger.info(f"Unregistered skill: {name}")
            return True
        return False

    def get(self, name: str) -> SkillEntry | None:
        """Get a skill from the local registry.

        Args:
            name: Skill name.

        Returns:
            SkillEntry or None.
        """
        return self._local_index.get(name)

    def list_all(self, active_only: bool = True) -> list[SkillEntry]:
        """List all skills in the local registry.

        Args:
            active_only: Only return active skills.

        Returns:
            List of SkillEntry.
        """
        skills = list(self._local_index.values())
        if active_only:
            skills = [s for s in skills if s.active]
        return skills

    def search_local(self, query: str) -> list[SkillEntry]:
        """Search the local registry.

        Args:
            query: Search query.

        Returns:
            Matching SkillEntries.
        """
        query_lower = query.lower()
        results = []
        for skill in self._local_index.values():
            if not skill.active:
                continue
            # Match name, description, tags, keywords
            score = 0
            if query_lower in skill.name.lower():
                score += 10
            if query_lower in skill.description.lower():
                score += 5
            for tag in skill.tags:
                if query_lower in tag.lower():
                    score += 3
            for kw in skill.keywords:
                if query_lower in kw.lower():
                    score += 2
            if score > 0:
                results.append((score, skill))
        results.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in results]

    def _load_local_index(self) -> None:
        """Load the local registry index from disk."""
        index_file = self._local_dir / "index.json"
        if index_file.exists():
            try:
                data = json.loads(index_file.read_text())
                for name, entry_data in data.items():
                    self._local_index[name] = SkillEntry.from_dict(entry_data)
                logger.info(f"Loaded local registry: {len(self._local_index)} skills")
            except Exception as e:
                logger.warning(f"Failed to load local registry: {e}")

    def _save_local_index(self) -> None:
        """Save the local registry index to disk."""
        index_file = self._local_dir / "index.json"
        data = {name: s.to_dict() for name, s in self._local_index.items()}
        index_file.write_text(json.dumps(data, indent=2))
        logger.debug(f"Saved local registry: {len(data)} skills")

    # -- Remote Registry --

    async def fetch_remote_index(self) -> dict[str, SkillEntry]:
        """Fetch the remote registry index.

        Returns:
            Dict of skill name -> SkillEntry.
        """
        import httpx

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self._remote_url}/api/v1/index",
                    headers={"Accept": "application/json"},
                )
                response.raise_for_status()
                data = response.json()

                self._remote_index = {
                    name: SkillEntry.from_dict(entry)
                    for name, entry in data.items()
                }
                logger.info(f"Fetched remote index: {len(self._remote_index)} skills")
                return self._remote_index

        except Exception as e:
            logger.warning(f"Failed to fetch remote index: {e}")
            return {}

    async def browse_remote(
        self,
        query: str | None = None,
        tags: list[str] | None = None,
        limit: int = 50,
    ) -> list[SkillEntry]:
        """Browse skills from the remote registry.

        Args:
            query: Search query.
            tags: Filter by tags.
            limit: Maximum results.

        Returns:
            List of SkillEntry.
        """
        if not self._remote_index:
            await self.fetch_remote_index()

        results = list(self._remote_index.values())

        if query:
            query_lower = query.lower()
            results = [
                s for s in results
                if query_lower in s.name.lower()
                or query_lower in s.description.lower()
                or any(query_lower in t.lower() for t in s.tags)
            ]

        if tags:
            tag_set = set(tags)
            results = [s for s in results if tag_set.intersection(s.tags)]

        return results[:limit]

    async def install_from_remote(self, name: str) -> SkillEntry | None:
        """Install a skill from the remote registry.

        Args:
            name: Skill name.

        Returns:
            Installed SkillEntry or None.
        """
        if not self._remote_index:
            await self.fetch_remote_index()

        skill = self._remote_index.get(name)
        if not skill:
            logger.warning(f"Skill '{name}' not found in remote registry")
            return None

        # Download the skill
        import httpx
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self._remote_url}/api/v1/skills/{name}/install",
                    headers={"Accept": "application/json"},
                )
                response.raise_for_status()
                data = response.json()

                # Save skill
                skill_dir = self._local_dir / name
                skill_dir.mkdir(parents=True, exist_ok=True)
                (skill_dir / "skill.json").write_text(json.dumps(data, indent=2))

                # Register in local index
                skill.installed_at = time.strftime("%Y-%m-%dT%H:%M:%S")
                self.register(skill)

                logger.info(f"Installed skill '{name}' v{skill.version} from remote")
                return skill

        except Exception as e:
            logger.error(f"Failed to install skill '{name}' from remote: {e}")
            return None

    # -- Integrity --

    def verify_integrity(self, skill_name: str) -> bool:
        """Verify a skill's integrity against its recorded hash.

        Args:
            skill_name: Skill name.

        Returns:
            True if integrity verified.
        """
        skill = self.get(skill_name)
        if not skill or not skill.integrity:
            return True  # No integrity data to verify

        skill_dir = self._local_dir / skill_name
        if not skill_dir.exists():
            return False

        import hashlib
        computed_hashes: list[str] = []
        for file_path in skill_dir.rglob("*"):
            if file_path.is_file() and file_path.name != "index.json":
                h = hashlib.sha256(file_path.read_bytes()).hexdigest()
                computed_hashes.append(f"{file_path.relative_to(skill_dir)}:{h}")

        computed = hashlib.sha256("\n".join(sorted(computed_hashes)).encode()).hexdigest()
        return computed == skill.integrity

    def update_integrity(self, skill_name: str) -> bool:
        """Update the integrity hash for a skill.

        Args:
            skill_name: Skill name.

        Returns:
            True if integrity was updated.
        """
        skill = self.get(skill_name)
        if not skill:
            return False

        skill_dir = self._local_dir / skill_name
        if not skill_dir.exists():
            return False

        import hashlib
        computed_hashes: list[str] = []
        for file_path in skill_dir.rglob("*"):
            if file_path.is_file() and file_path.name != "index.json":
                h = hashlib.sha256(file_path.read_bytes()).hexdigest()
                computed_hashes.append(f"{file_path.relative_to(skill_dir)}:{h}")

        skill.integrity = hashlib.sha256("\n".join(sorted(computed_hashes)).encode()).hexdigest()
        skill.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._save_local_index()
        return True

    # -- Auto-update --

    def get_outdated(self) -> list[SkillEntry]:
        """Get all outdated skills.

        Returns:
            List of outdated SkillEntry.
        """
        if not self._remote_index:
            return []

        outdated = []
        for name, local_skill in self._local_index.items():
            remote_skill = self._remote_index.get(name)
            if remote_skill and remote_skill.version != local_skill.version:
                outdated.append(local_skill)
        return outdated

    async def auto_update(self) -> list[SkillEntry]:
        """Auto-update all outdated skills.

        Returns:
            List of updated skills.
        """
        await self.fetch_remote_index()
        outdated = self.get_outdated()
        updated = []

        for skill in outdated:
            result = await self.install_from_remote(skill.name)
            if result:
                updated.append(result)

        return updated

    # -- Serialization --

    def export_data(self) -> dict[str, Any]:
        """Export registry data."""
        return {
            "local": {name: s.to_dict() for name, s in self._local_index.items()},
            "remote": {name: s.to_dict() for name, s in self._remote_index.items()},
            "remote_url": self._remote_url,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillsRegistry:
        """Create registry from exported data."""
        remote_url = data.get("remote_url", cls.DEFAULT_REGISTRY_URL)
        registry = cls(remote_url=remote_url)

        for name, entry_data in data.get("local", {}).items():
            registry._local_index[name] = SkillEntry.from_dict(entry_data)
        for name, entry_data in data.get("remote", {}).items():
            registry._remote_index[name] = SkillEntry.from_dict(entry_data)

        return registry
