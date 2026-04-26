"""Wiki tools — the agent-facing interface for the knowledge graph.

Tools follow the existing pattern: functions that take (bus, args) and
are registered as core.tools.bus.Tool objects.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from core.tools import ToolBus

# Module-level reference to the current bus (set during initialization)
_current_bus: ToolBus | None = None


def _get_bus() -> ToolBus | None:
    """Get the current tool bus."""
    return _current_bus


def _wiki_init(**kwargs: Any) -> str:
    """Initialize a knowledge graph for the current project.

    Scans the project directory, extracts entities (modules, tools, frameworks,
    languages, configs), creates edges between them, and populates the wiki.
    If a wiki already exists for this project, returns a summary of what's there.
    """
    from core.wiki.initializer import ProjectInitializer

    bus = _get_bus()
    if bus is None:
        return "Wiki not initialized."

    wiki = bus.wiki
    if not wiki:
        return "Wiki not initialized."

    cwd = Path.cwd()

    # Check if wiki already exists: look for project pages in the graph
    project_scope = str(cwd)
    existing_entities = wiki.graph.list_entities(scope=project_scope, limit=1)
    if existing_entities:
        entity_count = wiki.graph.count()
        edge_count = wiki.graph.edge_count()
        index = wiki.get_index()
        return (
            f"Wiki already initialized for this project.\n"
            f"  Entities: {entity_count} | Edges: {edge_count}\n"
            f"  Pages: {len(index)}\n"
            f"  Run wiki_lint to check health."
        )

    # Initialize the project wiki
    initializer = ProjectInitializer(wiki, cwd)
    summary = initializer.initialize()
    return summary


def _wiki_graph_summary() -> str:
    """Get a summary of the global knowledge graph."""
    bus = _get_bus()
    if bus is None:
        return "Wiki not initialized."
    wiki = bus.wiki
    if not wiki:
        return "Wiki not initialized."
    summary = wiki.graph.summarize()
    lines = [
        f"Graph summary: {summary['entity_count']} entities, {summary['edge_count']} edges",
        "Type breakdown:",
    ]
    for type_name, count in sorted(summary.get("type_counts", {}).items()):
        lines.append(f"  {type_name}: {count}")
    return "\n".join(lines)


def _wiki_list_entities(entity_type: str = "", scope: str = "", limit: int = 20) -> str:
    """List entities in the knowledge graph."""
    from core.wiki.graph import EntityType
    bus = _get_bus()
    if bus is None:
        return "Wiki not initialized."
    wiki = bus.wiki
    if not wiki:
        return "Wiki not initialized."

    et = None
    if entity_type:
        try:
            et = EntityType(entity_type)
        except ValueError:
            return f"Unknown entity type: {entity_type}"

    entities = wiki.graph.list_entities(entity_type=et, scope=scope if scope else None, limit=limit)
    if not entities:
        return "No entities found."

    lines = [f"Found {len(entities)} entities:"]
    for e in entities:
        lines.append(f"  [{e.entity_type.value}] {e.name} (scope={e.scope})")
        if e.summary:
            lines.append(f"    {e.summary[:120]}")
    return "\n".join(lines)


def _wiki_search_pages(query: str, limit: int = 10) -> str:
    """Search wiki pages by text content."""
    bus = _get_bus()
    if bus is None:
        return "Wiki not initialized."
    wiki = bus.wiki
    if not wiki:
        return "Wiki not initialized."

    pages = wiki.search_pages(query, limit=limit)
    if not pages:
        return "No pages found matching query."

    lines = [f"Found {len(pages)} pages:"]
    for p in pages:
        lines.append(f"  [{p.page_type}] {p.title}")
        if p.content:
            ql = query.lower()
            for line in p.content.split("\n"):
                if ql in line.lower():
                    lines.append(f"    ...{line.strip()[:150]}...")
                    break
    return "\n".join(lines)


def _wiki_get_page(page_id: str) -> str:
    """Get the full content of a wiki page."""
    bus = _get_bus()
    if bus is None:
        return "Wiki not initialized."
    wiki = bus.wiki
    if not wiki:
        return "Wiki not initialized."

    page = wiki.get_page(page_id)
    if not page:
        return f"Page '{page_id}' not found."

    lines = [
        f"# {page.title}",
        f"Type: {page.page_type}",
        f"Tags: {', '.join(page.tags)}",
        f"Sources: {page.source_count}",
        f"Updated: {page.updated_at}",
        "",
    ]
    if page.content:
        lines.append(page.content)
    if page.linked_pages:
        lines.append("\n## Linked Pages")
        for ref in page.linked_pages:
            lines.append(f"- [{ref}]")
    return "\n".join(lines)


def _wiki_query_graph(entity_id: str, depth: int = 2) -> str:
    """Query the knowledge graph: get neighbors of an entity."""
    bus = _get_bus()
    if bus is None:
        return "Wiki not initialized."
    wiki = bus.wiki
    if not wiki:
        return "Wiki not initialized."

    entity = wiki.graph.get_entity(entity_id)
    if not entity:
        return f"Entity '{entity_id}' not found."

    lines = [
        f"Entity: {entity.name} ({entity.entity_type.value})",
        f"Neighbors (depth {depth}):",
    ]

    neighbors = wiki.graph.get_neighbors(entity_id, max_depth=depth)
    if not neighbors:
        lines.append("  (none)")
    else:
        for neighbor_id, edge_type, weight in neighbors:
            neighbor = wiki.graph.get_entity(neighbor_id)
            name = neighbor.name if neighbor else neighbor_id
            lines.append(f"  [{edge_type.value}] {name} (weight={weight:.2f})")

    return "\n".join(lines)


def _wiki_lint() -> str:
    """Run health checks on the wiki."""
    bus = _get_bus()
    if bus is None:
        return "Wiki not initialized."
    wiki = bus.wiki
    if not wiki:
        return "Wiki not initialized."

    issues = wiki.lint()
    if not issues:
        return "Wiki health OK. No issues found."

    lines = [f"Wiki health: {len(issues)} issue(s):"]
    for issue in issues:
        lines.append(f"  [{issue['severity'].upper()}] {issue['message']}")
    return "\n".join(lines)


def _wiki_index() -> str:
    """Get the wiki index (catalog of all pages)."""
    bus = _get_bus()
    if bus is None:
        return "Wiki not initialized."
    wiki = bus.wiki
    if not wiki:
        return "Wiki not initialized."

    index = wiki.get_index()
    if not index:
        return "Wiki index is empty."

    lines = ["Wiki index:"]
    for entry in index:
        lines.append(
            f"  [{entry.get('type', '?')}] {entry.get('title', '?')} "
            f"(sources={entry.get('source_count', 0)}, updated={entry.get('updated', '?')})"
        )
    return "\n".join(lines)


def register_wiki_tools(bus: ToolBus) -> None:
    """Register all wiki tools with the tool bus."""
    # Set the module-level bus reference so wiki handlers can access it
    from core.wiki import tools as wiki_tools_module
    wiki_tools_module._current_bus = bus

    from core.tools import Tool

    bus.register(Tool(
        name="wiki_graph_summary",
        description="Get a summary of the knowledge graph: entity count, edge count, type breakdown.",
        parameters={"type": "object", "properties": {}},
        handler=_wiki_graph_summary,
        cost_estimate=50,
    ))
    bus.register(Tool(
        name="wiki_list_entities",
        description="List entities in the knowledge graph. Args: entity_type (filter), scope (filter), limit.",
        parameters={
            "type": "object",
            "properties": {
                "entity_type": {"type": "string"},
                "scope": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
            },
        },
        handler=_wiki_list_entities,
        cost_estimate=100,
    ))
    bus.register(Tool(
        name="wiki_search_pages",
        description="Search wiki pages by text content. Args: query (text), limit (max results).",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
        handler=_wiki_search_pages,
        cost_estimate=100,
    ))
    bus.register(Tool(
        name="wiki_get_page",
        description="Get the full content of a wiki page. Args: page_id.",
        parameters={
            "type": "object",
            "properties": {
                "page_id": {"type": "string"},
            },
            "required": ["page_id"],
        },
        handler=_wiki_get_page,
        cost_estimate=50,
    ))
    bus.register(Tool(
        name="wiki_query_graph",
        description="Query the knowledge graph: get neighbors of an entity. Args: entity_id, depth (1-3).",
        parameters={
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "depth": {"type": "integer", "default": 2},
            },
            "required": ["entity_id"],
        },
        handler=_wiki_query_graph,
        cost_estimate=100,
    ))
    bus.register(Tool(
        name="wiki_lint",
        description="Run health checks on the wiki. Returns issues found (orphaned pages, stale pages, etc.).",
        parameters={"type": "object", "properties": {}},
        handler=_wiki_lint,
        cost_estimate=50,
    ))
    bus.register(Tool(
        name="wiki_index",
        description="Get the wiki index (catalog of all wiki pages with metadata).",
        parameters={"type": "object", "properties": {}},
        handler=_wiki_index,
        cost_estimate=50,
    ))
    bus.register(Tool(
        name="wiki_init",
        description="Initialize a knowledge graph for the current project. Scans the project directory, extracts entities (modules, tools, frameworks, languages), creates edges between them, and populates the wiki. If a wiki already exists for this project, returns a summary of what's there.",
        parameters={"type": "object", "properties": {}},
        handler=_wiki_init,
        cost_estimate=500,
    ))
