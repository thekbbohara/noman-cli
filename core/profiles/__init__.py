"""Profiles + credential pooling for multi-tenant noman-cli usage.

Provides isolated profile management with config, sessions, skills,
and memory per profile. Supports cloning, export/import, and aliasing.

Usage:
    from core.profiles import ProfileManager

    manager = ProfileManager()
    await manager.create("dev", model="gpt-4o")
    profile = await manager.use("dev")
    result = await profile.run_task("analyze this code")
"""

from __future__ import annotations

from core.profiles.profile import Profile, ProfileConfig
from core.profiles.manager import ProfileManager
from core.profiles.loader import ProfileLoader

__all__ = [
    "Profile",
    "ProfileConfig",
    "ProfileManager",
    "ProfileLoader",
]
