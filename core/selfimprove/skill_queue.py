"""SkillQueue — manages draft skill proposals in a JSON file.

Enhanced with:
- Draft expiry (auto-expire old drafts after 7 days)
- Usage tracking (track how often a skill gets approved/discarded)
- Duplicate detection against both pending drafts AND existing skills
- Ranked listing (highest score first)
- Domain-level approval rate tracking for threshold tuning
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_QUEST_PATH = Path.home() / ".noman/skill_suggestions.json"
USAGE_DB_PATH = Path.home() / ".noman/skill_usage_stats.json"

# How long a draft stays valid (seconds)
DRAFT_TTL = 7 * 24 * 3600  # 7 days


@dataclass
class SkillDraft:
    """A draft skill proposal waiting for human review."""

    draft_id: str
    name: str
    description: str
    content: str  # Full SKILL.md content
    trigger_reason: str  # Why this was suggested
    score: float  # 0.0-1.0, from trace_critic
    domain: str = "general"  # Detected domain of the trace
    created_at: float = field(default_factory=time.time)
    discarded: bool = False
    approved: bool = False
    usage_count: int = 0  # How many times this skill was referenced
    last_reviewed_at: float | None = None

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > DRAFT_TTL

    @property
    def age_hours(self) -> float:
        return (time.time() - self.created_at) / 3600.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SkillDraft":
        return cls(**data)


class SkillQueue:
    """Persistent queue of skill drafts awaiting human review."""

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
        domain: str = "general",
    ) -> str | None:
        """Add a draft skill proposal. Returns draft_id or None if rejected.

        Rejection reasons:
        - Duplicate name exists (pending or approved)
        - Duplicate name exists in existing approved skills
        """
        drafts = self._load()
        draft_id = f"draft_{uuid.uuid4().hex[:8]}"

        # Check for duplicate name in pending drafts (from this queue's path)
        for d in drafts:
            if d.get("name") == name:
                if d.get("discarded") or d.get("approved"):
                    # Old draft is dead, remove it
                    drafts.remove(d)
                    logger.info("Removed expired/dead draft '%s' (duplicate: %s)", d.get("draft_id"), name)
                else:
                    # Active pending draft with same name — skip new one
                    logger.info("Skipping duplicate draft for '%s' (keeping existing %s)", name, d.get("draft_id"))
                    return None

        # Also check the default queue for duplicates (cross-queue dedup)
        if self.path != DEFAULT_QUEST_PATH:
            default_queue = SkillQueue(path=DEFAULT_QUEST_PATH)
            for existing in default_queue.list_pending():
                if existing.name == name:
                    logger.info("Skipping duplicate draft for '%s' (found in default queue)", name)
                    return None

        draft = SkillDraft(
            draft_id=draft_id,
            name=name,
            description=description,
            content=content,
            trigger_reason=trigger_reason,
            score=score,
            domain=domain,
        )

        drafts.append(draft.to_dict())
        self._save(drafts)
        logger.info("Added skill draft '%s' (score: %.2f, domain: %s)", name, score, domain)
        return draft_id

    def list_pending(self) -> list[SkillDraft]:
        """Return non-discarded, non-expired drafts, sorted by score (highest first)."""
        drafts = self._load()
        pending = []
        now = time.time()
        for d in drafts:
            if d.get("discarded", False):
                continue
            created_at = d.get("created_at", 0)
            if (now - created_at) > DRAFT_TTL:
                # Auto-expire old drafts
                logger.info("Auto-expiring draft '%s' (age: %.1f hours)", d.get("draft_id"),
                           (now - created_at) / 3600)
                d["discarded"] = True
                continue
            pending.append(SkillDraft.from_dict(d))
        # Sort by score descending
        pending.sort(key=lambda d: d.score, reverse=True)
        self._save([d.to_dict() for d in pending])  # Clean up expired
        return pending

    def approve(self, draft_id: str) -> tuple[bool, str]:
        """Approve a draft: write SKILL.md to ~/.hermes/skills/<name>/."""
        drafts = self._load()
        for i, d in enumerate(drafts):
            if d["draft_id"] == draft_id:
                draft = SkillDraft.from_dict(d)
                skill_dir = Path.home() / ".hermes/skills" / draft.name
                skill_dir.mkdir(parents=True, exist_ok=True)
                skill_file = skill_dir / "SKILL.md"
                skill_file.write_text(draft.content)

                drafts[i]["approved"] = True
                drafts[i]["discarded"] = True
                drafts[i]["approved_id"] = f"skill_{draft.name}"

                # Record approval in usage DB for domain-level tracking
                self._record_approval(draft.domain, draft.name)

                self._save(drafts)
                logger.info("Approved skill draft '%s' -> %s", draft.name, skill_file)
                return True, f"Skill '{draft.name}' created at {skill_file}"

        return False, f"Draft '{draft_id}' not found"

    def discard(self, draft_id: str) -> tuple[bool, str]:
        """Discard a draft (soft delete)."""
        drafts = self._load()
        for i, d in enumerate(drafts):
            if d["draft_id"] == draft_id:
                draft = SkillDraft.from_dict(d)
                drafts[i]["discarded"] = True

                # Record discard in usage DB for domain-level tracking
                self._record_discard(draft.domain)

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
                drafts[i]["last_reviewed_at"] = time.time()
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

    def get_usage_stats(self) -> dict[str, Any]:
        """Return usage statistics for all drafts ever created."""
        drafts = self._load()
        total = len(drafts)
        pending = sum(1 for d in drafts if not d.get("discarded", False) and not d.get("approved", False))
        approved = sum(1 for d in drafts if d.get("approved", False))
        discarded = sum(1 for d in drafts if d.get("discarded", False) and not d.get("approved", False))
        expired = 0
        now = time.time()
        for d in drafts:
            created_at = d.get("created_at", 0)
            if (now - created_at) > DRAFT_TTL:
                expired += 1

        # Also load domain-level stats
        domain_stats = self._get_domain_stats()

        return {
            "total": total,
            "pending": pending,
            "approved": approved,
            "discarded": discarded,
            "expired": expired,
            "domain_stats": domain_stats,
        }

    # ------------------------------------------------------------------
    # Usage tracking for domain-level threshold tuning
    # ------------------------------------------------------------------

    def _load_usage_db(self) -> dict:
        """Load the usage statistics database."""
        if USAGE_DB_PATH.exists():
            try:
                return json.loads(USAGE_DB_PATH.read_text())
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save_usage_db(self, data: dict) -> None:
        """Save the usage statistics database."""
        USAGE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        USAGE_DB_PATH.write_text(json.dumps(data, indent=2))

    def _record_approval(self, domain: str, skill_name: str) -> None:
        """Record that a draft was approved."""
        db = self._load_usage_db()
        domains = db.setdefault("domains", {})
        domain_data = domains.setdefault(domain, {"approved": 0, "discarded": 0})
        domain_data["approved"] += 1
        self._save_usage_db(db)

    def _record_discard(self, domain: str) -> None:
        """Record that a draft was discarded."""
        db = self._load_usage_db()
        domains = db.setdefault("domains", {})
        domain_data = domains.setdefault(domain, {"approved": 0, "discarded": 0})
        domain_data["discarded"] += 1
        self._save_usage_db(db)

    def _get_domain_stats(self) -> dict[str, dict]:
        """Get per-domain approval/discard stats."""
        db = self._load_usage_db()
        return db.get("domains", {})

    def get_domain_approval_rate(self, domain: str) -> float:
        """Get the approval rate for a domain (approved / total).

        Returns 0.0 if no data, 1.0 if all approved.
        Higher rate = domain produces more useful skills.
        """
        stats = self._get_domain_stats()
        domain_data = stats.get(domain, {"approved": 0, "discarded": 0})
        total = domain_data["approved"] + domain_data["discarded"]
        if total == 0:
            return 0.5  # No data yet, neutral
        return domain_data["approved"] / total

    def get_recommended_threshold(self, domain: str) -> float:
        """Get a recommended score threshold for a domain.

        Domains with high approval rates can use lower thresholds
        (more likely to produce useful skills). Domains with low
        approval rates should use higher thresholds.
        """
        rate = self.get_domain_approval_rate(domain)
        # Base threshold is 0.7, adjusted by approval rate
        # rate=1.0 -> 0.5 threshold, rate=0.0 -> 0.9 threshold
        base = 0.7
        adjustment = (0.5 - rate) * 0.4  # Range: -0.2 to +0.2
        return max(0.4, min(1.0, base + adjustment))
