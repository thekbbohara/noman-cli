"""Entity deduplication for the knowledge graph.

Finds and merges near-duplicate entities based on name similarity
(Levenshtein distance) and scope matching. Merges metadata, edges,
and keeps the most recently updated entity.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.wiki.graph import Edge, EdgeType, Entity, EntityType, Graph


def _levenshtein(a: str, b: str) -> int:
    """Compute Levenshtein distance between two strings."""
    if len(a) < len(b):
        return _levenshtein(b, a)
    if len(b) == 0:
        return len(a)
    prev_row = range(len(b) + 1)
    for i, ca in enumerate(a):
        curr_row = [i + 1]
        for j, cb in enumerate(b):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (ca != cb)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row
    return prev_row[-1]


def _name_similarity(a: str, b: str) -> float:
    """Compute name similarity score (0.0 to 1.0)."""
    a_norm = a.lower().replace(' ', '_').replace('-', '_')
    b_norm = b.lower().replace(' ', '_').replace('-', '_')
    if a_norm == b_norm:
        return 1.0
    distance = _levenshtein(a_norm, b_norm)
    max_len = max(len(a_norm), len(b_norm))
    if max_len == 0:
        return 1.0
    return 1.0 - (distance / max_len)


def dedup_graph(graph: Graph, threshold: float = 0.75) -> dict:
    """Deduplicate entities in the graph.

    Finds entities with similar names within the same scope,
    merges their metadata and edges, and keeps the most recently
    updated entity.

    Args:
        graph: The knowledge graph to deduplicate.
        threshold: Minimum name similarity to consider as duplicate.

    Returns:
        Summary of deduplication results.
    """
    entities = graph.list_entities(limit=1000)
    merged_count = 0
    skipped_count = 0
    kept: dict[str, Entity] = {}
    removed_ids: list[str] = []

    # Group entities by scope
    by_scope: dict[str, list[Entity]] = {}
    for e in entities:
        scope = e.scope or "global"
        by_scope.setdefault(scope, []).append(e)

    for scope, scope_entities in by_scope.items():
        for i, entity in enumerate(scope_entities):
            if entity.id in kept:
                continue  # Already merged into another entity

            candidates = []
            for j, other in enumerate(scope_entities):
                if i == j:
                    continue
                if other.id in kept:
                    continue
                sim = _name_similarity(entity.name, other.name)
                if sim >= threshold:
                    candidates.append((other, sim))

            if not candidates:
                kept[entity.id] = entity
                continue

            # Merge all candidates into the entity with highest similarity
            candidates.sort(key=lambda x: x[1], reverse=True)
            best_target, best_sim = candidates[0]

            # Merge metadata
            merged_metadata = dict(entity.metadata)
            merged_metadata.update(best_target.metadata)
            merged_metadata.setdefault('merged_from', []).append(best_target.id)
            merged_metadata['merged_from'].append(entity.id)

            # Merge edges: collect all edges for the removed entity
            removed_edges = graph.get_edges(best_target.id, direction="both")

            # Update the kept entity
            updated = Entity(
                id=entity.id,
                name=entity.name,
                entity_type=entity.entity_type,
                scope=scope,
                summary=entity.summary or best_target.summary,
                metadata=merged_metadata,
                created_at=entity.created_at,
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
            kept[entity.id] = updated

            # Remove the duplicate
            removed_ids.append(best_target.id)
            graph.remove_entity(best_target.id)

            # Re-add edges that pointed to the removed entity
            for edge in removed_edges:
                if edge.source == best_target.id:
                    graph.add_edge(entity.id, edge.target, edge.edge_type, edge.weight,
                                   f"Edge remapped from {best_target.id}")
                if edge.target == best_target.id:
                    graph.add_edge(edge.source, entity.id, edge.edge_type, edge.weight,
                                   f"Edge remapped to {entity.id}")

            merged_count += 1

    return {
        'merged_count': merged_count,
        'removed_ids': removed_ids,
        'kept_count': len(kept),
    }
