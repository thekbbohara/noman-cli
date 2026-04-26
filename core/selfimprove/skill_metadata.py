"""
Skill metadata tracking — usage stats, effectiveness scoring,
personalization data for ranking.

Stores per-skill lifecycle data in ~/.noman/skill_metadata.json.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


METADATA_PATH = Path.home() / ".noman" / "skill_metadata.json"

# Default values for new skills
_DEFAULT_METADATA = {
    "loaded_count": 0,
    "last_loaded": 0.0,
    "avg_session_length": 0,
    "discarded_count": 0,
    "discarded_reasons": [],
    "usage_categories": [],
    "prerequisites": [],
    "required_by": [],
    "effectiveness_score": 0.5,
    "semantic_tags": [],
    "last_updated": 0.0,
    "freshness_boost": 1.0,  # Decays over time
}


@dataclass
class SkillMetadata:
    """Per-skill usage metadata."""
    loaded_count: int = 0
    last_loaded: float = 0.0
    avg_session_length: float = 0.0
    session_turns: list[float] = field(default_factory=list)
    discarded_count: int = 0
    discarded_reasons: list[str] = field(default_factory=list)
    usage_categories: list[str] = field(default_factory=list)
    prerequisites: list[str] = field(default_factory=list)
    required_by: list[str] = field(default_factory=list)
    effectiveness_score: float = 0.5  # 0.0 = useless, 1.0 = essential
    semantic_tags: list[str] = field(default_factory=list)
    last_updated: float = 0.0
    freshness_boost: float = 1.0
    _session_load_time: float = 0.0  # Internal: when loaded this session

    def to_dict(self) -> dict:
        d = asdict(self)
        # Remove internal fields
        d.pop('_session_load_time', None)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> 'SkillMetadata':
        # Filter out internal fields
        clean = {k: v for k, v in d.items() if not k.startswith('_')}
        return cls(**clean)

    def record_load(self):
        """Record a skill load event."""
        self.loaded_count += 1
        self.last_loaded = time.time()
        self._session_load_time = time.time()

    def record_discard(self, reason: str = ""):
        """Record a skill discard event."""
        self.discarded_count += 1
        if reason and reason not in self.discarded_reasons:
            self.discarded_reasons.append(reason)

    def record_session_end(self, turns: int):
        """Record session length for this skill."""
        self.session_turns.append(turns)
        if self.session_turns:
            self.avg_session_length = sum(self.session_turns) / len(self.session_turns)

    def update_effectiveness(self):
        """Recalculate effectiveness score based on usage."""
        if self.loaded_count == 0:
            self.effectiveness_score = 0.5
            return

        # Base score: ratio of non-discarded loads
        base = (self.loaded_count - self.discarded_count) / self.loaded_count
        base = max(0.0, min(1.0, base))

        # Session length bonus: longer sessions = more useful
        session_bonus = 0.0
        if self.avg_session_length > 0:
            if self.avg_session_length >= 10:
                session_bonus = 0.15
            elif self.avg_session_length >= 5:
                session_bonus = 0.08
            elif self.avg_session_length >= 2:
                session_bonus = 0.03

        self.effectiveness_score = min(1.0, base + session_bonus)

    def decay_freshness(self, hours_since_load: float):
        """Decay freshness boost over time (24h half-life)."""
        if hours_since_load < 48:
            # Half-life decay: 1.0 -> 0.5 over 24h
            self.freshness_boost = max(0.0, 1.0 - (hours_since_load / 48.0))
        else:
            self.freshness_boost = 0.0


class SkillMetadataStore:
    """
    Persistent metadata store for skill usage tracking.
    
    Loads from ~/.noman/skill_metadata.json on init.
    Saves on every modification.
    """

    def __init__(self, path: Path = METADATA_PATH):
        self.path = path
        self._data: dict[str, SkillMetadata] = {}
        self._dirty = False
        self._load()

    def _load(self):
        """Load metadata from disk."""
        if self.path.exists():
            try:
                content = self.path.read_text()
                raw = json.loads(content)
                for skill_id, meta in raw.items():
                    self._data[skill_id] = SkillMetadata.from_dict(meta)
            except (json.JSONDecodeError, TypeError):
                self._data = {}

    def _save(self):
        """Save metadata to disk."""
        if not self._dirty:
            return

        self.path.parent.mkdir(parents=True, exist_ok=True)
        raw = {}
        for skill_id, meta in self._data.items():
            raw[skill_id] = meta.to_dict()
        self.path.write_text(json.dumps(raw, indent=2))
        self._dirty = False

    def get(self, skill_id: str) -> SkillMetadata:
        """Get metadata for a skill (creates default if missing)."""
        if skill_id not in self._data:
            self._data[skill_id] = SkillMetadata()
        return self._data[skill_id]

    def record_load(self, skill_id: str):
        """Record a skill load event."""
        meta = self.get(skill_id)
        meta.record_load()
        self._dirty = True

    def record_discard(self, skill_id: str, reason: str = ""):
        """Record a skill discard event."""
        meta = self.get(skill_id)
        meta.record_discard(reason)
        self._dirty = True

    def record_session_end(self, skill_id: str, turns: int):
        """Record session length for a skill."""
        meta = self.get(skill_id)
        meta.record_session_end(turns)
        self._dirty = True

    def update_effectiveness(self, skill_id: str):
        """Recalculate effectiveness for a skill."""
        meta = self.get(skill_id)
        meta.update_effectiveness()
        self._dirty = True

    def decay_freshness(self, skill_id: str, hours_since_load: float):
        """Apply freshness decay."""
        meta = self.get(skill_id)
        meta.decay_freshness(hours_since_load)
        self._dirty = True

    def get_effectiveness(self, skill_id: str) -> float:
        """Get the effectiveness score for a skill."""
        meta = self.get(skill_id)
        return meta.effectiveness_score

    def get_loaded_count(self, skill_id: str) -> int:
        """Get load count for a skill."""
        meta = self.get(skill_id)
        return meta.loaded_count

    def get_freshness_boost(self, skill_id: str) -> float:
        """Get the freshness boost for a skill."""
        meta = self.get(skill_id)
        return meta.freshness_boost

    def get_recently_loaded(self, max_hours: float = 24) -> list[str]:
        """Get skills loaded within the last N hours."""
        now = time.time()
        threshold = now - (max_hours * 3600)
        return [
            sid for sid, meta in self._data.items()
            if meta.last_loaded >= threshold
        ]

    def get_low_effectiveness(self, threshold: float = 0.3) -> list[str]:
        """Get skills with effectiveness below threshold."""
        return [
            sid for sid, meta in self._data.items()
            if meta.effectiveness_score < threshold
        ]

    def cleanup_expired(self, max_hours: float = 720) -> int:
        """
        Remove metadata for skills never loaded or loaded long ago.
        Returns count of removed entries.
        """
        now = time.time()
        threshold = now - (max_hours * 3600)
        removed = 0
        to_remove = []

        for sid, meta in self._data.items():
            if meta.loaded_count == 0 and meta.last_loaded == 0:
                to_remove.append(sid)
            elif meta.last_loaded < threshold and meta.loaded_count < 2:
                to_remove.append(sid)

        for sid in to_remove:
            del self._data[sid]
            removed += 1

        if removed > 0:
            self._dirty = True

        return removed

    def save(self):
        """Explicitly save metadata."""
        self._save()
