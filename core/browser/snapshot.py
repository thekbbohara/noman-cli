"""Snapshot utilities for DOM extraction and analysis.

Provides structured DOM tree extraction, element querying,
and snapshot comparison utilities.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SnapshotNode:
    """A single node in a DOM snapshot tree.

    Attributes:
        tag: HTML tag name (lowercase).
        text: Text content (for text nodes).
        attrs: Dictionary of HTML attributes.
        children: Child nodes.
        selector: Computed CSS selector for this node.
        role: ARIA role if available.
        visible: Whether the element is visible.
        interactive: Whether the element is interactive.
    """

    tag: str = ""
    text: str | None = None
    attrs: dict[str, str] = field(default_factory=dict)
    children: list["SnapshotNode"] = field(default_factory=list)
    selector: str = ""
    role: str = ""
    visible: bool = False
    interactive: bool = False
    _raw_attrs: dict[str, str] = field(default_factory=dict, repr=False)

    @property
    def id(self) -> str | None:
        """Get the element ID attribute."""
        return self.attrs.get("id")

    @property
    def name(self) -> str | None:
        """Get the element name attribute."""
        return self.attrs.get("name")

    @property
    def class_names(self) -> list[str]:
        """Get class names as a list."""
        cls = self.attrs.get("class", "")
        return cls.split() if cls else []

    @property
    def is_input(self) -> bool:
        """Check if this is an input element."""
        return self.tag in ("input", "textarea", "select")

    @property
    def is_button(self) -> bool:
        """Check if this is a button element."""
        return self.tag in ("button",) or (self.tag == "input" and self.attrs.get("type") in ("submit", "button", "reset"))

    @property
    def is_link(self) -> bool:
        """Check if this is an anchor element."""
        return self.tag == "a"

    @property
    def href(self) -> str | None:
        """Get the href attribute if this is a link."""
        return self.attrs.get("href")

    @property
    def value(self) -> str | None:
        """Get the value attribute for form elements."""
        return self.attrs.get("value")

    def get_selector(self) -> str:
        """Get the full CSS selector for this node."""
        return self.selector or self._compute_selector()

    def _compute_selector(self) -> str:
        """Compute a unique CSS selector for this node."""
        if self.id:
            return f"#{self.id}"
        if self.name:
            return f"{self.tag}[name={self.name!r}]"
        # Use nth-child selector
        parts = [self.tag]
        if self.attrs.get("class"):
            for cls in self.class_names:
                parts.append(f".{cls}")
        return ".".join(parts) if parts else self.tag

    def find_by_tag(self, tag: str) -> list[SnapshotNode]:
        """Find all descendant nodes with the given tag."""
        results = []
        for child in self.children:
            if child.tag == tag:
                results.append(child)
            results.extend(child.find_by_tag(tag))
        return results

    def find_by_selector(self, selector: str) -> list[SnapshotNode]:
        """Find descendant nodes matching a CSS selector."""
        results = []
        for child in self.children:
            if child.matches_selector(selector):
                results.append(child)
            results.extend(child.find_by_selector(selector))
        return results

    def matches_selector(self, selector: str) -> bool:
        """Check if this node matches a CSS selector (simplified)."""
        # Simple selector matching
        if selector.startswith("#"):
            return self.id == selector[1:]
        if selector.startswith("."):
            return selector[1:] in self.class_names
        if "[" in selector:
            # Handle attribute selectors
            import re
            m = re.match(r'(.+?)\[(.+?)="(.+?)"\]', selector)
            if m:
                tag_match, attr, val = m.group(1), m.group(2), m.group(3)
                if tag_match and self.tag != tag_match:
                    return False
                return self.attrs.get(attr) == val
        return self.tag == selector

    def to_dict(self, depth: int = 0, max_depth: int = 10) -> dict[str, Any]:
        """Serialize to dictionary.

        Args:
            depth: Current nesting depth.
            max_depth: Maximum serialization depth.

        Returns:
            Dictionary representation.
        """
        if depth > max_depth:
            return {"tag": self.tag, "_truncated": True}

        result: dict[str, Any] = {
            "tag": self.tag,
            "selector": self.get_selector(),
            "attrs": {k: v for k, v in self.attrs.items() if k in ("id", "class", "name", "type", "href", "value", "role", "aria-label")},
        }
        if self.text:
            result["text"] = self.text
        if self.interactive:
            result["interactive"] = True
        if self.children and depth < max_depth:
            result["children"] = [c.to_dict(depth + 1, max_depth) for c in self.children]
        return result

    def __repr__(self) -> str:
        return f"<SnapshotNode {self.tag} selector={self.get_selector()!r}>"


@dataclass
class Snapshot:
    """A complete DOM snapshot of a page.

    Attributes:
        url: The page URL.
        title: The page title.
        root: The root DOM node.
        nodes: Flat mapping of all nodes by selector.
        timestamp: When the snapshot was taken.
    """

    url: str = ""
    title: str = ""
    root: SnapshotNode | None = None
    nodes: dict[str, SnapshotNode] = field(default_factory=dict)
    timestamp: str = ""
    cookies: list[dict[str, Any]] = field(default_factory=list)
    local_storage: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.timestamp:
            import time
            self.timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        if self.root:
            self._index_nodes(self.root)

    def _index_nodes(self, node: SnapshotNode, depth: int = 0) -> None:
        """Index all nodes in the tree for fast lookup."""
        if depth > 20:
            return
        selector = node.get_selector()
        if selector:
            self.nodes[selector] = node
        for child in node.children:
            self._index_nodes(child, depth + 1)

    def find_by_tag(self, tag: str) -> list[SnapshotNode]:
        """Find all nodes with the given tag in the DOM."""
        if not self.root:
            return []
        return self.root.find_by_tag(tag)

    def find_by_selector(self, selector: str) -> list[SnapshotNode]:
        """Find all nodes matching a CSS selector."""
        if not self.root:
            return []
        return self.root.find_by_selector(selector)

    def find_interactive(self) -> list[SnapshotNode]:
        """Find all interactive elements."""
        if not self.root:
            return []
        results = []
        self._collect_interactive(self.root, results)
        return results

    def _collect_interactive(self, node: SnapshotNode, results: list[SnapshotNode]) -> None:
        """Collect interactive nodes recursively."""
        if node.interactive:
            results.append(node)
        for child in node.children:
            self._collect_interactive(child, results)

    def to_dict(self, max_depth: int = 10) -> dict[str, Any]:
        """Serialize the snapshot to a dictionary."""
        result: dict[str, Any] = {
            "url": self.url,
            "title": self.title,
            "timestamp": self.timestamp,
            "cookies": self.cookies,
            "local_storage": self.local_storage,
        }
        if self.root:
            result["dom"] = self.root.to_dict(max_depth=max_depth)
        return result

    def to_text(self, max_depth: int = 10) -> str:
        """Render the snapshot as a readable text representation.

        Args:
            max_depth: Maximum depth to render.

        Returns:
            Text representation of the DOM.
        """
        if not self.root:
            return ""
        lines = [f"# {self.title} ({self.url})"]
        lines.append(f"# Timestamp: {self.timestamp}")
        lines.append("")
        self._render_tree(self.root, lines, 0, max_depth)
        return "\n".join(lines)

    def _render_tree(
        self,
        node: SnapshotNode,
        lines: list[str],
        depth: int,
        max_depth: int,
    ) -> None:
        """Recursively render a node tree as text."""
        if depth > max_depth:
            lines.append("  " * depth + "... [truncated]")
            return

        indent = "  " * depth
        attrs_str = ""
        if node.id:
            attrs_str += f"#{node.id}"
        if node.class_names:
            attrs_str += f".{'.'.join(node.class_names)}"
        if node.attrs.get("type"):
            attrs_str += f"[type={node.attrs['type']}]"
        if node.is_link and node.href:
            attrs_str += f" href={node.href}"

        tag_str = f"<{node.tag}" + attrs_str + ">" if attrs_str else f"<{node.tag}>"
        text_preview = f" — {node.text[:50]}..." if node.text else ""
        lines.append(f"{indent}{tag_str}{text_preview}")

        for child in node.children:
            self._render_tree(child, lines, depth + 1, max_depth)


@dataclass
class SnapshotOptions:
    """Options for DOM snapshot extraction.

    Attributes:
        include_styles: Include computed styles in snapshot.
        include_scripts: Include script content.
        max_depth: Maximum DOM tree depth to traverse.
        max_text_length: Maximum text length per node.
        include_hidden: Include hidden elements.
        include_interactive_only: Only include interactive elements.
        selector: Only snapshot nodes matching this selector.
    """

    include_styles: bool = False
    include_scripts: bool = False
    max_depth: int = 10
    max_text_length: int = 200
    include_hidden: bool = True
    include_interactive_only: bool = False
    selector: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "include_styles": self.include_styles,
            "include_scripts": self.include_scripts,
            "max_depth": self.max_depth,
            "max_text_length": self.max_text_length,
            "include_hidden": self.include_hidden,
            "include_interactive_only": self.include_interactive_only,
            "selector": self.selector,
        }
