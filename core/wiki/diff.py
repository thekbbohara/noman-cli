"""Wiki diff tracking between versions.

Tracks changes between wiki versions for auditing and comparison.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def compute_diff(wiki, version_a: str, version_b: str | None = None) -> dict:
    """Compute diff between two wiki versions.
    
    Args:
        wiki: Wiki instance
        version_a: First version string (or "current")
        version_b: Second version string (or "current")
        
    Returns:
        Diff summary with added/removed/changed entities and edges.
    """
    # Load both versions
    if version_a == "current":
        entities_a = _load_version_entities(wiki)
        edges_a = wiki.graph.get_all_edges()
    else:
        entities_a, edges_a = _load_version_from_file(wiki, version_a)
    
    if version_b == "current":
        entities_b = _load_version_entities(wiki)
        edges_b = wiki.graph.get_all_edges()
    else:
        entities_b, edges_b = _load_version_from_file(wiki, version_b)
    
    # Compare entities
    ids_a = {e['id'] for e in entities_a}
    ids_b = {e['id'] for e in entities_b}
    
    added = [e for e in entities_b if e['id'] not in ids_a]
    removed = [e for e in entities_a if e['id'] not in ids_b]
    
    # Find changed entities (same id, different content)
    entity_map_a = {e['id']: e for e in entities_a}
    entity_map_b = {e['id']: e for e in entities_b}
    changed = []
    for eid in ids_a & ids_b:
        a_data = entity_map_a[eid]
        b_data = entity_map_b[eid]
        if a_data.get('summary') != b_data.get('summary') or a_data.get('metadata') != b_data.get('metadata'):
            changed.append({
                'id': eid,
                'name': b_data.get('name', eid),
                'changes': _compute_entity_changes(a_data, b_data),
            })
    
    # Compare edges — normalize Edge objects to tuples for comparison
    def _edge_to_tuple(e):
        if hasattr(e, 'to_dict'):
            d = e.to_dict()
            return (d['source'], d['target'], d['edge_type'])
        if isinstance(e, dict):
            return (e['source'], e['target'], e['edge_type'])
        return (e.source, e.target, e.edge_type)

    edges_set_a = {_edge_to_tuple(e) for e in edges_a}
    edges_set_b = {_edge_to_tuple(e) for e in edges_b}
    
    edges_added = [e for e in edges_b if _edge_to_tuple(e) not in edges_set_a]
    edges_removed = [e for e in edges_a if _edge_to_tuple(e) not in edges_set_b]
    
    return {
        'version_a': version_a,
        'version_b': version_b,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'entity_changes': {
            'added': len(added),
            'removed': len(removed),
            'changed': len(changed),
        },
        'edge_changes': {
            'added': len(edges_added),
            'removed': len(edges_removed),
        },
        'details': {
            'added_entities': added[:20],
            'removed_entities': removed[:20],
            'changed_entities': changed[:20],
            'added_edges': edges_added[:20],
            'removed_edges': edges_removed[:20],
        },
    }


def _compute_entity_changes(a: dict, b: dict) -> dict:
    """Compute detailed changes between two entity versions."""
    changes = {}
    
    if a.get('name') != b.get('name'):
        changes['name'] = {'from': a.get('name'), 'to': b.get('name')}
    
    if a.get('entity_type') != b.get('entity_type'):
        changes['type'] = {'from': a.get('entity_type'), 'to': b.get('entity_type')}
    
    if a.get('summary') != b.get('summary'):
        changes['summary'] = {'from': a.get('summary', '')[:100], 'to': b.get('summary', '')[:100]}
    
    if a.get('metadata') != b.get('metadata'):
        changes['metadata'] = {'from': a.get('metadata'), 'to': b.get('metadata')}
    
    return changes


def _load_version_entities(wiki) -> list[dict]:
    """Load current entities from wiki as serializable dicts."""
    entities = []
    for entity in wiki.graph.list_entities(limit=10000):
        entities.append(entity.to_dict())
    return entities


def _load_version_from_file(wiki, version: str) -> tuple[list[dict], list[dict]]:
    """Load entity and edge data from a saved version file."""
    version_file = wiki._base / f"version_{version}.json"
    if version_file.exists():
        try:
            data = json.loads(version_file.read_text())
            return data.get('entities', []), data.get('edges', [])
        except Exception:
            pass
    return [], []

