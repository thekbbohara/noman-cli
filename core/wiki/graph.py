"""Knowledge graph data structure.

Stores entities (projects, concepts, tools, people), their types, and
relationships (edges) between them. Serializes to JSON for persistence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class EntityType(str, Enum):
    PROJECT = "project"
    TOOL = "tool"
    CONCEPT = "concept"
    PERSON = "person"
    DATABASE = "database"
    FRAMEWORK = "framework"
    API = "api"
    CONFIG = "config"
    BUG = "bug"
    FIX = "fix"
    PATTERN = "pattern"
    UNKNOWN = "unknown"


class EdgeType(str, Enum):
    """Types of relationships between entities."""
    REFERENCES = "references"
    DEPENDS_ON = "depends_on"
    IMPLEMENTS = "implements"
    USES = "uses"
    RELATES_TO = "relates_to"
    CONTRADICTS = "contradicts"
    EXTENDS = "extends"
    PART_OF = "part_of"
    ORIGINATED_FROM = "originated_from"
    SIMILAR_TO = "similar_to"


@dataclass
class Entity:
    """A node in the knowledge graph."""
    id: str
    name: str
    entity_type: EntityType
    scope: str = "global"  # "global" or a project path
    summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        d = asdict(self)
        d["entity_type"] = self.entity_type.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Entity:
        entity_type = d.get("entity_type", "unknown")
        if isinstance(entity_type, str):
            entity_type = EntityType(entity_type)
        d["entity_type"] = entity_type
        return cls(**d)


@dataclass
class Edge:
    """A relationship between two entities."""
    source: str  # entity id
    target: str  # entity id
    edge_type: EdgeType
    weight: float = 1.0
    evidence: str = ""  # brief note about why this edge exists
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        d = asdict(self)
        d["edge_type"] = self.edge_type.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Edge:
        edge_type = d.get("edge_type", "relates_to")
        if isinstance(edge_type, str):
            edge_type = EdgeType(edge_type)
        d["edge_type"] = edge_type
        return cls(**d)


class Graph:
    """Persistent knowledge graph backed by JSON.

    Entities are stored as individual files for git-versioning.
    Edges are stored in a single edges.json for efficient traversal.
    """

    def __init__(self, base_path: str | Path) -> None:
        self._base = Path(base_path)
        self._base.mkdir(parents=True, exist_ok=True)
        self._entities: dict[str, Entity] = {}
        self._edges: list[Edge] = []
        self._load()

    # --- Entity CRUD ---

    def get_entity(self, entity_id: str) -> Entity | None:
        return self._entities.get(entity_id)

    def upsert_entity(self, entity: Entity) -> None:
        entity.touch()
        self._entities[entity.id] = entity
        self._save_entity_file(entity)
        self._save_edges()  # re-index edges

    def remove_entity(self, entity_id: str) -> bool:
        if entity_id not in self._entities:
            return False
        del self._entities[entity_id]
        # Delete file
        fpath = self._entity_file_path(entity_id)
        if fpath.exists():
            fpath.unlink()
        # Remove edges involving this entity
        self._edges = [
            e for e in self._edges
            if e.source != entity_id and e.target != entity_id
        ]
        self._save_edges()
        return True

    def list_entities(
        self,
        entity_type: EntityType | None = None,
        scope: str | None = None,
        limit: int = 100,
    ) -> list[Entity]:
        entities = list(self._entities.values())
        if entity_type:
            entities = [e for e in entities if e.entity_type == entity_type]
        if scope:
            entities = [e for e in entities if e.scope == scope]
        # Sort by updated_at descending
        entities.sort(key=lambda e: e.updated_at, reverse=True)
        return entities[:limit]

    # --- Edge CRUD ---

    def add_edge(
        self,
        source: str,
        target: str,
        edge_type: EdgeType,
        weight: float = 1.0,
        evidence: str = "",
    ) -> Edge:
        edge = Edge(
            source=source,
            target=target,
            edge_type=edge_type,
            weight=weight,
            evidence=evidence,
        )
        # Avoid duplicate edges with same type
        for i, existing in enumerate(self._edges):
            if (existing.source == edge.source
                    and existing.target == edge.target
                    and existing.edge_type == edge.edge_type):
                # Update weight (incremental)
                self._edges[i].weight = min(1.0, existing.weight + 0.1)
                if evidence:
                    self._edges[i].evidence = evidence
                break
        else:
            self._edges.append(edge)
        self._save_edges()
        return edge

    def remove_edge(self, source: str, target: str, edge_type: EdgeType) -> bool:
        for i, e in enumerate(self._edges):
            if e.source == source and e.target == target and e.edge_type == edge_type:
                self._edges.pop(i)
                self._save_edges()
                return True
        return False

    def get_edges(
        self,
        entity_id: str,
        direction: str = "out",
    ) -> list[Edge]:
        if direction == "out":
            return [e for e in self._edges if e.source == entity_id]
        elif direction == "in":
            return [e for e in self._edges if e.target == entity_id]
        return []

    def get_all_edges(self) -> list[Edge]:
        return list(self._edges)

    def get_neighbors(
        self,
        entity_id: str,
        edge_type: EdgeType | None = None,
        max_depth: int = 2,
    ) -> list[tuple[str, EdgeType, float]]:
        """Get connected entity IDs with their edge type and weight. BFS up to max_depth."""
        visited: set[str] = set()
        result: list[tuple[str, EdgeType, float]] = []
        frontier: list[str] = [entity_id]

        for _ in range(max_depth):
            next_frontier: list[str] = []
            for current_id in frontier:
                for edge in self.get_edges(current_id, direction="out"):
                    if edge.target not in visited:
                        if edge_type is None or edge.edge_type == edge_type:
                            result.append((edge.target, edge.edge_type, edge.weight))
                        visited.add(edge.target)
                        next_frontier.append(edge.target)
                for edge in self.get_edges(current_id, direction="in"):
                    if edge.source not in visited:
                        if edge_type is None or edge.edge_type == edge_type:
                            result.append((edge.source, edge.edge_type, edge.weight))
                        visited.add(edge.source)
                        next_frontier.append(edge.source)
            frontier = next_frontier
            if not frontier:
                break

        return result

    # --- Index / queries ---

    def count(self) -> int:
        return len(self._entities)

    def edge_count(self) -> int:
        return len(self._edges)

    def summarize(self) -> dict:
        """Return a compact summary of the graph state."""
        type_counts: dict[str, int] = {}
        for e in self._entities.values():
            t = e.entity_type.value
            type_counts[t] = type_counts.get(t, 0) + 1
        return {
            "entity_count": len(self._entities),
            "edge_count": len(self._edges),
            "type_counts": type_counts,
        }

    # --- Persistence ---

    def _entity_file_path(self, entity_id: str) -> Path:
        """Entity files are named by id, stored in entities/ dir."""
        return self._base / "entities" / f"{entity_id}.json"

    def _save_entity_file(self, entity: Entity) -> None:
        path = self._entity_file_path(entity.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entity.to_dict(), indent=2))

    def _edges_file_path(self) -> Path:
        return self._base / "edges.json"

    def _save_edges(self) -> None:
        # Re-index: rebuild edges dict from entity files for consistency
        path = self._edges_file_path()
        path.write_text(json.dumps([e.to_dict() for e in self._edges], indent=2))

    def _load(self) -> None:
        """Load graph state from disk."""
        # Load entities
        entities_dir = self._base / "entities"
        if entities_dir.exists():
            for f in entities_dir.glob("*.json"):
                try:
                    data = json.loads(f.read_text())
                    entity = Entity.from_dict(data)
                    self._entities[entity.id] = entity
                except Exception:
                    continue

        # Load edges
        edges_file = self._edges_file_path()
        if edges_file.exists():
            try:
                data = json.loads(edges_file.read_text())
                self._edges = [Edge.from_dict(e) for e in data]
            except Exception:
                self._edges = []

    def reset(self) -> None:
        """Clear all graph data."""
        import shutil
        self._entities.clear()
        self._edges.clear()
        # Remove all files
        if self._base.exists():
            shutil.rmtree(self._base)
        self._base.mkdir(parents=True, exist_ok=True)
