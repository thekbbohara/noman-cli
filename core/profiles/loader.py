"""ProfileLoader: Loads and initializes profiles from configuration.

Handles:
- Loading profiles from TOML/YAML/JSON config
- Merging profile configs with defaults
- Resolving provider settings per profile
- Credential pool integration
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from core.profiles.profile import Profile, ProfileConfig

logger = logging.getLogger(__name__)


class ProfileLoader:
    """Loads and initializes profiles from various sources.

    Sources (in priority order):
    1. Environment variable NOMAN_PROFILE
    2. Active profile from ProfileManager index
    3. Default profile
    4. System-wide config file
    """

    def __init__(self, profiles_dir: Path | None = None) -> None:
        self._profiles_dir = profiles_dir or Path.home() / ".noman" / "profiles"
        self._profiles_dir.mkdir(parents=True, exist_ok=True)

    @property
    def profiles_dir(self) -> Path:
        """Get the profiles directory."""
        return self._profiles_dir

    # -- Loading --

    def load_from_env(self) -> Profile | None:
        """Load profile from NOMAN_PROFILE environment variable.

        Returns:
            Profile or None if not set.
        """
        profile_name = os.environ.get("NOMAN_PROFILE")
        if not profile_name:
            return None

        config_file = self._profiles_dir / profile_name / "config.json"
        if not config_file.exists():
            logger.warning(f"NOMAN_PROFILE={profile_name} but config not found")
            return None

        config = ProfileConfig.from_dict(json.loads(config_file.read_text()))
        profile = Profile(
            name=profile_name,
            config=config,
            base_dir=self._profiles_dir,
        )
        logger.info(f"Loaded profile from env: {profile_name}")
        return profile

    def load_from_file(self, config_path: Path) -> Profile:
        """Load profile from a config file.

        Args:
            config_path: Path to the config file.

        Returns:
            Profile.
        """
        config = ProfileConfig.from_dict(json.loads(config_file.read_text()))
        name = config_path.parent.name
        profile = Profile(
            name=name,
            config=config,
            base_dir=config_path.parent.parent,
        )
        logger.info(f"Loaded profile from file: {config_path}")
        return profile

    def load_system_config(self) -> Profile | None:
        """Load system-wide profile configuration.

        Returns:
            Profile from system config or None.
        """
        system_config = Path("/etc/noman/profiles.json")
        if not system_config.exists():
            # Also check ~/.config/noman/
            system_config = Path.home() / ".config" / "noman" / "profiles.json"

        if not system_config.exists():
            return None

        try:
            data = json.loads(system_config.read_text())
            default_profile = data.get("default_profile") or "default"

            profile_path = self._profiles_dir / default_profile / "config.json"
            if not profile_path.exists():
                return None

            return self.load_from_file(profile_path)
        except Exception as e:
            logger.warning(f"Failed to load system config: {e}")
            return None

    def load_default(self) -> Profile:
        """Load the default profile, creating it if necessary.

        Returns:
            Default Profile.
        """
        default_profile = self._profiles_dir / "default" / "config.json"
        if default_profile.exists():
            return self.load_from_file(default_profile)

        # Create default profile
        from core.profiles.manager import ProfileManager
        manager = ProfileManager(self._profiles_dir)
        import asyncio
        return asyncio.run(manager.create("default"))

    # -- Config Resolution --

    def resolve_provider_config(
        self,
        profile: Profile,
        provider_name: str | None = None,
    ) -> dict[str, Any]:
        """Resolve provider configuration for a profile.

        Merges profile-specific provider settings with defaults.

        Args:
            profile: Target profile.
            provider_name: Provider name. If None, uses default.

        Returns:
            Resolved provider configuration.
        """
        providers = profile.config.providers
        if not providers:
            return {}

        if provider_name is None:
            provider_name = profile.config.default_provider

        if isinstance(providers, dict):
            return providers.get(provider_name, {})
        elif isinstance(providers, list):
            return next((p for p in providers if p.get("id") == provider_name), {})

        return {}

    def merge_profiles(
        self,
        base_profile: Profile,
        override_profile: Profile,
    ) -> Profile:
        """Merge two profiles, with override taking precedence.

        Args:
            base_profile: Base profile to merge from.
            override_profile: Override profile (takes precedence).

        Returns:
            Merged Profile.
        """
        merged_config = ProfileConfig()

        # Start with base config
        merged_config.default_provider = base_profile.config.default_provider
        merged_config.model = base_profile.config.model
        merged_config.stt = base_profile.config.stt
        merged_config.tts = base_profile.config.tts
        merged_config.vision = base_profile.config.vision
        merged_config.image_gen = base_profile.config.image_gen
        merged_config.browser = base_profile.config.browser
        merged_config.delegation = base_profile.config.delegation
        merged_config.providers = base_profile.config.providers
        merged_config.custom = dict(base_profile.config.custom)

        # Apply overrides
        if override_profile.config.default_provider:
            merged_config.default_provider = override_profile.config.default_provider
        if override_profile.config.model:
            merged_config.model = override_profile.config.model
        if override_profile.config.stt:
            merged_config.stt = override_profile.config.stt
        if override_profile.config.tts:
            merged_config.tts = override_profile.config.tts
        if override_profile.config.vision:
            merged_config.vision = override_profile.config.vision
        if override_profile.config.image_gen:
            merged_config.image_gen = override_profile.config.image_gen
        if override_profile.config.browser:
            merged_config.browser = override_profile.config.browser
        if override_profile.config.delegation:
            merged_config.delegation = override_profile.config.delegation
        if override_profile.config.providers:
            merged_config.providers = override_profile.config.providers
        merged_config.custom.update(override_profile.config.custom)

        merged = Profile(
            name=f"{base_profile.name}+{override_profile.name}",
            config=merged_config,
            base_dir=self._profiles_dir,
        )
        return merged

    # -- Credential Pool Integration --

    def get_credential_env_vars(self, profile: Profile) -> dict[str, str]:
        """Get environment variables for credentials in a profile.

        Maps provider API keys to environment variables.

        Args:
            profile: Target profile.

        Returns:
            Dict of env var name -> value.
        """
        env_vars: dict[str, str] = {}
        providers = profile.config.providers

        if isinstance(providers, dict):
            for provider_name, provider_config in providers.items():
                if isinstance(provider_config, dict):
                    api_key = provider_config.get("api_key", "")
                    if api_key:
                        env_key = f"{provider_name.upper()}_API_KEY"
                        env_vars[env_key] = api_key
        elif isinstance(providers, list):
            for provider_config in providers:
                if isinstance(provider_config, dict):
                    api_key = provider_config.get("api_key", "")
                    if api_key:
                        provider_name = provider_config.get("id", "unknown")
                        env_key = f"{provider_name.upper()}_API_KEY"
                        env_vars[env_key] = api_key

        return env_vars

    def setup_profile_env(self, profile: Profile) -> dict[str, str]:
        """Set up environment for a profile.

        Args:
            profile: Target profile.

        Returns:
            Dict of environment variables to set.
        """
        env = {
            "NOMAN_PROFILE": profile.name,
            "NOMAN_PROFILE_DIR": str(self._profiles_dir / profile.name),
        }

        # Add credential env vars
        env.update(self.get_credential_env_vars(profile))

        return env
