"""Conversation-derived entity extraction.

Tracks entities mentioned in conversations and auto-creates
or updates wiki pages when an entity is mentioned multiple
times. Captures insights from discussions without requiring
manual wiki updates.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.wiki.graph import Entity, EntityType, EdgeType
from core.wiki.wiki import Wiki


@dataclass
class ConversationEntry:
    """A single conversation turn with entity mentions."""
    turn_id: str
    role: str  # "user" or "assistant"
    content: str
    entities_mentioned: list[dict] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class EntityMention:
    """An entity mentioned in conversation."""
    name: str
    entity_type: str  # "class", "module", "function", "concept", "pattern"
    context: str = ""  # surrounding text
    confidence: float = 0.5


class ConversationExtractor:
    """Extract entities from conversation context.

    Tracks entity mentions across turns and auto-creates
    wiki pages when entities are mentioned 2+ times.
    """

    # Patterns for detecting entity names in conversation
    PATTERN_RULES = [
        # Class names (CamelCase)
        (r'\b([A-Z][a-z]+(?:[A-Z][a-z]+)+)\b', 'class', 0.8),
        # Module names (snake_case with known prefixes)
        (r'\b(?:module|package|library|import)\s+([a-z_]+(?:\.[a-z_]+)*)', 'module', 0.9),
        # Function names
        (r'\b(?:function|method|def|call)\s+([a-z_]+(?:\.[a-z_]+)*)', 'function', 0.7),
        # Pattern names
        (r'\b(?:pattern|design\s+pattern)\s+([A-Z][a-zA-Z]+(?:\s+[a-z]+)+)', 'pattern', 0.7),
        # Concept names
        (r'\b(concept|topic|idea)\s+["\']?([a-z\s]+?)["\']?\s*[,\.)]', 'concept', 0.6),
    ]

    # Common stop words to filter out
    STOP_WORDS = {
        'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
        'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
        'would', 'could', 'should', 'may', 'might', 'can', 'shall',
        'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from',
        'as', 'into', 'through', 'during', 'before', 'after', 'above',
        'below', 'between', 'and', 'or', 'but', 'not', 'no', 'yes',
        'it', 'its', 'this', 'that', 'these', 'those', 'i', 'you',
        'he', 'she', 'we', 'they', 'me', 'him', 'her', 'us', 'them',
        'my', 'your', 'his', 'our', 'their', 'what', 'which', 'who',
        'how', 'where', 'when', 'why', 'if', 'then', 'else', 'than',
        'more', 'most', 'less', 'least', 'very', 'just', 'about',
        'also', 'only', 'each', 'every', 'all', 'some', 'any',
    }

    def __init__(self, wiki: Wiki, storage_path: Path | None = None) -> None:
        self._wiki = wiki
        self._storage = storage_path or Path.home() / '.noman' / 'wiki' / 'conversation'
        self._storage.mkdir(parents=True, exist_ok=True)
        self._entries: list[ConversationEntry] = []
        self._mention_counts: dict[str, dict] = defaultdict(lambda: {
            'count': 0,
            'types': defaultdict(int),
            'contexts': [],
            'last_seen': None,
        })
        self._load()

    def _load(self) -> None:
        """Load conversation state from disk."""
        state_file = self._storage / 'state.json'
        if state_file.exists():
            try:
                data = json.loads(state_file.read_text())
                self._mention_counts = defaultdict(lambda: {
                    'count': 0,
                    'types': defaultdict(int),
                    'contexts': [],
                    'last_seen': None,
                })
                for key, val in data.items():
                    if isinstance(val, dict):
                        val['types'] = defaultdict(int, val.get('types', {}))
                        self._mention_counts[key] = val
            except (json.JSONDecodeError, TypeError):
                pass

    def _save(self) -> None:
        """Save conversation state to disk."""
        state_file = self._storage / 'state.json'
        # Convert defaultdicts to plain dicts for serialization
        saveable = {}
        for key, val in self._mention_counts.items():
            saveable[key] = {
                'count': val['count'],
                'types': dict(val['types']),
                'contexts': val.get('contexts', [])[-10:],  # Keep last 10
                'last_seen': val['last_seen'],
            }
        state_file.write_text(json.dumps(saveable, indent=2))

    def add_turn(self, turn_id: str, role: str, content: str) -> list[EntityMention]:
        """Process a conversation turn and extract entities.

        Args:
            turn_id: Unique identifier for this turn.
            role: "user" or "assistant".
            content: The text content of the turn.

        Returns:
            List of extracted EntityMention objects.
        """
        mentions = self._extract_mentions(content)
        entry = ConversationEntry(
            turn_id=turn_id,
            role=role,
            content=content,
            entities_mentioned=[m.__dict__ for m in mentions],
        )
        self._entries.append(entry)
        self._entries = self._entries[-100:]  # Keep last 100 turns

        # Update mention counts
        for mention in mentions:
            key = mention.name.lower()
            self._mention_counts[key]['count'] += 1
            self._mention_counts[key]['types'][mention.entity_type] += 1
            self._mention_counts[key]['contexts'].append(mention.context)
            self._mention_counts[key]['last_seen'] = datetime.now(timezone.utc).isoformat()

        self._save()

        # Auto-create pages for entities mentioned 2+ times
        auto_created = []
        for key, data in self._mention_counts.items():
            if data['count'] >= 2:
                page_id = self._ensure_entity_page(key, data)
                if page_id:
                    auto_created.append(page_id)

        return mentions

    def _extract_mentions(self, content: str) -> list[EntityMention]:
        """Extract entity mentions from text content."""
        mentions = []
        seen_names: set[str] = set()

        for pattern, entity_type, confidence in self.PATTERN_RULES:
            for match in re.finditer(pattern, content):
                name = match.group(1) if match.lastindex and match.lastindex >= 1 else match.group(0)

                # Skip stop words and short names
                if name.lower() in self.STOP_WORDS:
                    continue
                if len(name) < 2:
                    continue

                # Skip already seen
                if name.lower() in seen_names:
                    continue

                context = content[max(0, match.start()-30):match.end()+30]
                mention = EntityMention(
                    name=name,
                    entity_type=entity_type,
                    context=context.strip(),
                    confidence=confidence,
                )
                mentions.append(mention)
                seen_names.add(name.lower())

        return mentions

    def _ensure_entity_page(self, key: str, data: dict) -> str | None:
        """Create or update a wiki page for a mentioned entity."""
        # Determine entity type from mention history
        type_counts = data['types']
        dominant_type = max(type_counts, key=type_counts.get) if type_counts else 'concept'

        # Map to EntityType
        type_map = {
            'class': EntityType.CONCEPT,
            'module': EntityType.CONCEPT,
            'function': EntityType.CONCEPT,
            'pattern': EntityType.PATTERN,
            'concept': EntityType.CONCEPT,
        }
        entity_type = type_map.get(dominant_type, EntityType.CONCEPT)

        # Check if entity already exists
        existing = self._wiki.graph.get_entity(f"conv:{key}")
        if existing:
            # Update metadata
            existing.metadata['mentioned_count'] = data['count']
            existing.metadata['mention_types'] = dict(data['types'])
            existing.metadata['last_mentioned'] = data['last_seen']
            self._wiki.graph.upsert_entity(existing)
            return f"conv:{key}"

        # Create new entity
        entity = Entity(
            id=f"conv:{key}",
            name=key.title() if dominant_type == 'concept' else key,
            entity_type=entity_type,
            scope="conversation",
            summary=f"Entity mentioned {data['count']} times in conversation",
            metadata={
                'mentioned_count': data['count'],
                'mention_types': dict(data['types']),
                'last_seen': data['last_seen'],
            },
        )
        self._wiki.graph.upsert_entity(entity)
        return f"conv:{key}"

    def get_mention_counts(self, limit: int = 20) -> list[dict]:
        """Get top entity mentions."""
        sorted_mentions = sorted(
            self._mention_counts.items(),
            key=lambda x: x[1]['count'],
            reverse=True,
        )
        return [
            {
                'name': name,
                'count': data['count'],
                'types': dict(data['types']),
                'last_seen': data['last_seen'],
            }
            for name, data in sorted_mentions[:limit]
        ]

    def reset(self) -> None:
        """Reset conversation state."""
        self._mention_counts.clear()
        self._entries.clear()
        self._save()
