"""Auto cross-project linking using semantic similarity.

Compares entities across projects and auto-links similar ones.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

from core.wiki.wiki import Wiki


def auto_link_cross_projects(wikis: dict[str, Wiki], threshold: float = 0.7) -> dict:
    """Auto-link similar entities across multiple wikis.
    
    Args:
        wikis: Dict of {project_name: Wiki}
        threshold: Minimum similarity to create link
        
    Returns:
        Summary of links created.
    """
    links = []
    
    # Get all entities from all wikis
    all_entities = []
    for project, wiki in wikis.items():
        for entity in wiki.graph.list_entities(limit=1000):
            all_entities.append({
                'project': project,
                'wiki': wiki,
                'entity': entity,
            })
    
    # Compare entities across projects
    for i, a in enumerate(all_entities):
        for j, b in enumerate(all_entities):
            if i >= j:
                continue
            if a['project'] == b['project']:
                continue  # Skip same project
            
            # Compute similarity
            sim = _compute_entity_similarity(a['entity'], b['entity'])
            
            if sim >= threshold:
                # Create cross-project link
                a['wiki'].link_cross_project(
                    a['entity'].id,
                    b['project'],
                    b['entity'].id,
                    sim,
                )
                b['wiki'].link_cross_project(
                    b['entity'].id,
                    a['project'],
                    a['entity'].id,
                    sim,
                )
                links.append({
                    'source': f"{a['project']}:{a['entity'].id}",
                    'target': f"{b['project']}:{b['entity'].id}",
                    'similarity': sim,
                })
    
    return {
        'links_created': len(links),
        'links': links[:50],  # Limit output
    }


def _compute_entity_similarity(e1, e2) -> float:
    """Compute similarity between two entities."""
    score = 0.0
    
    # Name similarity (weighted heavily)
    name1 = e1.name.lower()
    name2 = e2.name.lower()
    if name1 == name2:
        score += 0.5
    elif name2 in name1 or name1 in name2:
        score += 0.3
    else:
        # Levenshtein-based similarity
        max_len = max(len(name1), len(name2)) or 1
        distance = _levenshtein(name1, name2)
        score += 0.2 * (1 - distance / max_len)
    
    # Type match
    if e1.entity_type == e2.entity_type:
        score += 0.2
    
    # Summary similarity
    if e1.summary and e2.summary:
        words1 = set(e1.summary.lower().split())
        words2 = set(e2.summary.lower().split())
        if words1 and words2:
            overlap = len(words1 & words2) / max(len(words1), len(words2))
            score += 0.1 * overlap
    
    # Metadata similarity
    meta1 = e1.metadata or {}
    meta2 = e2.metadata or {}
    if meta1.get('complexity') == meta2.get('complexity'):
        score += 0.1
    
    return min(score, 1.0)


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

