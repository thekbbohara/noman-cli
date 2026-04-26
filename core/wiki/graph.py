"""Knowledge graph data structure.

Stores entities (projects, concepts, tools, people), their types, and
relationships (edges) between them. Serializes to JSON for persistence.
"""

from __future__ import annotations

import json
from collections import defaultdict
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




class EntityStatus(str, Enum):
    """Lifecycle status for wiki entities."""
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"
    SUPERSEDED = "superseded"


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

    # Hotspot/complexity data
    complexity: int = 0
    hotspot_score: float = 0.0
    churn_per_week: float = 0.0

    # Cross-project links
    cross_project_links: list[str] = field(default_factory=list)

    # Embedding cache key
    embedding_key: str = ""
    
    # Lifecycle status
    status: EntityStatus = EntityStatus.ACTIVE
    superseded_by: str = ""
    
    # Call chain data
    call_chains: list[dict] = field(default_factory=list)
    
    # Type annotation relationships
    type_annotations: dict[str, str] = field(default_factory=dict)
    
    # File hash tracking
    file_hash: str = ""
    
    # Diff history
    version: str = ""
    diff_from_previous: str = ""

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Entity):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)


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
        self._cross_project: dict[str, list[dict]] = {}  # entity_id -> cross-links
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
        # Remove cross-project links
        self._cross_project.pop(entity_id, None)
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

    # --- Cross-project linking ---

    def add_cross_project_link(self, local_entity_id: str, target_project: str, target_entity_id: str, similarity: float = 0.0) -> None:
        """Add a cross-project link between entities."""
        self._cross_project.setdefault(local_entity_id, []).append({
            'project': target_project,
            'entity_id': target_entity_id,
            'similarity': similarity,
        })
        # Update entity's cross_project_links field
        entity = self._entities.get(local_entity_id)
        if entity:
            for link in self._cross_project[local_entity_id]:
                link_str = f"{link['project']}:{link['entity_id']}"
                if link_str not in entity.cross_project_links:
                    entity.cross_project_links.append(link_str)
            entity.touch()
            self._save_entity_file(entity)
            self._save_cross_project()

    def get_cross_project_links(self, entity_id: str) -> list[dict]:
        """Get cross-project links for an entity."""
        return self._cross_project.get(entity_id, [])

    def list_all_cross_links(self) -> list[dict]:
        """List all cross-project links."""
        links = []
        for local_id, link_list in self._cross_project.items():
            for link in link_list:
                links.append({
                    'local_entity': local_id,
                    **link,
                })
        return links

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
            "cross_project_links": sum(len(v) for v in self._cross_project.values()),
        }

    # --- Deduplication ---

    def dedup(self, threshold: float = 0.75) -> dict:
        """Deduplicate entities in this graph.

        Uses Levenshtein distance for name similarity.
        Returns summary of deduplication results.
        """
        from core.wiki.dedup import dedup_graph
        return dedup_graph(self, threshold)

    # --- Visualization ---

    def render_ascii(self, entity_id: str | None = None, depth: int = 2) -> str:
        """Render graph as ASCII tree diagram.

        Args:
            entity_id: Start from this entity (None = render all roots).
            depth: BFS depth limit.

        Returns:
            ASCII diagram string.
        """
        lines = []

        if entity_id:
            # Render from specific entity
            entity = self._entities.get(entity_id)
            if not entity:
                return f"Entity '{entity_id}' not found."
            lines.append(self._render_tree(entity_id, depth, prefix=""))
        else:
            # Render all roots (entities with no incoming edges)
            incoming = set()
            for edge in self._edges:
                incoming.add(edge.target)
            roots = [eid for eid in self._entities if eid not in incoming]
            if not roots:
                roots = list(self._entities.keys())[:10]  # Fallback

            for root_id in roots[:15]:  # Limit output
                entity = self._entities.get(root_id)
                if entity:
                    lines.append(f"{'=' * 60}")
                    lines.append(f"[{entity.entity_type.value}] {entity.name}")
                    if entity.summary:
                        lines.append(f"    {entity.summary[:100]}")
                    lines.append("")
                    lines.append(self._render_tree(root_id, depth, prefix=""))

        return chr(10).join(lines)

    def _render_tree(self, entity_id: str, depth: int, prefix: str) -> str:
        """Recursively render a tree from entity."""
        lines = []
        if depth <= 0:
            return lines

        neighbors = self.get_neighbors(entity_id)
        visited = set()

        for neighbor_id, edge_type, weight in neighbors:
            if neighbor_id in visited:
                continue
            visited.add(neighbor_id)

            entity = self._entities.get(neighbor_id)
            if not entity:
                continue

            connector = "├── " if len([n for n in neighbors if n[0] not in visited]) > 1 else "└── "
            lines.append(f"{prefix}{connector}[{entity.entity_type.value}] {entity.name} ({edge_type.value})")

            # Recurse for next level
            if depth > 1:
                sub_prefix = prefix + ("│   " if len([n for n in neighbors if n[0] not in visited]) > 1 else "    ")
                sub_lines = self._render_tree(neighbor_id, depth - 1, sub_prefix)
                lines.extend(sub_lines)

        return chr(10).join(lines)

    def render_mermaid(self, entity_id: str | None = None, depth: int = 2) -> str:
        """Render graph as Mermaid flowchart.

        Args:
            entity_id: Start from this entity (None = render all).
            depth: BFS depth limit.

        Returns:
            Mermaid diagram string.
        """
        lines = ["```mermaid", "graph TD"]
        edges_drawn = set()

        if entity_id:
            # Render from specific entity
            entity = self._entities.get(entity_id)
            if not entity:
                return f"Entity '{entity_id}' not found."
            self._add_mermaid_node(lines, entity_id, entity)
            self._add_mermaid_neighbors(lines, entity_id, depth, edges_drawn)
        else:
            # Render all
            for eid, entity in self._entities.items():
                self._add_mermaid_node(lines, eid, entity)
            for edge in self._edges:
                safe_src = self._mermaid_safe(edge.source)
                safe_tgt = self._mermaid_safe(edge.target)
                edge_key = f"{safe_src}--{edge.edge_type.value}-->{safe_tgt}"
                if edge_key not in edges_drawn:
                    lines.append(f"    {safe_src} -- \"{edge.edge_type.value}\" --> {safe_tgt}")
                    edges_drawn.add(edge_key)

        lines.append("```")
        return chr(10).join(lines)

    def _mermaid_safe(self, s: str) -> str:
        """Make a string safe for Mermaid node IDs."""
        return s.replace(':', '_').replace('/', '_').replace('-', '_').replace('.', '_')

    def _add_mermaid_node(self, lines: list[str], eid: str, entity: Entity) -> None:
        """Add a Mermaid node definition."""
        safe_id = self._mermaid_safe(eid)
        color = {
            EntityType.PROJECT: "fill:#e1f5fe,stroke:#01579b",
            EntityType.CONCEPT: "fill:#fff3e0,stroke:#e65100",
            EntityType.PATTERN: "fill:#f3e5f5,stroke:#6a1b9a",
            EntityType.TOOL: "fill:#e8f5e9,stroke:#2e7d32",
            EntityType.DATABASE: "fill:#fce4ec,stroke:#880e4f",
            EntityType.FRAMEWORK: "fill:#f1f8e9,stroke:#33691e",
            EntityType.API: "fill:#fff8e1,stroke:#ff6f00",
            EntityType.CONFIG: "fill:#f5f5f5,stroke:#616161",
        }.get(entity.entity_type, "fill:#fafafa,stroke:#9e9e9e")
        lines.append(f"    {safe_id}[\"{entity.name}\"] @{color}")

    def _add_mermaid_neighbors(self, lines: list[str], eid: str, depth: int, drawn: set, max_hops: int = 2) -> None:
        """Recursively add Mermaid edges for neighbors."""
        if max_hops <= 0:
            return
        for neighbor_id, edge_type, weight in self.get_neighbors(eid):
            safe_src = self._mermaid_safe(eid)
            safe_tgt = self._mermaid_safe(neighbor_id)
            edge_key = f"{safe_src}--{edge_type.value}-->{safe_tgt}"
            if edge_key not in drawn:
                lines.append(f"    {safe_src} -- \"{edge_type.value}\" --> {safe_tgt}")
                drawn.add(edge_key)
                self._add_mermaid_neighbors(lines, neighbor_id, depth, drawn, max_hops - 1)

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

    def _cross_project_file_path(self) -> Path:
        return self._base / "cross_links.json"

    def _save_edges(self) -> None:
        # Re-index: rebuild edges dict from entity files for consistency
        path = self._edges_file_path()
        path.write_text(json.dumps([e.to_dict() for e in self._edges], indent=2))

    def _save_cross_project(self) -> None:
        path = self._cross_project_file_path()
        path.write_text(json.dumps(self._cross_project, indent=2))

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

        # Load cross-project links
        cross_file = self._cross_project_file_path()
        if cross_file.exists():
            try:
                data = json.loads(cross_file.read_text())
                self._cross_project = data
            except Exception:
                self._cross_project = {}


    # --- Graph Query Language ---

    def query(self, query_str: str) -> list[dict]:
        """Parse and execute a graph query.
        
        Supports:
        - "show packages that depend on X"
        - "find classes with complexity > N"
        - "list entities of type X"
        - "what uses X?"
        - "show me all X"
        """
        results = []
        
        # Normalize query
        q = query_str.lower().strip()
        
        # Pattern: "what uses X?" / "what depends on X"
        import re
        depends_match = re.search(r'(what uses|what depends on|uses|depends on)\s+(.+?)[?.]?', q)
        if depends_match:
            target = depends_match.group(2).strip()
            for eid, entity in self._entities.items():
                if target.lower() in entity.name.lower():
                    incoming = self.get_edges(eid, direction="in")
                    if incoming:
                        for edge in incoming:
                            src = self.get_entity(edge.source)
                            if src:
                                results.append({
                                    'type': 'dependent',
                                    'entity': src.name,
                                    'entity_id': src.id,
                                    'edge_type': edge.edge_type.value,
                                    'target': entity.name,
                                })
            if results:
                return results
        
        # Pattern: "show packages that depend on X" / "packages that use X"
        packages_match = re.search(r'(packages|modules|libraries)\s+that\s+(depend|use)\s+on\s+(.+?)[?.]?', q)
        if packages_match:
            target = packages_match.group(3).strip()
            for eid, entity in self._entities.items():
                if entity.entity_type.value == 'concept' and target.lower() in entity.name.lower():
                    edges = self.get_edges(eid, direction="in")
                    if edges:
                        results.append({
                            'type': 'package',
                            'entity': entity.name,
                            'entity_id': eid,
                            'dependent_count': len(edges),
                        })
            return results
        
        # Pattern: "find classes with complexity > N" / "complex classes"
        complexity_match = re.search(r'(find|show|list)\s+(?:classes|functions|methods)\s+(?:with\s+)?(?:complexity\s*?>\s*(\d+)|complex)', q)
        if complexity_match:
            threshold = int(complexity_match.group(2)) if complexity_match.group(2) else 10
            for eid, entity in self._entities.items():
                complexity = entity.metadata.get('complexity', 0)
                if complexity > threshold:
                    results.append({
                        'type': 'complex_entity',
                        'entity': entity.name,
                        'entity_id': eid,
                        'complexity': complexity,
                    })
            return results
        
        # Pattern: "list entities of type X" / "show all X"
        type_match = re.search(r'(list|show|find)\s+(?:all\s+)?(?:entities|classes|modules|patterns)\s+(?:of\s+)?(?:type\s+)?(\w+)', q)
        if type_match:
            entity_type = type_match.group(2)
            for eid, entity in self._entities.items():
                if entity.entity_type.value == entity_type.lower():
                    results.append({
                        'type': 'entity',
                        'entity': entity.name,
                        'entity_id': eid,
                        'entity_type': entity.entity_type.value,
                    })
            return results
        
        # Pattern: "show me all X" / "show all X"
        all_match = re.search(r'show\s+(?:me\s+)?(?:all\s+)?(.+?)[?.]?', q)
        if all_match and not results:
            keyword = all_match.group(1).strip()
            for eid, entity in self._entities.items():
                if keyword.lower() in entity.name.lower() or keyword.lower() in entity.summary.lower():
                    results.append({
                        'type': 'entity',
                        'entity': entity.name,
                        'entity_id': eid,
                        'entity_type': entity.entity_type.value,
                    })
            return results
        
        # Default: search by name
        for eid, entity in self._entities.items():
            if any(word in entity.name.lower() for word in q.split() if len(word) > 2):
                results.append({
                    'type': 'entity',
                    'entity': entity.name,
                    'entity_id': eid,
                    'entity_type': entity.entity_type.value,
                })
        
        return results

    def query_as_markdown(self, query_str: str) -> str:
        """Execute a query and return formatted markdown."""
        results = self.query(query_str)
        if not results:
            return f"No results for query: `{query_str}`"
        
        lines = [f"## Query Results: `{query_str}`", ""]
        
        if results[0].get('type') == 'dependent':
            lines.append("| Entity | Type | Edge Type | Target |")
            lines.append("|--------|------|-----------|--------|")
            for r in results:
                lines.append(f"| [{r['entity']}]({r['entity_id']}) | entity | {r['edge_type']} | {r['target']} |")
        elif results[0].get('type') == 'complex_entity':
            lines.append("| Entity | Complexity |")
            lines.append("|--------|------------|")
            for r in sorted(results, key=lambda x: x['complexity'], reverse=True):
                lines.append(f"| [{r['entity']}]({r['entity_id']}) | {r['complexity']} |")
        else:
            lines.append("| Entity | Type | ID |")
            lines.append("|--------|------|----|")
            for r in results[:50]:
                lines.append(f"| {r.get('entity', '?')} | {r.get('entity_type', '?')} | {r.get('entity_id', '?')} |")
        
        return chr(10).join(lines)



    # --- Enhanced Visualization ---

    def render_enhanced_ascii(self, entity_id: str | None = None, depth: int = 2) -> str:
        """Enhanced ASCII diagram with risk coloring and edge details.
        
        Shows risk levels (complexity), edge types with labels,
        and cross-project links.
        """
        lines = []
        
        if entity_id:
            entity = self._entities.get(entity_id)
            if not entity:
                return f"Entity '{entity_id}' not found."
            
            lines.append(f"{'=' * 70}")
            lines.append(f"[{entity.entity_type.value.upper()}] {entity.name}")
            lines.append(f"  ID: {entity.id}")
            if entity.summary:
                lines.append(f"  Summary: {entity.summary[:120]}")
            
            # Show risk indicators
            complexity = entity.metadata.get('complexity', 0)
            hotspot = entity.metadata.get('hotspot_score', 0.0)
            if complexity > 10:
                lines.append(f"  ⚠️  High complexity: {complexity}")
            if hotspot > 0.5:
                lines.append(f"  🔥 Hotspot score: {hotspot:.2f}")
            
            lines.append(f"  Created: {entity.created_at[:19] if entity.created_at else 'unknown'}")
            lines.append(f"  Updated: {entity.updated_at[:19] if entity.updated_at else 'unknown'}")
            
            if entity.status.value != 'active':
                lines.append(f"  Status: {entity.status.value}")
                if entity.superseded_by:
                    lines.append(f"  Superseded by: {entity.superseded_by}")
            
            lines.append("")
            lines.append(self._render_enhanced_tree(entity_id, depth, prefix=""))
        else:
            # Render all with risk coloring
            incoming = set()
            for edge in self._edges:
                incoming.add(edge.target)
            roots = [eid for eid in self._entities if eid not in incoming]
            if not roots:
                roots = list(self._entities.keys())[:10]
            
            for i, root_id in enumerate(roots[:15]):
                entity = self._entities.get(root_id)
                if entity:
                    lines.append(f"{'=' * 70}")
                    complexity = entity.metadata.get('complexity', 0)
                    risk = "🔴" if complexity > 10 else "🟡" if complexity > 5 else "🟢"
                    lines.append(f"[{risk}] [{entity.entity_type.value}] {entity.name}")
                    if entity.summary:
                        lines.append(f"    {entity.summary[:100]}")
                    lines.append("")
                    lines.append(self._render_enhanced_tree(root_id, depth, prefix=""))
        
        return chr(10).join(lines)
    
    def _render_enhanced_tree(self, entity_id: str, depth: int, prefix: str) -> str:
        """Recursively render enhanced tree."""
        lines = []
        if depth <= 0:
            return lines
        
        neighbors = self.get_neighbors(entity_id)
        visited = set()
        
        for neighbor_id, edge_type, weight in neighbors:
            if neighbor_id in visited:
                continue
            visited.add(neighbor_id)
            
            entity = self._entities.get(neighbor_id)
            if not entity:
                continue
            
            complexity = entity.metadata.get('complexity', 0)
            risk = "🔴" if complexity > 10 else "🟡" if complexity > 5 else "🟢"
            connector = "├── " if len([n for n in neighbors if n[0] not in visited]) > 1 else "└── "
            
            lines.append(f"{prefix}{connector}[{risk}] [{entity.entity_type.value}] {entity.name} ({edge_type.value})")
            
            # Show edge weight as confidence
            if weight > 0.5:
                lines[-1] += f" [{weight:.0%}]"
            
            if depth > 1:
                sub_prefix = prefix + ("│   " if len([n for n in neighbors if n[0] not in visited]) > 1 else "    ")
                sub_lines = self._render_enhanced_tree(neighbor_id, depth - 1, sub_prefix)
                lines.extend(sub_lines)
        
        return chr(10).join(lines)
    
    def render_enhanced_mermaid(self, entity_id: str | None = None, depth: int = 2) -> str:
        """Enhanced Mermaid diagram with risk coloring and call chains."""
        lines = ["```mermaid", "graph TD"]
        edges_drawn = set()
        
        if entity_id:
            entity = self._entities.get(entity_id)
            if not entity:
                return f"Entity '{entity_id}' not found."
            self._add_mermaid_node(lines, entity_id, entity, enhanced=True)
            self._add_mermaid_neighbors(lines, entity_id, depth, edges_drawn, enhanced=True)
        else:
            for eid, entity in self._entities.items():
                self._add_mermaid_node(lines, eid, entity, enhanced=True)
            for edge in self._edges:
                safe_src = self._mermaid_safe(edge.source)
                safe_tgt = self._mermaid_safe(edge.target)
                edge_key = f"{safe_src}--{edge.edge_type.value}-->{safe_tgt}"
                if edge_key not in edges_drawn:
                    edge_text = f'{safe_src} -- {edge.edge_type.value} --> {safe_tgt}'
                    lines.append(f'    {edge_text}')
                    edges_drawn.add(edge_key)
        
        lines.append("```")
        return chr(10).join(lines)
    
    def _add_mermaid_node(self, lines: list[str], eid: str, entity: Entity, enhanced: bool = False) -> None:
        """Add Mermaid node with enhanced styling."""
        safe_id = self._mermaid_safe(eid)
        
        if enhanced:
            complexity = entity.metadata.get('complexity', 0)
            hotspot = entity.metadata.get('hotspot_score', 0.0)
            
            if hotspot > 0.7:
                color = "fill:#ffcccc,stroke:#ff0000,stroke-width:2px"
            elif complexity > 10:
                color = "fill:#fff3cd,stroke:#ffc107"
            elif complexity > 5:
                color = "fill:#d1e7dd,stroke:#198754"
            else:
                color = "fill:#f8f9fa,stroke:#6c757d"
        else:
            color = {
                EntityType.PROJECT: "fill:#e1f5fe,stroke:#01579b",
                EntityType.CONCEPT: "fill:#fff3e0,stroke:#e65100",
                EntityType.PATTERN: "fill:#f3e5f5,stroke:#6a1b9a",
                EntityType.TOOL: "fill:#e8f5e9,stroke:#2e7d32",
                EntityType.DATABASE: "fill:#fce4ec,stroke:#880e4f",
                EntityType.FRAMEWORK: "fill:#f1f8e9,stroke:#33691e",
                EntityType.API: "fill:#fff8e1,stroke:#ff6f00",
                EntityType.CONFIG: "fill:#f5f5f5,stroke:#616161",
            }.get(entity.entity_type, "fill:#fafafa,stroke:#9e9e9e")
        
        label = entity.name
        if enhanced and complexity > 5:
            label += f"\n(complexity: {complexity})"
        
        label_text = f'{safe_id}[{label}] @{color}'
        lines.append(f'    {label_text}')
    def _add_mermaid_neighbors(self, lines: list[str], eid: str, depth: int, drawn: set, max_hops: int = 2, enhanced: bool = False) -> None:
        """Recursively add Mermaid edges with enhanced styling."""
        if max_hops <= 0:
            return
        for neighbor_id, edge_type, weight in self.get_neighbors(eid):
            safe_src = self._mermaid_safe(eid)
            safe_tgt = self._mermaid_safe(neighbor_id)
            edge_key = f"{safe_src}--{edge_type.value}-->{safe_tgt}"
            if edge_key not in drawn:
                style = ""
                if enhanced and weight > 0.8:
                    style = ",stroke-width:2px"
                lines.append(f'    {safe_src} -- {edge_type.value}{style} --> {safe_tgt}')
                drawn.add(edge_key)
                self._add_mermaid_neighbors(lines, neighbor_id, depth, drawn, max_hops - 1, enhanced)

    def reset(self) -> None:
        """Clear all graph data."""
        import shutil
        self._entities.clear()
        self._edges.clear()
        self._cross_project.clear()
        # Remove all files
        if self._base.exists():
            shutil.rmtree(self._base)
        self._base.mkdir(parents=True, exist_ok=True)
