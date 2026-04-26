"""
BM25 index over the skill catalog.

Scans the SKILLS list from tools_catalog.py and all SKILL.md files on disk.
Provides fast lexical matching without embedding overhead.
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SkillEntry:
    """Single skill entry in the BM25 index."""
    id: str
    name: str
    description: str
    category: str
    file_path: str = ""  # Path to the SKILL.md on disk
    tags: list[str] = field(default_factory=list)
    setup_needed: bool = False
    missing_env: list[str] = field(default_factory=list)
    missing_cmds: list[str] = field(default_factory=list)

    def to_text(self) -> str:
        """Combine name, description, tags, category into searchable text."""
        parts = [self.name, self.description]
        if self.tags:
            parts.extend(self.tags)
        if self.category:
            parts.append(self.category)
        return " ".join(parts)


@dataclass
class BM25Result:
    """Result from BM25 search."""
    skill_id: str
    score: float
    matched_fields: list[str] = field(default_factory=list)
    reason: str = ""


# ---------------------------------------------------------------------------
# BM25 scoring (lightweight, no external deps)
# ---------------------------------------------------------------------------

_K = 1.2
_B = 0.75
_MIN_DOC_FREQ = 1


def _tokenize(text: str) -> list[str]:
    """Simple whitespace + underscore tokenizer."""
    return re.findall(r"[a-zA-Z0-9_]+", text.lower())


def _avg_doc_len(documents: list[str]) -> float:
    if not documents:
        return 0.0
    return sum(len(_tokenize(d)) for d in documents) / len(documents)


class SkillBM25Index:
    """
    Lightweight BM25 index over skill catalog.
    
    Indexes name, description, tags, and category of each skill.
    Search is pure lexical — no embedding model needed.
    ~5ms for 100 skills.
    """

    def __init__(self):
        self.skills: dict[str, SkillEntry] = {}
        self._doc_lengths: dict[str, int] = {}
        self._doc_freq: dict[str, int] = {}
        self._num_docs: int = 0
        self._avg_dl: float = 0.0
        self._initialized: bool = False

    def _compute_stats(self):
        """Compute document lengths and document frequencies."""
        all_texts = []
        for skill in self.skills.values():
            text = skill.to_text()
            tokens = _tokenize(text)
            self._doc_lengths[skill.id] = len(tokens)
            all_texts.append(text)
            for token in set(tokens):
                self._doc_freq[token] = self._doc_freq.get(token, 0) + 1
        self._num_docs = len(all_texts)
        self._avg_dl = _avg_doc_len(all_texts)

    def add_skill(self, skill: SkillEntry):
        """Add a skill to the index."""
        self.skills[skill.id] = skill

    def _score_skill(self, skill: SkillEntry, query_tokens: list[str]) -> tuple[float, list[str]]:
        """Score a single skill against query tokens."""
        text = skill.to_text()
        doc_tokens = _tokenize(text)
        doc_len = self._doc_lengths[skill.id]

        if not doc_len or not query_tokens:
            return 0.0, []

        score = 0.0
        matched = []
        k = _K
        b = _B

        for qtok in query_tokens:
            freq = doc_tokens.count(qtok)
            if freq == 0:
                continue

            df = self._doc_freq.get(qtok, _MIN_DOC_FREQ)
            idf = math.log(
                (self._num_docs - df + 0.5) / (df + 0.5) + 1.0
            )

            numerator = freq * (k + 1)
            denominator = freq + k * (1 - b + b * doc_len / self._avg_dl)
            bm25 = idf * numerator / denominator

            score += bm25
            matched.append(qtok)

        return score, matched

    def search(self, query: str, top_n: int = 10) -> list[BM25Result]:
        """
        Search skills by query text.
        Returns ranked list of BM25Result with scores and match details.
        """
        if not self._initialized:
            self._compute_stats()
            self._initialized = True

        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        results = []
        for skill_id, skill in self.skills.items():
            score, matched = self._score_skill(skill, query_tokens)
            if score > 0:
                reason_parts = []
                if len(matched) > 0:
                    reason_parts.append(f"matched: {', '.join(matched)}")
                if skill.category:
                    reason_parts.append(f"category: {skill.category}")
                reason = "; ".join(reason_parts)

                results.append(BM25Result(
                    skill_id=skill_id,
                    score=round(score, 4),
                    matched_fields=matched,
                    reason=reason,
                ))

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_n]

    def get_skill(self, skill_id: str) -> SkillEntry | None:
        """Retrieve a skill by ID."""
        return self.skills.get(skill_id)

    def get_all_ids(self) -> list[str]:
        """Get all skill IDs."""
        return list(self.skills.keys())

    def get_skill_name(self, skill_id: str) -> str | None:
        """Get the human-readable name for a skill ID."""
        entry = self.skills.get(skill_id)
        return entry.name if entry else None

    def get_skill_description(self, skill_id: str) -> str | None:
        """Get the description for a skill ID."""
        entry = self.skills.get(skill_id)
        return entry.description if entry else None

    def get_skill_category(self, skill_id: str) -> str | None:
        """Get the category for a skill ID."""
        entry = self.skills.get(skill_id)
        return entry.category if entry else None

    def count(self) -> int:
        return len(self.skills)


# ---------------------------------------------------------------------------
# Catalog scanner
# ---------------------------------------------------------------------------

def _scan_skills_from_catalog() -> list[SkillEntry]:
    """Scan SKILLS list from tools_catalog.py."""
    from core.tools.tools_catalog import SKILLS
    entries = []
    for skill in SKILLS:
        entry = SkillEntry(
            id=skill.name,
            name=skill.name,
            description=skill.description,
            category=skill.category,
            file_path=skill.file_path,
            setup_needed=skill.setup_needed,
            missing_env=skill.missing_env,
            missing_cmds=skill.missing_cmds,
        )
        entries.append(entry)
    return entries


def _scan_skills_from_disk() -> list[SkillEntry]:
    """Scan ~/.hermes/skills/ for SKILL.md files not in catalog."""
    skill_dir = Path.home() / ".hermes" / "skills"
    if not skill_dir.exists():
        return []

    entries = []
    for skill_md in skill_dir.rglob("SKILL.md"):
        # Skip if already in catalog
        # We'll merge later
        try:
            content = skill_md.read_text()
            # Extract name from frontmatter
            name_match = re.search(r'^\s*name:\s*(.+)$', content, re.MULTILINE)
            if not name_match:
                continue
            name = name_match.group(1).strip().strip('"').strip("'")

            desc_match = re.search(r'^\s*description:\s*(.+)$', content, re.MULTILINE)
            description = desc_match.group(1).strip().strip('"').strip("'") if desc_match else ""

            cat_match = re.search(r'^\s*category:\s*(.+)$', content, re.MULTILINE)
            category = cat_match.group(1).strip().strip('"').strip("'") if cat_match else "custom"

            entry = SkillEntry(
                id=name,
                name=name,
                description=description,
                category=category,
                file_path=str(skill_md),
            )
            entries.append(entry)
        except Exception:
            continue
    return entries


def build_skill_index() -> SkillBM25Index:
    """
    Build the complete skill index from catalog and disk.
    Disk skills override catalog entries with same ID.
    """
    index = SkillBM25Index()

    # First pass: catalog
    catalog_skills = _scan_skills_from_catalog()
    for skill in catalog_skills:
        index.add_skill(skill)

    # Second pass: disk (overrides catalog)
    disk_skills = _scan_skills_from_disk()
    for skill in disk_skills:
        # Check if SKILL.md exists at expected path
        if skill.file_path and Path(skill.file_path).exists():
            index.add_skill(skill)

    return index
