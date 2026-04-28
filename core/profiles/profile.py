"""Profile: Isolated configuration and state per user/environment.

A Profile encapsulates:
- Isolated config (provider, model, settings)
- Session data (browser cookies, auth tokens)
- Skills and capabilities
- Memory store
- Wiki and knowledge base
"""

from __future__ import annotations

import copy
import json
import logging
import tarfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


@dataclass
class ProfileConfig:
    """Profile-specific configuration.

    Mirrors the TOML config structure for a single profile:
    - providers: Provider settings
    - default_provider: Default provider name
    - model: Model settings
    - stt: Speech-to-text settings
    - tts: Text-to-speech settings
    - vision: Vision settings
    - image_gen: Image generation settings
    - browser: Browser settings
    - delegation: Delegation settings
    """

    # Provider config
    providers: dict[str, Any] = field(default_factory=dict)
    default_provider: str = "default"

    # Model config
    model: dict[str, Any] = field(default_factory=lambda: {
        "max_tool_calls_per_turn": 10,
    })

    # Voice (STT/TTS)
    stt: dict[str, Any] = field(default_factory=lambda: {
        "enabled": False,
        "provider": "faster_whisper",
    })
    tts: dict[str, Any] = field(default_factory=lambda: {
        "enabled": False,
        "provider": "edge",
    })

    # Vision
    vision: dict[str, Any] = field(default_factory=lambda: {
        "default_provider": "openai",
        "providers": {},
    })

    # Image generation
    image_gen: dict[str, Any] = field(default_factory=lambda: {
        "default_provider": "fal",
        "default_aspect": "square",
        "enhance_prompts": True,
        "providers": {},
    })

    # Browser settings
    browser: dict[str, Any] = field(default_factory=lambda: {
        "default_mode": "headless",
        "default_browser": "chromium",
    })

    # Delegation settings
    delegation: dict[str, Any] = field(default_factory=lambda: {
        "model": "",
        "provider": "",
        "max_workers": 4,
    })

    # Custom profile settings
    custom: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        d: dict[str, Any] = {
            "default_provider": self.default_provider,
            "model": self.model,
            "stt": self.stt,
            "tts": self.tts,
            "vision": self.vision,
            "image_gen": self.image_gen,
            "browser": self.browser,
            "delegation": self.delegation,
            "custom": self.custom,
        }
        if self.providers:
            d["providers"] = self.providers
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProfileConfig:
        """Create ProfileConfig from dictionary."""
        config = cls()
        config.default_provider = data.get("default_provider", "default")
        config.model = data.get("model", config.model)
        config.stt = data.get("stt", config.stt)
        config.tts = data.get("tts", config.tts)
        config.vision = data.get("vision", config.vision)
        config.image_gen = data.get("image_gen", config.image_gen)
        config.browser = data.get("browser", config.browser)
        config.delegation = data.get("delegation", config.delegation)
        config.custom = data.get("custom", {})
        if "providers" in data:
            config.providers = data["providers"]
        return config


@dataclass
class Profile:
    """An isolated profile with its own config, sessions, skills, and memory.

    Profiles allow running multiple independent instances of noman-cli
    with different settings, credentials, and knowledge bases.

    Attributes:
        name: Profile name/identifier.
        config: Profile-specific configuration.
        base_dir: Base directory for profile data.
        created_at: Profile creation timestamp.
        active: Whether this profile is currently active.
        metadata: Additional metadata.
    """

    name: str
    config: ProfileConfig = field(default_factory=ProfileConfig)
    base_dir: Path = field(default_factory=lambda: Path.home() / ".noman" / "profiles")
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))
    active: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    # Internal state
    _sessions: dict[str, Any] = field(default_factory=dict)
    _skills: dict[str, Any] = field(default_factory=dict)
    _aliases: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)

    # -- Properties --

    @property
    def config_path(self) -> Path:
        """Get the config file path for this profile."""
        return self.base_dir / self.name / "config.json"

    @property
    def sessions_dir(self) -> Path:
        """Get the sessions directory."""
        return self.base_dir / self.name / "sessions"

    @property
    def skills_dir(self) -> Path:
        """Get the skills directory."""
        return self.base_dir / self.name / "skills"

    @property
    def memory_path(self) -> Path:
        """Get the memory database path."""
        return self.base_dir / self.name / "memory.db"

    @property
    def wiki_dir(self) -> Path:
        """Get the wiki directory."""
        return self.base_dir / self.name / "wiki"

    @property
    def browser_cache_dir(self) -> Path:
        """Get the browser cache directory."""
        return self.base_dir / self.name / "browser_cache"

    @property
    def alias_scripts_dir(self) -> Path:
        """Get the directory for profile alias scripts."""
        return self.base_dir / self.name / "aliases"

    # -- Config --

    def get_provider(self, name: str | None = None) -> dict[str, Any] | None:
        """Get a provider configuration.

        Args:
            name: Provider name. If None, returns default provider.

        Returns:
            Provider config dict or None.
        """
        providers = self.config.providers
        if not providers:
            return None

        if name is None:
            name = self.config.default_provider

        if isinstance(providers, dict):
            return providers.get(name)
        elif isinstance(providers, list):
            return next((p for p in providers if p.get("id") == name), None)
        return None

    def set_provider(self, name: str, config: dict[str, Any]) -> None:
        """Set a provider configuration.

        Args:
            name: Provider name.
            config: Provider configuration.
        """
        providers = self.config.providers
        if isinstance(providers, list):
            # Convert to dict for easier management
            d = {}
            for p in providers:
                if isinstance(p, dict):
                    d[p.get("id", "unknown")] = p
            providers = d
            self.config.providers = d

        if isinstance(providers, dict):
            providers[name] = config

    def update_config(self, **kwargs: Any) -> None:
        """Update profile configuration with keyword arguments.

        Args:
            **kwargs: Configuration keys and values to update.
        """
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
            else:
                self.config.custom[key] = value

    # -- Session Management --

    def save_session(self, session_id: str, data: dict[str, Any]) -> None:
        """Save a session to the profile's session store.

        Args:
            session_id: Session identifier.
            data: Session data to save.
        """
        session_dir = self.sessions_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "data.json").write_text(json.dumps(data, indent=2))
        self._sessions[session_id] = {
            "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "path": str(session_dir),
        }

    def load_session(self, session_id: str) -> dict[str, Any] | None:
        """Load a session from the profile's session store.

        Args:
            session_id: Session identifier.

        Returns:
            Session data or None if not found.
        """
        session_dir = self.sessions_dir / session_id
        data_file = session_dir / "data.json"
        if data_file.exists():
            return json.loads(data_file.read_text())
        return None

    def list_sessions(self) -> list[str]:
        """List all session IDs for this profile."""
        sessions_dir = self.sessions_dir
        if not sessions_dir.exists():
            return []
        return [d.name for d in sessions_dir.iterdir() if d.is_dir()]

    def delete_session(self, session_id: str) -> bool:
        """Delete a session.

        Args:
            session_id: Session identifier.

        Returns:
            True if deleted, False if not found.
        """
        session_dir = self.sessions_dir / session_id
        if session_dir.exists():
            import shutil
            shutil.rmtree(session_dir)
            self._sessions.pop(session_id, None)
            return True
        return False

    # -- Skills --

    def save_skill(self, skill_id: str, data: dict[str, Any]) -> None:
        """Save a skill to the profile's skills directory.

        Args:
            skill_id: Skill identifier.
            data: Skill data.
        """
        skill_dir = self.skills_dir / skill_id
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "skill.json").write_text(json.dumps(data, indent=2))
        self._skills[skill_id] = {
            "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "path": str(skill_dir),
        }

    def load_skill(self, skill_id: str) -> dict[str, Any] | None:
        """Load a skill.

        Args:
            skill_id: Skill identifier.

        Returns:
            Skill data or None.
        """
        skill_dir = self.skills_dir / skill_id
        data_file = skill_dir / "skill.json"
        if data_file.exists():
            return json.loads(data_file.read_text())
        return None

    def list_skills(self) -> list[str]:
        """List all skill IDs for this profile."""
        skills_dir = self.skills_dir
        if not skills_dir.exists():
            return []
        return [d.name for d in skills_dir.iterdir() if d.is_dir()]

    def delete_skill(self, skill_id: str) -> bool:
        """Delete a skill.

        Args:
            skill_id: Skill identifier.

        Returns:
            True if deleted, False if not found.
        """
        skill_dir = self.skills_dir / skill_id
        if skill_dir.exists():
            import shutil
            shutil.rmtree(skill_dir)
            self._skills.pop(skill_id, None)
            return True
        return False

    # -- Cloning --

    async def clone(
        self,
        new_name: str,
        clone_type: str = "full",
    ) -> Profile:
        """Clone this profile.

        Args:
            new_name: Name for the cloned profile.
            clone_type: Clone type - 'full', 'config-only', or 'skills-only'.

        Returns:
            New Profile instance.

        Raises:
            ValueError: If clone_type is invalid.
        """
        if clone_type not in ("full", "config-only", "skills-only"):
            raise ValueError(f"Invalid clone type: {clone_type}")

        # Create config copy
        new_config = copy.deepcopy(self.config)

        # Create new profile
        new_profile = Profile(
            name=new_name,
            config=new_config,
            base_dir=self.base_dir,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        )

        # Clone based on type
        if clone_type == "full":
            # Copy all directories
            await self._clone_directory(
                self.base_dir / self.name,
                self.base_dir / new_name,
            )
        elif clone_type == "config-only":
            # Copy only config
            if self.config_path.exists():
                (self.base_dir / new_name).mkdir(parents=True, exist_ok=True)
                new_profile.config_path.parent.mkdir(parents=True, exist_ok=True)
                import shutil
                shutil.copy2(self.config_path, new_profile.config_path)
        elif clone_type == "skills-only":
            # Copy only skills
            skills_dir = self.skills_dir
            if skills_dir.exists():
                new_skills_dir = new_profile.skills_dir
                new_skills_dir.mkdir(parents=True, exist_ok=True)
                import shutil
                for skill in skills_dir.iterdir():
                    if skill.is_dir():
                        shutil.copytree(skill, new_skills_dir / skill.name)

        logger.info(f"Profile '{self.name}' cloned to '{new_name}' (type: {clone_type})")
        return new_profile

    async def _clone_directory(self, src: Path, dst: Path) -> None:
        """Recursively copy a directory.

        Args:
            src: Source directory.
            dst: Destination directory.
        """
        import shutil
        dst.mkdir(parents=True, exist_ok=True)
        for item in src.iterdir():
            s = src / item.name
            d = dst / item.name
            if item.is_dir():
                await self._clone_directory(s, d)
            else:
                shutil.copy2(s, d)

    # -- Export/Import --

    async def export(self, path: Path) -> None:
        """Export the profile to a tar.gz archive.

        Args:
            path: Output path for the archive.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        profile_dir = self.base_dir / self.name
        if not profile_dir.exists():
            raise FileNotFoundError(f"Profile directory not found: {profile_dir}")

        with tarfile.open(str(path), "w:gz") as tar:
            tar.add(str(profile_dir), arcname=self.name)
        logger.info(f"Profile '{self.name}' exported to {path}")

    @classmethod
    async def import_profile(cls, archive_path: Path, base_dir: Path | None = None) -> Profile:
        """Import a profile from a tar.gz archive.

        Args:
            archive_path: Path to the archive file.
            base_dir: Base directory for profiles. Defaults to ~/.noman/profiles.

        Returns:
            New Profile instance.

        Raises:
            FileNotFoundError: If archive doesn't exist.
        """
        if base_dir is None:
            base_dir = Path.home() / ".noman" / "profiles"

        if not archive_path.exists():
            raise FileNotFoundError(f"Archive not found: {archive_path}")

        # Determine profile name from archive
        import tarfile
        with tarfile.open(str(archive_path), "r:gz") as tar:
            names = tar.getnames()
            # Extract profile name from archive structure
            profile_name = None
            for name in names:
                parts = name.split("/", 1)
                if len(parts) == 2:
                    profile_name = parts[0]
                    break
            if not profile_name:
                raise ValueError(f"Cannot determine profile name from archive: {archive_path}")

        # Extract to base directory
        base_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(str(archive_path), "r:gz") as tar:
            tar.extractall(str(base_dir))

        profile = cls(name=profile_name, base_dir=base_dir)
        logger.info(f"Profile '{profile_name}' imported from {archive_path}")
        return profile

    # -- Aliasing --

    def add_alias(self, alias_name: str) -> None:
        """Add an alias (wrapper script name) for this profile.

        Args:
            alias_name: Alias name (e.g., 'noman-dev').
        """
        if alias_name not in self._aliases:
            self._aliases.append(alias_name)
            self._create_alias_script(alias_name)

    def remove_alias(self, alias_name: str) -> None:
        """Remove an alias for this profile.

        Args:
            alias_name: Alias name to remove.
        """
        if alias_name in self._aliases:
            self._aliases.remove(alias_name)
            self._remove_alias_script(alias_name)

    @property
    def aliases(self) -> list[str]:
        """Get all aliases for this profile."""
        return list(self._aliases)

    def _create_alias_script(self, alias_name: str) -> None:
        """Create a wrapper script for this profile.

        Args:
            alias_name: Alias name for the script.
        """
        aliases_dir = self.alias_scripts_dir
        aliases_dir.mkdir(parents=True, exist_ok=True)

        script_path = aliases_dir / alias_name
        script_content = f"""#!/usr/bin/env bash
# noman profile alias: {self.name}
# Generated: {time.strftime("%Y-%m-%dT%H:%M:%S")}

export NOMAN_PROFILE="{self.name}"
export NOMAN_PROFILE_DIR="{self.base_dir / self.name}"

exec noman "$@"
"""
        script_path.write_text(script_content)
        script_path.chmod(0o755)
        logger.info(f"Created alias script: {script_path}")

    def _remove_alias_script(self, alias_name: str) -> None:
        """Remove a wrapper script.

        Args:
            alias_name: Alias name to remove.
        """
        aliases_dir = self.alias_scripts_dir
        script_path = aliases_dir / alias_name
        if script_path.exists():
            script_path.unlink()
            logger.info(f"Removed alias script: {script_path}")

    # -- Serialization --

    def to_dict(self) -> dict[str, Any]:
        """Serialize the profile to a dictionary."""
        return {
            "name": self.name,
            "config": self.config.to_dict(),
            "base_dir": str(self.base_dir),
            "created_at": self.created_at,
            "active": self.active,
            "metadata": self.metadata,
            "aliases": self._aliases,
            "sessions": dict(self._sessions),
            "skills": dict(self._skills),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Profile:
        """Create a Profile from a dictionary."""
        config = ProfileConfig.from_dict(data.get("config", {}))
        profile = cls(
            name=data["name"],
            config=config,
            base_dir=Path(data.get("base_dir", Path.home() / ".noman" / "profiles")),
            created_at=data.get("created_at", ""),
            active=data.get("active", False),
            metadata=data.get("metadata", {}),
        )
        profile._aliases = list(data.get("aliases", []))
        return profile

    def __repr__(self) -> str:
        return f"Profile(name={self.name!r}, active={self.active})"
