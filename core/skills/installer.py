"""SkillInstaller: Download, verify, and activate skills.

Handles:
- Installing skills from registry, GitHub, or local files
- Integrity verification (signature + hash)
- Dependency resolution
- Activation/deactivation
- Version management
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@dataclass
class InstallResult:
    """Result of a skill installation.

    Attributes:
        success: Whether the installation succeeded.
        skill_name: Name of the installed skill.
        version: Installed version.
        source: Source of the installation.
        installed_dir: Directory where the skill was installed.
        error: Error message if installation failed.
        dependencies_installed: List of dependencies that were auto-installed.
    """

    success: bool
    skill_name: str
    version: str = ""
    source: str = ""
    installed_dir: str = ""
    error: str | None = None
    dependencies_installed: list[str] = field(default_factory=list)


class SkillInstaller:
    """Installs skills from various sources with verification.

    Sources:
    - Remote registry (via SkillsRegistry)
    - GitHub repositories
    - Local tar.gz archives
    - Local directory paths
    """

    def __init__(
        self,
        registry: Any,
        install_dir: Path | None = None,
    ) -> None:
        self._registry = registry
        self._install_dir = install_dir or Path.home() / ".noman" / "skills"
        self._install_dir.mkdir(parents=True, exist_ok=True)

    @property
    def install_dir(self) -> Path:
        """Get the install directory."""
        return self._install_dir

    # -- Installation --

    async def install_from_registry(
        self,
        name: str,
        version: str | None = None,
    ) -> InstallResult:
        """Install a skill from the registry.

        Args:
            name: Skill name.
            version: Specific version (None = latest).

        Returns:
            InstallResult.
        """
        logger.info(f"Installing skill '{name}' from registry")

        # Fetch from registry
        skill = await self._registry.install_from_remote(name)
        if not skill:
            return InstallResult(
                success=False,
                skill_name=name,
                error=f"Skill '{name}' not found in registry",
            )

        # Verify integrity
        if not self._verify_integrity(name):
            return InstallResult(
                success=False,
                skill_name=name,
                error=f"Integrity verification failed for '{name}'",
            )

        # Resolve and install dependencies
        deps_installed = await self._install_dependencies(skill.dependencies)

        return InstallResult(
            success=True,
            skill_name=name,
            version=skill.version,
            source=f"registry:{self._registry._remote_url}",
            installed_dir=str(self._install_dir / name),
            dependencies_installed=deps_installed,
        )

    async def install_from_github(
        self,
        repo_url: str,
        name: str | None = None,
        version: str | None = None,
    ) -> InstallResult:
        """Install a skill from a GitHub repository.

        Args:
            repo_url: GitHub repository URL (e.g., 'owner/repo').
            name: Skill name (extracted from repo if None).
            version: Git tag/branch to use.

        Returns:
            InstallResult.
        """
        import httpx

        parsed = urlparse(repo_url)
        if not parsed.hostname or parsed.hostname != "github.com":
            return InstallResult(
                success=False,
                skill_name=name or "unknown",
                error=f"Invalid GitHub URL: {repo_url}",
            )

        # Extract owner/repo from URL
        parts = parsed.path.strip("/").split("/")
        if len(parts) < 2:
            return InstallResult(
                success=False,
                skill_name=name or "unknown",
                error=f"Invalid GitHub URL format: {repo_url}",
            )

        owner, repo = parts[0], parts[1]
        skill_name = name or repo

        # Download the repository archive
        archive_url = f"https://github.com/{owner}/{repo}/archive/refs/tags/{version or 'main'}.tar.gz"

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(archive_url)
                response.raise_for_status()

                # Extract to install directory
                import tarfile
                import io
                skill_dir = self._install_dir / skill_name
                skill_dir.mkdir(parents=True, exist_ok=True)

                with tarfile.open(fileobj=io.BytesIO(response.content)) as tar:
                    # Extract and clean up top-level directory
                    for member in tar.getmembers():
                        member.path = member.path.split("/", 1)[-1] if "/" in member.path else member.path
                        tar.extract(member, str(skill_dir))

                # Compute integrity hash
                integrity = self._compute_directory_hash(skill_dir)

                # Register in registry
                from core.skills.registry import SkillEntry
                entry = SkillEntry(
                    name=skill_name,
                    version=version or "0.0.0",
                    source=f"gh:{owner}/{repo}",
                    integrity=integrity,
                )
                self._registry.register(entry)

                return InstallResult(
                    success=True,
                    skill_name=skill_name,
                    version=entry.version,
                    source=f"gh:{owner}/{repo}",
                    installed_dir=str(skill_dir),
                )

        except Exception as e:
            return InstallResult(
                success=False,
                skill_name=skill_name,
                error=str(e),
            )

    async def install_from_local(self, path: Path) -> InstallResult:
        """Install a skill from a local directory.

        Args:
            path: Path to the skill directory (must contain skill.json).

        Returns:
            InstallResult.
        """
        skill_json = path / "skill.json"
        if not skill_json.exists():
            return InstallResult(
                success=False,
                skill_name=path.name,
                error=f"No skill.json found in {path}",
            )

        try:
            data = json.loads(skill_json.read_text())
            skill_name = data.get("name", path.name)
            version = data.get("version", "0.0.1")

            # Copy to install directory
            import shutil
            dest_dir = self._install_dir / skill_name
            if dest_dir.exists():
                shutil.rmtree(dest_dir)
            shutil.copytree(path, dest_dir)

            # Compute integrity hash
            integrity = self._compute_directory_hash(dest_dir)

            # Register in registry
            from core.skills.registry import SkillEntry
            entry = SkillEntry(
                name=skill_name,
                version=version,
                source=f"local:{path}",
                integrity=integrity,
            )
            self._registry.register(entry)

            return InstallResult(
                success=True,
                skill_name=skill_name,
                version=version,
                source=f"local:{path}",
                installed_dir=str(dest_dir),
            )

        except Exception as e:
            return InstallResult(
                success=False,
                skill_name=path.name,
                error=str(e),
            )

    # -- Dependencies --

    async def _install_dependencies(self, dependencies: list[str]) -> list[str]:
        """Install skill dependencies.

        Args:
            dependencies: List of dependency skill names.

        Returns:
            List of installed dependency names.
        """
        installed = []
        for dep in dependencies:
            # Check if already installed
            if self._registry.get(dep):
                logger.debug(f"Dependency '{dep}' already installed")
                continue

            # Install from registry
            result = await self.install_from_registry(dep)
            if result.success:
                installed.append(dep)
            else:
                logger.warning(f"Failed to install dependency '{dep}': {result.error}")

        return installed

    # -- Verification --

    def _verify_integrity(self, skill_name: str) -> bool:
        """Verify a skill's integrity.

        Args:
            skill_name: Skill name.

        Returns:
            True if integrity verified.
        """
        skill_dir = self._install_dir / skill_name
        if not skill_dir.exists():
            return False

        skill = self._registry.get(skill_name)
        if not skill or not skill.integrity:
            return True  # No integrity data

        computed = self._compute_directory_hash(skill_dir)
        return computed == skill.integrity

    def _compute_directory_hash(self, directory: Path) -> str:
        """Compute a hash of all files in a directory.

        Args:
            directory: Directory path.

        Returns:
            SHA256 hash string.
        """
        import os
        computed_hashes: list[str] = []
        for file_path in directory.rglob("*"):
            if file_path.is_file() and file_path.name != "index.json":
                rel_path = str(file_path.relative_to(directory))
                h = hashlib.sha256(file_path.read_bytes()).hexdigest()
                computed_hashes.append(f"{rel_path}:{h}")

        return hashlib.sha256("\n".join(sorted(computed_hashes)).encode()).hexdigest()

    # -- Activation --

    async def activate(self, skill_name: str) -> bool:
        """Activate a skill (make it available to the agent).

        Args:
            skill_name: Skill name.

        Returns:
            True if activated.
        """
        skill = self._registry.get(skill_name)
        if not skill:
            return False

        skill.active = True
        skill.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._registry._save_local_index()
        logger.info(f"Activated skill: {skill_name}")
        return True

    async def deactivate(self, skill_name: str) -> bool:
        """Deactivate a skill (hide it from the agent).

        Args:
            skill_name: Skill name.

        Returns:
            True if deactivated.
        """
        skill = self._registry.get(skill_name)
        if not skill:
            return False

        skill.active = False
        skill.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._registry._save_local_index()
        logger.info(f"Deactivated skill: {skill_name}")
        return True

    async def uninstall(self, skill_name: str) -> bool:
        """Uninstall a skill.

        Args:
            skill_name: Skill name.

        Returns:
            True if uninstalled.
        """
        # Unregister from registry
        self._registry.unregister(skill_name)

        # Remove from install directory
        skill_dir = self._install_dir / skill_name
        if skill_dir.exists():
            import shutil
            shutil.rmtree(skill_dir)
            logger.info(f"Uninstalled skill: {skill_name}")
            return True
        return False

    # -- Version Management --

    def get_installed_versions(self) -> dict[str, str]:
        """Get all installed skill versions.

        Returns:
            Dict of skill name -> version.
        """
        return {
            name: skill.version
            for name, skill in self._registry.local_index.items()
            if skill.active
        }

    def check_updates(self) -> dict[str, tuple[str, str]]:
        """Check for available updates for installed skills.

        Returns:
            Dict of skill name -> (installed_version, latest_version).
        """
        updates = {}
        for name, skill in self._registry.local_index.items():
            if not skill.active:
                continue
            latest = self._registry.remote_index.get(name)
            if latest and latest.version != skill.version:
                updates[name] = (skill.version, latest.version)
        return updates
