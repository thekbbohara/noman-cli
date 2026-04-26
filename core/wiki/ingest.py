"""Source ingestion for the wiki.

Parses conversations, files, and other sources to extract entities
and relations, then feeds them into the graph and wiki.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.wiki.graph import EdgeType, Entity, EntityType, Graph
from core.wiki.wiki import Wiki


@dataclass
class IngestionResult:
    """Result of ingesting a source."""
    entities: list[Entity]
    edges: list[tuple[str, str, EdgeType, str]]
    source_page_id: str
    page_ids_updated: list[str]


class Ingestor:
    """Extract entities and relations from raw content."""

    def __init__(self, wiki: Wiki) -> None:
        self._wiki = wiki

    def ingest_conversation(
        self,
        conversation_id: str,
        content: str,
        project_scope: str = "global",
    ) -> IngestionResult:
        """Ingest a conversation turn/summary.

        Extracts project names, tool names, file paths, concepts,
        and relationships between them.
        """
        entities: list[Entity] = []
        edges: list[tuple[str, str, EdgeType, str]] = []
        seen_ids: set[str] = set()

        # Extract project references (paths that look like projects)
        for match in re.finditer(r'`([^`]+/noman[^`]*)`', content):
            name = match.group(1)
            eid = f"project:{hash(name) & 0xFFFFFFFF:08x}"
            if eid not in seen_ids:
                entities.append(Entity(
                    id=eid,
                    name=name,
                    entity_type=EntityType.PROJECT,
                    scope=project_scope,
                    summary=f"Referenced in conversation {conversation_id}",
                ))
                seen_ids.add(eid)

        # Extract tool references
        for match in re.finditer(r'`([^`]+)`', content):
            name = match.group(1)
            # Skip paths and code snippets, focus on tool-like names
            if "/" not in name and len(name) > 2:
                eid = f"tool:{hash(name) & 0xFFFFFFFF:08x}"
                if eid not in seen_ids:
                    entities.append(Entity(
                        id=eid,
                        name=name,
                        entity_type=EntityType.TOOL,
                        scope=project_scope,
                        summary=f"Referenced as a tool in conversation {conversation_id}",
                    ))
                    seen_ids.add(eid)

        # Extract concept references (capitalized phrases)
        for match in re.finditer(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b', content):
            name = match.group(1).strip()
            if len(name) > 4 and len(name) < 80:
                eid = f"concept:{hash(name) & 0xFFFFFFFF:08x}"
                if eid not in seen_ids:
                    entities.append(Entity(
                        id=eid,
                        name=name,
                        entity_type=EntityType.CONCEPT,
                        scope=project_scope,
                        summary=f"Concept from conversation {conversation_id}",
                    ))
                    seen_ids.add(eid)

        # Create edges: tools used by projects, concepts related to projects
        for entity in entities:
            if entity.entity_type == EntityType.PROJECT:
                # Link tools referenced in the same conversation to this project
                for other in entities:
                    if other.entity_type == EntityType.TOOL:
                        edges.append((
                            entity.id, other.id,
                            EdgeType.USES,
                            f"Co-mentioned in {conversation_id}",
                        ))
            elif entity.entity_type == EntityType.TOOL:
                # Link tools to concepts
                for other in entities:
                    if other.entity_type == EntityType.CONCEPT:
                        edges.append((
                            entity.id, other.id,
                            EdgeType.REFERENCES,
                            f"Co-mentioned in {conversation_id}",
                        ))

        # Create source page
        source_page_id = f"source:conv:{conversation_id}"
        source_entity = Entity(
            id=source_page_id,
            name=f"Conversation {conversation_id}",
            entity_type=EntityType.PATTERN,
            scope=project_scope,
            summary=content[:500],
        )
        entities.append(source_entity)

        # Link source to all extracted entities
        for entity in entities:
            if entity.id != source_page_id:
                edges.append((
                    source_page_id, entity.id,
                    EdgeType.ORIGINATED_FROM,
                    f"Extracted from conversation {conversation_id}",
                ))

        # Feed into wiki
        page_ids = self._wiki.ingest_source(
            source_id=conversation_id,
            source_type="conversation",
            content=content,
            entities=entities,
            relations=edges,
        )

        return IngestionResult(
            entities=entities,
            edges=edges,
            source_page_id=source_page_id,
            page_ids_updated=page_ids,
        )

    def ingest_file(
        self,
        file_path: str,
        content: str,
        project_scope: str = "global",
    ) -> IngestionResult:
        """Ingest a file as a source."""
        entities: list[Entity] = []
        edges: list[tuple[str, str, EdgeType, str]] = []
        seen_ids: set[str] = set()

        # Extract class/function names
        for match in re.finditer(r'(?:class|def|function|fn)\s+(\w+)', content):
            name = match.group(1)
            eid = f"symbol:{hash(name) & 0xFFFFFFFF:08x}"
            if eid not in seen_ids:
                entities.append(Entity(
                    id=eid,
                    name=name,
                    entity_type=EntityType.CONCEPT,
                    scope=project_scope,
                    summary=f"Symbol in {file_path}",
                ))
                seen_ids.add(eid)

        # Extract file path references
        for match in re.finditer(r'`([^`]+\.py|[^`]+\.ts|[^`]+\.json)', content):
            path = match.group(1)
            eid = f"file:{hash(path) & 0xFFFFFFFF:08x}"
            if eid not in seen_ids:
                entities.append(Entity(
                    id=eid,
                    name=path,
                    entity_type=EntityType.CONFIG,
                    scope=project_scope,
                    summary=f"Referenced file",
                ))
                seen_ids.add(eid)

        # Source entity
        source_entity = Entity(
            id=f"source:file:{hash(file_path) & 0xFFFFFFFF:08x}",
            name=file_path,
            entity_type=EntityType.CONFIG,
            scope=project_scope,
            summary=content[:500],
        )
        entities.append(source_entity)

        for entity in entities:
            edges.append((
                source_entity.id, entity.id,
                EdgeType.ORIGINATED_FROM,
                f"Extracted from {file_path}",
            ))

        page_ids = self._wiki.ingest_source(
            source_id=file_path,
            source_type="file",
            content=content,
            entities=entities,
            relations=edges,
        )

        return IngestionResult(
            entities=entities,
            edges=edges,
            source_page_id=source_entity.id,
            page_ids_updated=page_ids,
        )
