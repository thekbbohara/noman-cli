"""SkillQueue — manages draft skill proposals in a JSON file."""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Drafts are stored here, not yet written as real skills.
DEFAULT_QUEST_PATH = Path.home() / ".noman/skill_suggestions.json"


@dataclass
class SkillDraft:
    """A draft skill proposal waiting for human review."""

    draft_id: str
    name: str
    description: str
    content: str  # Full SKILL.md content
    trigger_reason: str  # Why this was suggested
    score: float  # 0.0-1.0, from trace_critic
    created_at: float = field(default_factory=time.time)
    discarded: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SkillDraft":
        return cls(**data)


class SkillQueue:
    """
    Persistent queue of skill drafts awaiting human review.

    Provides:
    - Add drafts (from MetaAgent proposals)
    - List pending drafts
    - Approve (writes to ~/.hermes/skills/ and removes from queue)
    - Discard (removes from queue)
    - Edit draft content
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DEFAULT_QUEST_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            with open(self.path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []

    def _save(self, drafts: list[dict]) -> None:
        with open(self.path, "w") as f:
            json.dump(drafts, f, indent=2)

    def add_draft(
        self,
        name: str,
        description: str,
        content: str,
        trigger_reason: str,
        score: float,
    ) -> str:
        """Add a draft skill proposal. Returns draft_id."""
        drafts = self._load()
        draft_id = f"draft_{uuid.uuid4().hex[:8]}"

        draft = SkillDraft(
            draft_id=draft_id,
            name=name,
            description=description,
            content=content,
            trigger_reason=trigger_reason,
            score=score,
        )

        # Check for duplicate name - discard NEW draft if name exists
        for d in drafts:
            if d.get("name") == name and not d.get("discarded", False):
                logger.info("Discarding duplicate draft for '%s' (keeping existing)", name)
                return None  # Don't add duplicate

        drafts.append(draft.to_dict())
        self._save(drafts)
        logger.info("Added skill draft '%s' (score: %.2f)", name, score)
        return draft_id

    def list_pending(self) -> list[SkillDraft]:
        """Return non-discarded drafts."""
        drafts = self._load()
        pending = [d for d in drafts if not d.get("discarded", False)]
        return [SkillDraft.from_dict(d) for d in pending]

    def approve(self, draft_id: str) -> tuple[bool, str]:
        """
        Approve a draft: write SKILL.md to ~/.hermes/skills/<name>/
        and remove from queue.
        """
        drafts = self._load()
        for i, d in enumerate(drafts):
            if d["draft_id"] == draft_id:
                draft = SkillDraft.from_dict(d)
                # Write the actual skill file
                skill_dir = Path.home() / ".hermes/skills" / draft.name
                skill_dir.mkdir(parents=True, exist_ok=True)
                skill_file = skill_dir / "SKILL.md"
                skill_file.write_text(draft.content)

                # Mark as approved (use "approved_id" to track)
                drafts[i]["approved_id"] = f"skill_{draft.name}"
                drafts[i]["discarded"] = True
                self._save(drafts)
                logger.info("Approved skill draft '%s' → %s", draft.name, skill_file)
                return True, f"Skill '{draft.name}' created at {skill_file}"

        return False, f"Draft '{draft_id}' not found"

    def discard(self, draft_id: str) -> tuple[bool, str]:
        """Discard a draft (soft delete)."""
        drafts = self._load()
        for i, d in enumerate(drafts):
            if d["draft_id"] == draft_id:
                drafts[i]["discarded"] = True
                self._save(drafts)
                logger.info("Discarded draft '%s'", draft_id)
                return True, f"Draft '{draft_id}' discarded"

        return False, f"Draft '{draft_id}' not found"

    def edit(self, draft_id: str, new_content: str) -> tuple[bool, str]:
        """Edit draft content (e.g. user reviewed and tweaked)."""
        drafts = self._load()
        for i, d in enumerate(drafts):
            if d["draft_id"] == draft_id:
                drafts[i]["content"] = new_content
                self._save(drafts)
                logger.info("Edited draft '%s'", draft_id)
                return True, f"Draft '{draft_id}' updated"

        return False, f"Draft '{draft_id}' not found"

    def get_draft(self, draft_id: str) -> SkillDraft | None:
        """Get a single draft by ID."""
        drafts = self._load()
        for d in drafts:
            if d["draft_id"] == draft_id:
                return SkillDraft.from_dict(d)
        return None

    def clear_all(self) -> int:
        """Remove all drafts. Returns count removed."""
        count = len(self._load())
        self._save([])
        return count
