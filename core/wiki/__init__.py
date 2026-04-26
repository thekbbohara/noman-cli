"""Knowledge graph / wiki subsystem.

Compiles cross-references and synthesis across conversations and projects.
Three-layer pattern: raw sources (immutable) -> wiki (markdown pages) -> schema (config).
"""

from core.wiki.graph import (
    Edge,
    EdgeType,
    Entity,
    EntityType,
    Graph,
)
from core.wiki.wiki import Wiki

__all__ = [
    "Edge",
    "EdgeType",
    "Entity",
    "EntityType",
    "Graph",
    "Wiki",
]
