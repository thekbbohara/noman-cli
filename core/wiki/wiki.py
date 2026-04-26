"""Wiki engine — manages markdown pages, index, and changelog.

The wiki layer sits between raw sources and the knowledge graph.
It maintains a collection of markdown pages (entity pages, concept pages,
summaries) with cross-references, an index for navigation, and a log
for tracking all wiki events.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.wiki.graph import EdgeType, Entity, EntityType, Graph


@dataclass
class WikiPage:
    """A single wiki page."""
    id: str
    title: str
    page_type: str  # "entity", "concept", "summary", "comparison", "overview"
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    linked_pages: list[str] = field(default_factory=list)  # wiki page ids
    source_count: int = 0
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

    def to_frontmatter(self) -> str:
        """Generate YAML-like frontmatter."""
        lines = [
            "---",
            f"title: {self.title}",
            f"type: {self.page_type}",
            f"tags: [{', '.join(self.tags)}]",
            f"sources: {self.source_count}",
            f"linked: [{', '.join(self.linked_pages)}]",
            f"created: {self.created_at}",
            f"updated: {self.updated_at}",
            "---",
        ]
        return "\n".join(lines)

    def to_markdown(self) -> str:
        """Serialize page to markdown with frontmatter."""
        lines = [self.to_frontmatter(), "", f"# {self.title}", ""]
        if self.content:
            lines.append(self.content)
            lines.append("")
        if self.linked_pages:
            lines.append("## See Also")
            lines.append("")
            for ref in self.linked_pages:
                lines.append(f"- [[{ref}]]")
            lines.append("")
        return "\n".join(lines)

    @classmethod
    def from_markdown(cls, content: str, page_id: str) -> WikiPage:
        """Parse a wiki page from markdown content."""
        title = page_id
        page_type = "entity"
        tags = []
        source_count = 0
        linked_pages = []
        body = content

        # Extract frontmatter
        fm_match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        if fm_match:
            fm_text = fm_match.group(1)
            body = content[fm_match.end():].strip()
            for line in fm_text.split("\n"):
                if ":" in line:
                    key, val = line.split(":", 1)
                    key = key.strip().lower()
                    val = val.strip()
                    if key == "title":
                        title = val
                    elif key == "type":
                        page_type = val
                    elif key == "tags":
                        tags = [t.strip() for t in val.strip("[]").split(",") if t.strip()]
                    elif key == "sources":
                        try:
                            source_count = int(val)
                        except ValueError:
                            source_count = 0
                    elif key == "linked":
                        linked_pages = [t.strip() for t in val.strip("[]").split(",") if t.strip()]

        return cls(
            id=page_id,
            title=title,
            page_type=page_type,
            content=body,
            metadata={},
            tags=tags,
            linked_pages=linked_pages,
            source_count=source_count,
        )


class Wiki:
    """Wiki engine — manages pages, index, and log.

    Each wiki instance is scoped to a single directory (global or project).
    Pages are stored as markdown files. The index is a single JSON file.
    The log is an append-only markdown file.
    """

    def __init__(self, base_path: str | Path, graph: Graph | None = None) -> None:
        self._base = Path(base_path)
        self._base.mkdir(parents=True, exist_ok=True)
        self._graph = graph or Graph(self._base)
        self._pages: dict[str, WikiPage] = {}
        self._index_path = self._base / "index.json"
        self._log_path = self._base / "log.md"
        self._load_pages()

    @property
    def graph(self) -> Graph:
        return self._graph

    # --- Page CRUD ---

    def get_page(self, page_id: str) -> WikiPage | None:
        return self._pages.get(page_id)

    def upsert_page(self, page: WikiPage) -> None:
        page.touch()
        self._pages[page.id] = page
        self._save_page_file(page)
        self._update_index()

    def remove_page(self, page_id: str) -> bool:
        if page_id not in self._pages:
            return False
        del self._pages[page_id]
        fpath = self._page_file_path(page_id)
        if fpath.exists():
            fpath.unlink()
        self._update_index()
        return True

    def list_pages(
        self,
        page_type: str | None = None,
        tag: str | None = None,
        limit: int = 50,
    ) -> list[WikiPage]:
        pages = list(self._pages.values())
        if page_type:
            pages = [p for p in pages if p.page_type == page_type]
        if tag:
            pages = [p for p in pages if tag in p.tags]
        pages.sort(key=lambda p: p.updated_at, reverse=True)
        return pages[:limit]

    def search_pages(
        self,
        query: str,
        limit: int = 20,
    ) -> list[WikiPage]:
        """Simple text search across page titles and content."""
        query_lower = query.lower()
        results = []
        for page in self._pages.values():
            score = 0
            if query_lower in page.title.lower():
                score += 10
            if query_lower in page.content.lower():
                score += 1
            if score > 0:
                results.append((score, page))
        results.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in results[:limit]]

    # --- Graph integration ---

    def entity_to_page(self, entity: Entity) -> WikiPage:
        """Convert a graph entity to a wiki page."""
        return WikiPage(
            id=entity.id,
            title=entity.name,
            page_type="entity",
            content=entity.summary,
            tags=[entity.entity_type.value],
            source_count=len(self._graph.get_edges(entity.id)),
        )

    def page_to_entity(self, page: WikiPage) -> Entity:
        """Convert a wiki page to a graph entity."""
        return Entity(
            id=page.id,
            name=page.title,
            entity_type=EntityType(page.page_type) if page.page_type in EntityType._value2member_map_ else EntityType.UNKNOWN,
            scope="global",
            summary=page.content,
        )

    # --- Index ---

    def _update_index(self) -> None:
        """Rebuild the index from current pages."""
        index_entries = []
        for page in self._pages.values():
            index_entries.append({
                "id": page.id,
                "title": page.title,
                "type": page.page_type,
                "tags": page.tags,
                "source_count": page.source_count,
                "updated": page.updated_at,
                "summary": page.content[:200] if page.content else "",
            })
        self._index_path.write_text(json.dumps(index_entries, indent=2))

    def get_index(self) -> list[dict]:
        if self._index_path.exists():
            return json.loads(self._index_path.read_text())
        return []

    # --- Log ---

    def log_event(
        self,
        event_type: str,
        detail: str,
        page_id: str = "",
    ) -> None:
        """Append an event to the changelog."""
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        entry = f"## [{ts}] {event_type}"
        if page_id:
            entry += f" | page: {page_id}"
        entry += f"\n\n{detail}\n"
        if self._log_path.exists():
            existing = self._log_path.read_text()
            self._log_path.write_text(existing + entry)
        else:
            self._log_path.write_text(entry)

    def get_log(self, last_n: int = 20) -> list[str]:
        """Get the last N log entries."""
        if not self._log_path.exists():
            return []
        content = self._log_path.read_text()
        entries = re.split(r"## \[", content)
        entries = [f"## [{e}" for e in entries[1:] if e.strip()]  # skip empty first split
        return entries[-last_n:]

    # --- Ingest ---

    def ingest_source(
        self,
        source_id: str,
        source_type: str,
        content: str,
        entities: list[Entity],
        relations: list[tuple[str, str, EdgeType, str]],
    ) -> list[str]:
        """Ingest a new source and update the wiki.

        Args:
            source_id: unique identifier for the source
            source_type: "conversation", "file", "article", "config", etc.
            content: the source content
            entities: entities extracted from the source
            relations: (source_entity_id, target_entity_id, edge_type, evidence)

        Returns:
            List of page IDs that were updated.
        """
        updated_pages: list[str] = []

        # Upsert entities in graph
        for entity in entities:
            self._graph.upsert_entity(entity)
            # Create or update wiki page for entity
            page = self.entity_to_page(entity)
            self.upsert_page(page)
            updated_pages.append(entity.id)

        # Create source page
        source_page = WikiPage(
            id=f"source:{source_id}",
            title=f"Source: {source_type}",
            page_type="source",
            content=content[:5000],  # cap content
            tags=[f"type:{source_type}"],
        )
        self.upsert_page(source_page)

        # Create edges
        for src_id, tgt_id, edge_type, evidence in relations:
            self._graph.add_edge(src_id, tgt_id, edge_type, evidence=evidence)
            # Cross-reference in pages
            for eid in (src_id, tgt_id):
                if eid in self._pages:
                    other = tgt_id if eid == src_id else src_id
                    if other not in self._pages[eid].linked_pages:
                        self._pages[eid].linked_pages.append(other)
                        self._save_page_file(self._pages[eid])

        self._log_event("ingest", f"Source {source_id} ingested, {len(entities)} entities, {len(relations)} relations")
        return updated_pages

    # --- Lint ---

    def lint(self) -> list[dict]:
        """Run health checks. Returns list of issues found."""
        issues: list[dict] = []

        # Check for entities without wiki pages
        for entity_id in self._graph.list_entities():
            if entity_id not in self._pages:
                issues.append({
                    "severity": "warning",
                    "message": f"Entity '{entity_id}' has no wiki page",
                    "entity": entity_id,
                })

        # Check for pages without entities
        for page_id in self._pages:
            if page_id not in self._graph.list_entities():
                issues.append({
                    "severity": "info",
                    "message": f"Page '{page_id}' has no corresponding graph entity",
                    "page": page_id,
                })

        # Check for orphan pages (no edges, no linked pages)
        for page_id, page in self._pages.items():
            if page.page_type == "source":
                continue
            edges = self._graph.get_edges(page_id)
            if not edges and not page.linked_pages:
                issues.append({
                    "severity": "info",
                    "message": f"Page '{page_id}' is orphaned (no graph edges or links)",
                    "page": page_id,
                })

        # Check for very old pages
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        for page_id, page in self._pages.items():
            try:
                updated = datetime.fromisoformat(page.updated_at)
                if (now - updated).days > 180:
                    issues.append({
                        "severity": "info",
                        "message": f"Page '{page_id}' last updated {updated.strftime('%Y-%m-%d')} (>180 days ago)",
                        "page": page_id,
                    })
            except Exception:
                pass

        return issues

    # --- Persistence ---

    def _page_file_path(self, page_id: str) -> Path:
        # Sanitize page_id for filesystem
        safe_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", page_id)
        return self._base / "pages" / f"{safe_id}.md"

    def _save_page_file(self, page: WikiPage) -> None:
        path = self._page_file_path(page.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(page.to_markdown())

    def _load_pages(self) -> None:
        pages_dir = self._base / "pages"
        if pages_dir.exists():
            for f in pages_dir.glob("*.md"):
                try:
                    content = f.read_text()
                    page_id = f.stem
                    page = WikiPage.from_markdown(content, page_id)
                    self._pages[page.id] = page
                except Exception:
                    continue

    def _log_event(self, event_type: str, detail: str, page_id: str = "") -> None:
        self.log_event(event_type, detail, page_id)

    def reset(self) -> None:
        """Clear all wiki data."""
        import shutil
        self._pages.clear()
        if self._base.exists():
            shutil.rmtree(self._base)
        self._base.mkdir(parents=True, exist_ok=True)
        self._graph.reset()
