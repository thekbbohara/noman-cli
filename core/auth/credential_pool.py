"""Credential pooling for API key management across providers."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

AUTH_DIR = Path.home() / ".noman"
AUTH_FILE = AUTH_DIR / "auth.json"


@dataclass
class Credential:
    """A single API credential (API key)."""

    provider: str
    key: str
    id: str = ""
    label: str = ""
    created_at: str = ""
    last_used: str = ""
    usage_count: int = 0
    is_active: bool = True

    def __post_init__(self) -> None:
        if not self.id:
            self.id = uuid4().hex[:12]
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.label:
            self.label = f"key-{self.id[:6]}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "provider": self.provider,
            "label": self.label,
            "key": self.key,
            "created_at": self.created_at,
            "last_used": self.last_used,
            "usage_count": self.usage_count,
            "is_active": self.is_active,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Credential":
        return cls(**data)


class CredentialStore:
    """SQLite-backed storage for API credentials.

    Credentials are persisted to ~/.noman/auth.json as a JSON array.
    Each provider can have multiple credentials for failover/rotation.
    """

    def __init__(self, auth_file: Path | None = None) -> None:
        self._auth_file = auth_file or AUTH_FILE
        self._ensure_auth_dir()
        self._credentials: list[Credential] = []
        self._load()

    def _ensure_auth_dir(self) -> None:
        self._auth_file.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> None:
        """Load credentials from auth file."""
        if self._auth_file.exists():
            try:
                data = json.loads(self._auth_file.read_text())
                self._credentials = [Credential.from_dict(c) for c in data]
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                logger.warning(f"Failed to load auth file: {e}. Starting fresh.")
                self._credentials = []
        else:
            self._credentials = []

    def _save(self) -> None:
        """Save credentials to auth file."""
        data = [c.to_dict() for c in self._credentials]
        self._auth_file.parent.mkdir(parents=True, exist_ok=True)
        self._auth_file.write_text(json.dumps(data, indent=2))

    def add_credential(self, provider: str, key: str, label: str = "") -> Credential:
        """Add a new credential for a provider."""
        cred = Credential(provider=provider, key=key, label=label)
        self._credentials.append(cred)
        self._save()
        logger.info(f"Added credential for '{provider}' ({cred.id})")
        return cred

    def remove_credential(self, provider: str, credential_id: str | None = None) -> bool:
        """Remove a credential. If credential_id is None, remove all for provider."""
        if credential_id:
            self._credentials = [c for c in self._credentials if not (c.provider == provider and c.id == credential_id)]
        else:
            self._credentials = [c for c in self._credentials if c.provider != provider]
        self._save()
        return True

    def get_credentials(self, provider: str) -> list[Credential]:
        """Get all credentials for a provider."""
        return [c for c in self._credentials if c.provider == provider]

    def get_active_credential(self, provider: str) -> Credential | None:
        """Get the most recently used active credential for a provider."""
        creds = self.get_credentials(provider)
        active = [c for c in creds if c.is_active]
        if not active:
            return None
        # Sort by last_used descending (most recent first)
        active.sort(key=lambda c: c.last_used or "", reverse=True)
        return active[0]

    def get_next_available_credential(self, provider: str) -> Credential | None:
        """Get the next available credential for rotation.

        Returns the least recently used active credential, cycling through them.
        """
        creds = self.get_credentials(provider)
        active = [c for c in creds if c.is_active]
        if not active:
            return None
        # Sort by usage_count ascending (least used first), then by last_used descending
        active.sort(key=lambda c: (c.usage_count, -datetime.fromisoformat(c.last_used or "1970-01-01").timestamp() if c.last_used else 0))
        return active[0]

    def rotate_credential(self, provider: str) -> Credential | None:
        """Rotate to the next available credential for a provider.

        Updates last_used timestamp and increments usage_count.
        """
        cred = self.get_next_available_credential(provider)
        if cred:
            now = datetime.now(timezone.utc).isoformat()
            cred.last_used = now
            cred.usage_count += 1
            self._save()
        return cred

    def list_credentials(self, provider: str | None = None) -> list[Credential]:
        """List all credentials, optionally filtered by provider."""
        if provider:
            return self.get_credentials(provider)
        return list(self._credentials)

    def reset_usage(self, provider: str, credential_id: str | None = None) -> None:
        """Reset usage counts for credentials."""
        if credential_id:
            for c in self._credentials:
                if c.provider == provider and c.id == credential_id:
                    c.usage_count = 0
                    c.last_used = ""
        else:
            for c in self._credentials:
                if c.provider == provider:
                    c.usage_count = 0
                    c.last_used = ""
        self._save()

    def get_all_providers(self) -> list[str]:
        """Get list of all providers with registered credentials."""
        providers = set(c.provider for c in self._credentials)
        return sorted(providers)

    def total_credentials(self) -> int:
        """Total number of stored credentials."""
        return len(self._credentials)


class CredentialPool:
    """Manages credential pools per provider with auto-rotation.

    Provides a unified interface for credential management across providers.
    """

    def __init__(self, store: CredentialStore | None = None) -> None:
        self._store = store or CredentialStore()

    @property
    def store(self) -> CredentialStore:
        return self._store

    def add_key(self, provider: str, key: str, label: str = "") -> Credential:
        """Add an API key for a provider."""
        return self._store.add_credential(provider, key, label)

    def get_key(self, provider: str) -> str | None:
        """Get the next available API key for a provider (with rotation)."""
        cred = self._store.rotate_credential(provider)
        if cred:
            return cred.key
        return None

    def list_keys(self, provider: str | None = None) -> list[Credential]:
        """List API keys for a provider."""
        return self._store.list_credentials(provider)

    def remove_key(self, provider: str, credential_id: str | None = None) -> bool:
        """Remove an API key."""
        return self._store.remove_credential(provider, credential_id)

    def reset_usage(self, provider: str, credential_id: str | None = None) -> None:
        """Reset usage tracking for a provider's keys."""
        self._store.reset_usage(provider, credential_id)

    def get_all_providers(self) -> list[str]:
        """Get all providers with registered keys."""
        return self._store.get_all_providers()

    def has_key(self, provider: str) -> bool:
        """Check if a provider has any registered keys."""
        return len(self._store.get_credentials(provider)) > 0

    def get_provider_count(self) -> int:
        """Get total number of registered providers."""
        return len(self.get_all_providers())

    def get_key_count(self, provider: str) -> int:
        """Get number of keys for a provider."""
        return len(self._store.get_credentials(provider))


# ── CLI helpers ──

def get_credential_pool() -> CredentialPool:
    """Get the global credential pool instance."""
    return CredentialPool()


def auth_add(provider: str, key: str, label: str = "") -> str:
    """Add a credential and return its ID."""
    pool = get_credential_pool()
    cred = pool.add_key(provider, key, label)
    return cred.id


def auth_list(provider: str | None = None) -> list[dict[str, Any]]:
    """List credentials, optionally filtered by provider."""
    pool = get_credential_pool()
    creds = pool.list_keys(provider)
    return [
        {
            "id": c.id,
            "provider": c.provider,
            "label": c.label,
            "is_active": c.is_active,
            "created_at": c.created_at,
            "last_used": c.last_used,
            "usage_count": c.usage_count,
        }
        for c in creds
    ]


def auth_remove(provider: str, credential_id: str | None = None) -> bool:
    """Remove a credential."""
    pool = get_credential_pool()
    return pool.remove_key(provider, credential_id)


def auth_reset(provider: str, credential_id: str | None = None) -> None:
    """Reset usage for a credential."""
    pool = get_credential_pool()
    pool.reset_usage(provider, credential_id)
