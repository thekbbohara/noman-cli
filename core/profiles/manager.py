"""ProfileManager: Manages profile lifecycle (create, list, use, delete, etc.).

Provides CRUD operations for profiles, active profile tracking,
and CLI integration.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from core.profiles.profile import Profile, ProfileConfig

logger = logging.getLogger(__name__)

PROFILES_INDEX_FILE = ".profiles_index.json"


class ProfileManager:
    """Manages profiles: create, list, use, delete, show, export, import.

    Maintains an index of all profiles at ~/.noman/profiles/.profiles_index.json
    and provides a unified interface for profile operations.

    Example:
        manager = ProfileManager()
        await manager.create("dev", model="gpt-4o")
        await manager.use("dev")
        profile = await manager.current()
        profiles = await manager.list()
        await manager.delete("dev")
    """

    def __init__(self, profiles_dir: Path | None = None) -> None:
        self._profiles_dir = profiles_dir or Path.home() / ".noman" / "profiles"
        self._profiles_dir.mkdir(parents=True, exist_ok=True)
        self._current_profile: Profile | None = None
        self._index_path = self._profiles_dir / PROFILES_INDEX_FILE

    @property
    def current_profile(self) -> Profile | None:
        """Get the currently active profile."""
        return self._current_profile

    # -- CRUD Operations --

    async def create(
        self,
        name: str,
        config: dict[str, Any] | None = None,
        model: str | None = None,
        provider: str | None = None,
    ) -> Profile:
        """Create a new profile.

        Args:
            name: Profile name (must be unique, lowercase alphanumeric + hyphens).
            config: Profile configuration. If None, uses defaults.
            model: Default model name.
            provider: Default provider name.

        Returns:
            The created Profile.

        Raises:
            ValueError: If a profile with this name already exists.
        """
        profile_dir = self._profiles_dir / name
        if profile_dir.exists():
            raise ValueError(f"Profile '{name}' already exists")

        # Validate name
        import re
        if not re.match(r'^[a-z][a-z0-9_-]*$', name):
            raise ValueError(
                f"Invalid profile name '{name}'. Must start with a lowercase "
                "letter and contain only lowercase letters, numbers, underscores, and hyphens."
            )

        # Create config
        profile_config = ProfileConfig()
        if model:
            profile_config.model = {"model_name": model, "max_tool_calls_per_turn": 10}
        if provider:
            profile_config.default_provider = provider
            if "providers" not in profile_config.providers:
                profile_config.providers = {}
            profile_config.providers[provider] = {"type": provider, "model": model or "gpt-4o"}

        profile = Profile(
            name=name,
            config=profile_config,
            base_dir=self._profiles_dir,
        )

        # Save config
        profile.config_path.parent.mkdir(parents=True, exist_ok=True)
        profile.config_path.write_text(json.dumps(profile.config.to_dict(), indent=2))

        # Create required directories
        profile.sessions_dir.mkdir(parents=True, exist_ok=True)
        profile.skills_dir.mkdir(parents=True, exist_ok=True)
        profile.wiki_dir.mkdir(parents=True, exist_ok=True)
        profile.browser_cache_dir.mkdir(parents=True, exist_ok=True)

        # Update index
        await self._update_index(name, "created")

        self._current_profile = profile
        logger.info(f"Profile '{name}' created")
        return profile

    async def delete(self, name: str) -> bool:
        """Delete a profile and all its data.

        Args:
            name: Profile name.

        Returns:
            True if deleted, False if not found.
        """
        profile = await self.get(name)
        if not profile:
            return False

        import shutil
        profile_dir = self._profiles_dir / name
        if profile_dir.exists():
            shutil.rmtree(profile_dir)

        # Update index
        await self._update_index(name, "deleted")

        # Clear current profile if it was the active one
        if self._current_profile and self._current_profile.name == name:
            self._current_profile = None

        logger.info(f"Profile '{name}' deleted")
        return True

    async def get(self, name: str) -> Profile | None:
        """Get a profile by name.

        Args:
            name: Profile name.

        Returns:
            Profile or None if not found.
        """
        profile_dir = self._profiles_dir / name
        config_file = profile_dir / "config.json"

        if not config_file.exists():
            return None

        config = ProfileConfig.from_dict(json.loads(config_file.read_text()))
        profile = Profile(
            name=name,
            config=config,
            base_dir=self._profiles_dir,
        )
        return profile

    async def list_profiles(self) -> list[dict[str, Any]]:
        """List all profiles with their status.

        Returns:
            List of profile info dicts.
        """
        profiles = []
        index = await self._load_index()

        for name, info in index.items():
            profile_dir = self._profiles_dir / name
            config_file = profile_dir / "config.json"

            profile_info: dict[str, Any] = {
                "name": name,
                "active": self._current_profile and self._current_profile.name == name,
                "created_at": info.get("created_at", ""),
            }

            # Add model info if available
            if config_file.exists():
                try:
                    config = json.loads(config_file.read_text())
                    model = config.get("model", {}).get("model_name", "default")
                    provider = config.get("default_provider", "default")
                    profile_info["model"] = model
                    profile_info["provider"] = provider
                except Exception:
                    pass

            profiles.append(profile_info)

        return profiles

    async def use(self, name: str) -> Profile:
        """Set a profile as the active one.

        Args:
            name: Profile name.

        Returns:
            The activated Profile.

        Raises:
            ValueError: If the profile doesn't exist.
        """
        profile = await self.get(name)
        if not profile:
            raise ValueError(f"Profile '{name}' not found")

        # Deactivate current profile
        if self._current_profile:
            self._current_profile.active = False

        # Activate new profile
        profile.active = True
        self._current_profile = profile

        # Update index
        await self._update_index(name, "activated")

        logger.info(f"Profile '{name}' activated")
        return profile

    async def show(self, name: str | None = None) -> dict[str, Any]:
        """Show profile details.

        Args:
            name: Profile name. If None, shows current profile.

        Returns:
            Profile details dict.
        """
        profile_name = name or (self._current_profile.name if self._current_profile else None)
        if not profile_name:
            return {"error": "No active profile and no name provided"}

        profile = await self.get(profile_name)
        if not profile:
            return {"error": f"Profile '{profile_name}' not found"}

        return {
            "name": profile.name,
            "active": profile.active,
            "config": profile.config.to_dict(),
            "created_at": profile.created_at,
            "sessions": profile.list_sessions(),
            "skills": profile.list_skills(),
            "aliases": profile.aliases,
            "metadata": profile.metadata,
        }

    # -- Export/Import --

    async def export_profile(self, name: str, output_path: Path) -> None:
        """Export a profile to a tar.gz archive.

        Args:
            name: Profile name.
            output_path: Output path for the archive.
        """
        profile = await self.get(name)
        if not profile:
            raise ValueError(f"Profile '{name}' not found")

        await profile.export(output_path)

    async def import_profile(self, archive_path: Path) -> Profile:
        """Import a profile from a tar.gz archive.

        Args:
            archive_path: Path to the archive file.

        Returns:
            Imported Profile.
        """
        from core.profiles.profile import Profile
        return await Profile.import_profile(archive_path, self._profiles_dir)

    # -- Alias Management --

    async def create_alias(self, profile_name: str, alias_name: str) -> None:
        """Create an alias script for a profile.

        Args:
            profile_name: Profile name.
            alias_name: Alias name (e.g., 'noman-dev').
        """
        profile = await self.get(profile_name)
        if not profile:
            raise ValueError(f"Profile '{profile_name}' not found")

        profile.add_alias(alias_name)

    async def remove_alias(self, profile_name: str, alias_name: str) -> None:
        """Remove an alias for a profile.

        Args:
            profile_name: Profile name.
            alias_name: Alias name to remove.
        """
        profile = await self.get(profile_name)
        if not profile:
            raise ValueError(f"Profile '{profile_name}' not found")

        profile.remove_alias(alias_name)

    async def rename(self, old_name: str, new_name: str) -> Profile:
        """Rename a profile.

        Args:
            old_name: Current profile name.
            new_name: New profile name.

        Returns:
            Renamed Profile.

        Raises:
            ValueError: If old profile doesn't exist or new name is taken.
        """
        profile = await self.get(old_name)
        if not profile:
            raise ValueError(f"Profile '{old_name}' not found")

        new_dir = self._profiles_dir / new_name
        if new_dir.exists():
            raise ValueError(f"Profile '{new_name}' already exists")

        import re
        if not re.match(r'^[a-z][a-z0-9_-]*$', new_name):
            raise ValueError(f"Invalid profile name '{new_name}'")

        # Move directory
        old_dir = self._profiles_dir / old_name
        old_dir.rename(new_dir)

        # Update profile name and config
        profile.name = new_name
        profile.config_path.parent.mkdir(parents=True, exist_ok=True)
        profile.config_path.write_text(json.dumps(profile.config.to_dict(), indent=2))

        # Update index
        await self._update_index(old_name, "renamed", new_name)

        logger.info(f"Profile '{old_name}' renamed to '{new_name}'")
        return profile

    # -- Index Management --

    async def _load_index(self) -> dict[str, Any]:
        """Load the profiles index from disk.

        Returns:
            Index dictionary.
        """
        if self._index_path.exists():
            try:
                return json.loads(self._index_path.read_text())
            except Exception:
                pass
        return {}

    async def _update_index(self, name: str, action: str, new_name: str | None = None) -> None:
        """Update the profiles index.

        Args:
            name: Profile name that was modified.
            action: Action performed (created, deleted, activated, renamed).
            new_name: New name if the action was rename.
        """
        index = await self._load_index()

        if action == "created":
            index[name] = {
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "status": "active",
            }
        elif action == "deleted":
            index.pop(name, None)
        elif action == "activated":
            if name in index:
                index[name]["activated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        elif action == "renamed":
            if name in index:
                del index[name]
            if new_name:
                index[new_name] = index.get(name, {})
                index[new_name]["renamed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        self._index_path.write_text(json.dumps(index, indent=2))

    # -- Utility --

    async def get_current_or_default(self) -> Profile:
        """Get the current profile or create/use a default one.

        Returns:
            Active Profile.
        """
        if self._current_profile:
            return self._current_profile

        # Check for default profile
        default_name = "default"
        profile = await self.get(default_name)
        if profile:
            await self.use(default_name)
            return profile

        # Create default profile
        profile = await self.create(default_name)
        await self.use(default_name)
        return profile
