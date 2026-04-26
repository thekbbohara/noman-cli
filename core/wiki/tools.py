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
from core.tools import Tool

# Module-level reference to the current bus (set during initialization)
_current_bus: ToolBus | None = None


def _get_bus() -> ToolBus | None:
    """Get the current tool bus."""
    return _current_bus


def _wiki_init(**kwargs: Any) -> str:
    """Initialize a knowledge graph for the current project."""
    from core.wiki.initializer import ProjectInitializer

    bus = _get_bus()
    if bus is None:
        return "Wiki not initialized."
    wiki = bus.wiki
    if not wiki:
        return "Wiki not initialized."

    cwd = Path.cwd()
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

    initializer = ProjectInitializer(wiki, cwd)
    summary = initializer.initialize()

    # Run auto-dedup
    dedup_result = wiki.dedup(threshold=0.75)
    if dedup_result['merged_count'] > 0:
        summary += f"\n  Dedup: merged {dedup_result['merged_count']} duplicates"

    return summary


def _wiki_graph_summary(**kwargs: Any) -> str:
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
    if summary.get("cross_project_links"):
        lines.append(f"  Cross-project links: {summary['cross_project_links']}")
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


def _wiki_semantic_search(query: str, limit: int = 10) -> str:
    """Search wiki pages using semantic similarity (conceptual matching)."""
    bus = _get_bus()
    if bus is None:
        return "Wiki not initialized."
    wiki = bus.wiki
    if not wiki:
        return "Wiki not initialized."

    results = wiki.semantic_search(query, limit=limit)
    if not results:
        return "No results found for semantic search."

    lines = [f"Semantic search for '{query}' ({len(results)} results):"]
    for r in results:
        page = r['page']
        score = r['score']
        lines.append(f"  [{page.page_type}] {page.title} (score={score:.3f})")
        if page.content:
            # Show most relevant snippet
            for line in page.content.split("\n"):
                if len(line.strip()) > 0:
                    lines.append(f"    ...{line.strip()[:120]}...")
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

    # Show cross-project links
    cross_links = wiki.get_cross_links(page_id)
    if cross_links:
        lines.append("\n## Cross-Project Links")
        for link in cross_links:
            lines.append(f"- [{link['project']}:{link['entity_id']}] (similarity={link['similarity']:.2f})")

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


def _wiki_lint(**kwargs: Any) -> str:
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


def _wiki_dedup(threshold: float = 0.75) -> str:
    """Run entity deduplication to merge similar entities."""
    bus = _get_bus()
    if bus is None:
        return "Wiki not initialized."
    wiki = bus.wiki
    if not wiki:
        return "Wiki not initialized."

    result = wiki.dedup(threshold=threshold)
    if result['merged_count'] == 0:
        return "Deduplication complete. No duplicates found."

    lines = [
        f"Deduplication complete: merged {result['merged_count']} duplicates",
        "Removed entities:",
    ]
    for rid in result['removed_ids']:
        lines.append(f"  - {rid}")
    return "\n".join(lines)


def _wiki_hotspots(threshold: float = 0.5, limit: int = 20) -> str:
    """List high-risk entities (complex + frequently changed)."""
    bus = _get_bus()
    if bus is None:
        return "Wiki not initialized."
    wiki = bus.wiki
    if not wiki:
        return "Wiki not initialized."

    hotspots = wiki.get_hotspots(threshold=threshold, limit=limit)
    if not hotspots:
        return "No hotspots found (no complexity/churn data)."

    lines = [f"Top {len(hotspots)} hotspots (risk score >= {threshold}):"]
    for h in hotspots:
        lines.append(
            f"  [{h['type']}] {h['name']} "
            f"(complexity={h['complexity']}, score={h['score']:.3f})"
        )
    return "\n".join(lines)


def _wiki_sync(**kwargs: Any) -> str:
    """Sync unindexed source files into the wiki.

    Scans the project directory for source files not yet in the wiki
    and creates entity entries for them. Useful for keeping the wiki
    up to date as the codebase changes.
    """
    from core.wiki.initializer import _get_package_structure, _safe_name

    bus = _get_bus()
    if bus is None:
        return "Wiki not initialized."
    wiki = bus.wiki
    if not wiki:
        return "Wiki not initialized."

    cwd = Path.cwd()
    synced = 0
    created = 0

    for src_dir in ['core', 'src', 'lib', 'app']:
        src_path = cwd / src_dir
        if not src_path.exists():
            continue

        packages = _get_package_structure(src_path, cwd)
        for pkg in packages:
            pkg_id = f"module:{_safe_name(pkg['path'])}"
            existing = wiki.graph.get_entity(pkg_id)
            if not existing:
                # Create entity
                summary_parts = [f"Package with {pkg['file_count']} Python files"]
                if pkg['classes']:
                    summary_parts.append(f"defines {len(pkg['classes'])} classes")
                    summary_parts.append(f"({', '.join(c['name'] for c in pkg['classes'][:5])})")
                if pkg.get('external_imports'):
                    summary_parts.append(f"imports from {len(pkg['external_imports'])} external modules")
                if pkg.get('total_complexity'):
                    summary_parts.append(f"complexity: {pkg['total_complexity']}")

                entity = wiki.graph.get_entity(pkg_id)
                if not entity:
                    from core.wiki.graph import Entity, EntityType
                    entity = Entity(
                        id=pkg_id,
                        name=pkg['name'],
                        entity_type=EntityType.CONCEPT,
                        scope=str(cwd),
                        summary='; '.join(summary_parts),
                        metadata={
                            'file_count': pkg['file_count'],
                            'class_count': len(pkg['classes']),
                            'function_count': len(pkg['functions']),
                            'complexity': pkg.get('total_complexity', 0),
                        },
                    )
                    wiki.graph.upsert_entity(entity)
                    wiki.upsert_page(wiki.entity_to_page(entity))
                    created += 1
                else:
                    # Update existing
                    entity.metadata['file_count'] = pkg['file_count']
                    entity.metadata['complexity'] = pkg.get('total_complexity', 0)
                    wiki.graph.upsert_entity(entity)
                    synced += 1

    return f"Sync complete: {created} created, {synced} updated"


def _wiki_index(**kwargs: Any) -> str:
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


def _wiki_render_ascii(entity_id: str = "", depth: int = 2) -> str:
    """Render the wiki graph as an ASCII diagram."""
    bus = _get_bus()
    if bus is None:
        return "Wiki not initialized."
    wiki = bus.wiki
    if not wiki:
        return "Wiki not initialized."

    eid = entity_id if entity_id else None
    return wiki.render_ascii_graph(eid, depth)


def _wiki_render_mermaid(entity_id: str = "", depth: int = 2) -> str:
    """Render the wiki graph as a Mermaid diagram."""
    bus = _get_bus()
    if bus is None:
        return "Wiki not initialized."
    wiki = bus.wiki
    if not wiki:
        return "Wiki not initialized."

    eid = entity_id if entity_id else None
    return wiki.render_mermaid_graph(eid, depth)


def _wiki_cross_links(**kwargs: Any) -> str:
    """List all cross-project links."""
    bus = _get_bus()
    if bus is None:
        return "Wiki not initialized."
    wiki = bus.wiki
    if not wiki:
        return "Wiki not initialized."

    links = wiki.list_all_cross_links()
    if not links:
        return "No cross-project links found."

    lines = ["Cross-project links:"]
    for link in links:
        lines.append(f"  {link['local_entity']} → [{link['project']}:{link['entity_id']}] (sim={link['similarity']:.2f})")
    return "\n".join(lines)


def _wiki_mention_counts(limit: int = 20) -> str:
    """List top entity mentions from conversations."""
    bus = _get_bus()
    if bus is None:
        return "Wiki not initialized."
    wiki = bus.wiki
    if not wiki:
        return "Wiki not initialized."

    from core.wiki.conversation import ConversationExtractor
    extractor = ConversationExtractor(wiki)
    mentions = extractor.get_mention_counts(limit=limit)

    if not mentions:
        return "No conversation mentions recorded."

    lines = ["Top entity mentions:"]
    for m in mentions:
        types = ', '.join(f"{k}:{v}" for k, v in m['types'].items())
        lines.append(f"  {m['name']} ({m['count']} mentions, {types})")
    return "\n".join(lines)




def _wiki_knowledge_query(query: str, limit: int = 20) -> str:
    """Natural language query about the knowledge graph.
    
    Supports queries like:
    - "what depends on X?"
    - "show me complex classes"
    - "find all packages that use security"
    - "what is the relationship between X and Y?"
    """
    bus = _get_bus()
    if bus is None:
        return "Wiki not initialized."
    wiki = bus.wiki
    if not wiki:
        return "Wiki not initialized."
    
    # Use graph query language
    results = wiki.graph.query(query)
    
    if not results:
        return f"No results for: `{query}`"
    
    lines = [f"## Knowledge Query: `{query}`", ""]
    
    # Format based on result type
    result_types = set(r.get('type') for r in results)
    
    if 'dependent' in result_types:
        lines.append("| Entity | Type | Edge Type | Target |")
        lines.append("|--------|------|-----------|--------|")
        for r in results:
            lines.append(f"| [{r['entity']}]({r['entity_id']}) | entity | {r['edge_type']} | {r['target']} |")
    elif 'complex_entity' in result_types:
        lines.append("| Entity | Complexity |")
        lines.append("|--------|------------|")
        for r in sorted(results, key=lambda x: x['complexity'], reverse=True):
            lines.append(f"| [{r['entity']}]({r['entity_id']}) | {r['complexity']} |")
    else:
        lines.append("| Entity | Type | ID |")
        lines.append("|--------|------|----|")
        for r in results[:limit]:
            lines.append(f"| {r.get('entity', '?')} | {r.get('entity_type', '?')} | {r.get('entity_id', '?')} |")
    
    return '\n'.join(lines)


def _wiki_knowledge_query_markdown(query: str, limit: int = 20) -> str:
    """Natural language query with markdown formatting."""
    bus = _get_bus()
    if bus is None:
        return "Wiki not initialized."
    wiki = bus.wiki
    if not wiki:
        return "Wiki not initialized."
    
    return wiki.graph.query_as_markdown(query)


def _wiki_context_summary(query: str, depth: int = 2) -> str:
    """Generate context-aware summary for a query.
    
    Selects most relevant entities for the given query/topic
    and formats them for injection into context.
    """
    bus = _get_bus()
    if bus is None:
        return "Wiki not initialized."
    wiki = bus.wiki
    if not wiki:
        return "Wiki not initialized."
    
    # Get relevant entities based on query
    query_words = set(query.lower().split())
    scores = []
    
    for eid, entity in wiki.graph._entities.items():
        score = 0.0
        name_lower = entity.name.lower()
        summary_lower = entity.summary.lower()
        
        for word in query_words:
            if len(word) < 3:
                continue
            if word in name_lower:
                score += 2.0
            if word in summary_lower:
                score += 1.0
            # Check for substring matches
            if word in name_lower.split('_') or word in name_lower.split(' '):
                score += 1.5
        
        # Boost for complexity
        complexity = entity.metadata.get('complexity', 0)
        score += min(complexity / 10.0, 1.0)
        
        if score > 0:
            scores.append((score, eid, entity))
    
    # Sort by score and take top N
    scores.sort(key=lambda x: x[0], reverse=True)
    top_entities = [s[2] for s in scores[:15]]
    
    if not top_entities:
        return f"No relevant entities for: `{query}`"
    
    lines = [f"## Context for: `{query}`", ""]
    lines.append(f"**{len(top_entities)} relevant entities:**")
    lines.append("")
    
    for entity in top_entities:
        complexity = entity.metadata.get('complexity', 0)
        risk = "🔴" if complexity > 10 else "🟡" if complexity > 5 else "🟢"
        lines.append(f"- {risk} **{entity.name}** (`{entity.id}`)")
        if entity.summary:
            lines.append(f"  - {entity.summary[:150]}")
        if complexity > 0:
            lines.append(f"  - complexity: {complexity}")
    
    # Show edges between top entities
    lines.append("")
    lines.append("**Connections:**")
    connections = set()
    for entity in top_entities:
        for neighbor_id, edge_type, weight in wiki.graph.get_neighbors(entity.id, max_depth=1):
            if neighbor_id in [e.id for e in top_entities]:
                key = (entity.id, neighbor_id)
                if key not in connections:
                    connections.add(key)
                    neighbor = wiki.graph.get_entity(neighbor_id)
                    if neighbor:
                        lines.append(f"- [{entity.name}] --[{edge_type.value}]--> [{neighbor.name}]")
    
    return '\n'.join(lines)



def _wiki_auto_link(**kwargs) -> str:
    """Auto-link similar entities across projects."""
    bus = _get_bus()
    if bus is None:
        return "Wiki not initialized."
    wiki = bus.wiki
    if not wiki:
        return "Wiki not initialized."
    
    from core.wiki.crosslink import auto_link_cross_projects
    threshold = kwargs.get('threshold', 0.7)
    
    # Get all wikis (global + any project wikis)
    wikis = {'global': wiki}
    
    result = auto_link_cross_projects(wikis, threshold)
    return f"Auto-linking complete: {result['links_created']} links created"


def _wiki_diff(version_a: str = "current", version_b: str = "current") -> str:
    """Compute diff between two wiki versions."""
    bus = _get_bus()
    if bus is None:
        return "Wiki not initialized."
    wiki = bus.wiki
    if not wiki:
        return "Wiki not initialized."
    
    from core.wiki.diff import compute_diff
    diff = compute_diff(wiki, version_a, version_b)
    
    lines = [
        f"## Wiki Diff: {version_a} → {version_b}",
        f"Timestamp: {diff['timestamp']}",
        "",
        f"Entity changes: +{diff['entity_changes']['added']} -{diff['entity_changes']['removed']} ~{diff['entity_changes']['changed']}",
        f"Edge changes: +{diff['edge_changes']['added']} -{diff['edge_changes']['removed']}",
        "",
    ]
    
    if diff['details']['added_entities']:
        lines.append("### Added Entities")
        for e in diff['details']['added_entities'][:10]:
            lines.append(f"- {e.get('name', e.get('id', '?'))}")
    
    if diff['details']['removed_entities']:
        lines.append("### Removed Entities")
        for e in diff['details']['removed_entities'][:10]:
            lines.append(f"- {e.get('name', e.get('id', '?'))}")
    
    if diff['details']['changed_entities']:
        lines.append("### Changed Entities")
        for c in diff['details']['changed_entities'][:10]:
            lines.append(f"- {c['name']}: {c['changes']}")
    
    return '\n'.join(lines)


def _wiki_enhanced_ascii(entity_id: str = "", depth: int = 2) -> str:
    """Enhanced ASCII diagram with risk coloring."""
    bus = _get_bus()
    if bus is None:
        return "Wiki not initialized."
    wiki = bus.wiki
    if not wiki:
        return "Wiki not initialized."
    
    eid = entity_id if entity_id else None
    return wiki.graph.render_enhanced_ascii(eid, depth)


def _wiki_enhanced_mermaid(entity_id: str = "", depth: int = 2) -> str:
    """Enhanced Mermaid diagram with risk coloring."""
    bus = _get_bus()
    if bus is None:
        return "Wiki not initialized."
    wiki = bus.wiki
    if not wiki:
        return "Wiki not initialized."
    
    eid = entity_id if entity_id else None
    return wiki.graph.render_enhanced_mermaid(eid, depth)


def _wiki_auto_extract(path: str = "") -> str:
    """Auto-extract entities from source files."""
    bus = _get_bus()
    if bus is None:
        return "Wiki not initialized."
    wiki = bus.wiki
    if not wiki:
        return "Wiki not initialized."
    
    from core.wiki.auto_extract import auto_extract_directory
    
    cwd = Path.cwd()
    if path:
        project_path = Path(path)
    else:
        project_path = cwd
    
    result = auto_extract_directory(project_path, wiki)
    
    lines = [
        "Auto-extraction complete:",
        f"  Created: {len(result['created'])} entities",
        f"  Updated: {len(result['updated'])} entities",
        f"  Skipped: {len(result['skipped'])} files",
        f"  Errors: {len(result['errors'])}",
    ]
    
    if result['errors']:
        lines.append("Errors:")
        for err in result['errors'][:5]:
            lines.append(f"  - {err}")
    
    return '\n'.join(lines)


def _wiki_save_version(version_name: str) -> str:
    """Save current wiki state as a version."""
    bus = _get_bus()
    if bus is None:
        return "Wiki not initialized."
    wiki = bus.wiki
    if not wiki:
        return "Wiki not initialized."
    
    # Save version data
    entities = [e.to_dict() for e in wiki.graph.list_entities(limit=10000)]
    edges = [e.to_dict() for e in wiki.graph.get_all_edges()]
    
    version_file = wiki._base / f"version_{version_name}.json"
    version_file.write_text(json.dumps({
        'version': version_name,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'entities': entities,
        'edges': edges,
    }, indent=2))
    
    return f"Version '{version_name}' saved with {len(entities)} entities and {len(edges)} edges"

def register_wiki_tools(bus: ToolBus) -> None:
    """Register all wiki tools with the tool bus."""
    from core.wiki import tools as wiki_tools_module
    wiki_tools_module._current_bus = bus

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
        name="wiki_semantic_search",
        description="Search wiki pages using semantic similarity (conceptual matching). Finds related concepts even with different words. Args: query, limit.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
        handler=_wiki_semantic_search,
        cost_estimate=200,
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
        description="Initialize a knowledge graph for the current project. Scans the project directory, extracts entities (modules, classes, functions, imports), creates dependency edges, and populates the wiki. Also runs auto-deduplication.",
        parameters={"type": "object", "properties": {}},
        handler=_wiki_init,
        cost_estimate=500,
    ))
    bus.register(Tool(
        name="wiki_dedup",
        description="Run entity deduplication. Merges entities with similar names (using Levenshtein distance) within the same scope. Args: threshold (0.0-1.0, default 0.75).",
        parameters={
            "type": "object",
            "properties": {
                "threshold": {"type": "number", "default": 0.75},
            },
        },
        handler=_wiki_dedup,
        cost_estimate=200,
    ))
    bus.register(Tool(
        name="wiki_hotspots",
        description="List high-risk entities (complex and frequently changed code). Args: threshold (default 0.5), limit (default 20).",
        parameters={
            "type": "object",
            "properties": {
                "threshold": {"type": "number", "default": 0.5},
                "limit": {"type": "integer", "default": 20},
            },
        },
        handler=_wiki_hotspots,
        cost_estimate=100,
    ))
    bus.register(Tool(
        name="wiki_sync",
        description="Sync unindexed source files into the wiki. Scans source directories and creates entity entries for files not yet in the wiki.",
        parameters={"type": "object", "properties": {}},
        handler=_wiki_sync,
        cost_estimate=300,
    ))
    bus.register(Tool(
        name="wiki_render_ascii",
        description="Render the wiki graph as an ASCII tree diagram. Args: entity_id (optional, start from), depth (default 2).",
        parameters={
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "depth": {"type": "integer", "default": 2},
            },
        },
        handler=_wiki_render_ascii,
        cost_estimate=100,
    ))
    bus.register(Tool(
        name="wiki_render_mermaid",
        description="Render the wiki graph as a Mermaid flowchart diagram. Args: entity_id (optional), depth (default 2).",
        parameters={
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "depth": {"type": "integer", "default": 2},
            },
        },
        handler=_wiki_render_mermaid,
        cost_estimate=100,
    ))
    bus.register(Tool(
        name="wiki_cross_links",
        description="List all cross-project links between entities.",
        parameters={"type": "object", "properties": {}},
        handler=_wiki_cross_links,
        cost_estimate=50,
    ))
    bus.register(Tool(
        name="wiki_mention_counts",
        description="List top entity mentions from conversations (auto-extracted). Args: limit.",
        parameters={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 20},
            },
        },
        handler=_wiki_mention_counts,
        cost_estimate=50,
    )),

    # Knowledge graph query tools
    bus.register(Tool(
        name="wiki_knowledge_query",
        description="Natural language query about the knowledge graph. Supports: 'what depends on X?', 'show me complex classes', 'find all packages that use X', 'relationship between X and Y'. Args: query, limit.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
            },
            "required": ["query"],
        },
        handler=_wiki_knowledge_query,
        cost_estimate=200,
    ))
    bus.register(Tool(
        name="wiki_knowledge_query_markdown",
        description="Natural language query with markdown table formatting. Same as wiki_knowledge_query but returns formatted tables.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
            },
            "required": ["query"],
        },
        handler=_wiki_knowledge_query_markdown,
        cost_estimate=200,
    ))
    bus.register(Tool(
        name="wiki_context_summary",
        description="Generate context-aware summary for a given topic. Selects most relevant entities from the knowledge graph for injection into context.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "depth": {"type": "integer", "default": 2},
            },
            "required": ["query"],
        },
        handler=_wiki_context_summary,
        cost_estimate=300,
    ))
    bus.register(Tool(
        name="wiki_auto_link",
        description="Auto-link similar entities across multiple projects using name and content similarity.",
        parameters={
            "type": "object",
            "properties": {
                "threshold": {"type": "number", "default": 0.7},
            },
        },
        handler=_wiki_auto_link,
        cost_estimate=500,
    ))
    bus.register(Tool(
        name="wiki_diff",
        description="Compute diff between two wiki versions. Shows added/removed/changed entities and edges. Args: version_a, version_b (or 'current').",
        parameters={
            "type": "object",
            "properties": {
                "version_a": {"type": "string"},
                "version_b": {"type": "string"},
            },
        },
        handler=_wiki_diff,
        cost_estimate=300,
    ))
    bus.register(Tool(
        name="wiki_enhanced_ascii",
        description="Enhanced ASCII diagram with risk coloring (complexity-based) and edge weights.",
        parameters={
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "depth": {"type": "integer", "default": 2},
            },
        },
        handler=_wiki_enhanced_ascii,
        cost_estimate=100,
    ))
    bus.register(Tool(
        name="wiki_enhanced_mermaid",
        description="Enhanced Mermaid diagram with risk coloring and call chain annotations.",
        parameters={
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "depth": {"type": "integer", "default": 2},
            },
        },
        handler=_wiki_enhanced_mermaid,
        cost_estimate=100,
    ))
    bus.register(Tool(
        name="wiki_auto_extract",
        description="Auto-extract entities from source files without manual init. Useful for quick extraction of unindexed files.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
            },
        },
        handler=_wiki_auto_extract,
        cost_estimate=200,
    ))
    bus.register(Tool(
        name="wiki_save_version",
        description="Save current wiki state as a version for diff tracking. Args: version_name.",
        parameters={
            "type": "object",
            "properties": {
                "version_name": {"type": "string"},
            },
            "required": ["version_name"],
        },
        handler=_wiki_save_version,
        cost_estimate=50,
    ))
