"""CrossSessionDetector — finds recurring patterns across recent sessions.

Scans the last N sessions for tool call patterns that appear multiple times
but may not have been recognized as skill-worthy at the time.

This is a background analysis module — it doesn't run automatically but can
be triggered via CLI or on-demand.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Session storage paths
SESSION_DIR = Path.home() / ".noman" / "sessions"


@dataclass
class SessionPattern:
    """A recurring pattern detected across sessions."""

    tool_sequence: str  # Canonical form of the tool chain
    count: int  # How many sessions contain this pattern
    domains: list[str]  # Detected domains
    avg_score: float  # Average skill suggestion score across occurrences
    first_seen: str  # ISO-ish timestamp
    last_seen: str  # ISO-ish timestamp
    session_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _get_recent_sessions(limit: int = 50) -> list[dict]:
    """Load recent session files, sorted by modification time."""
    if not SESSION_DIR.exists():
        return []

    sessions = []
    for f in sorted(SESSION_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)[:limit]:
        if f.suffix in (".json", ".jsonl") and f.is_file():
            try:
                data = json.loads(f.read_text())
                data["_session_file"] = str(f)
                sessions.append(data)
            except (json.JSONDecodeError, OSError):
                pass
    return sessions


def _extract_tool_chain(session: dict) -> tuple[str, list[str]]:
    """Extract a canonical tool chain from a session.

    Returns (canonical_sequence, domain_labels).
    Groups consecutive tool calls into phases.
    """
    turns = session.get("turns", [])
    tool_calls = session.get("tool_calls", [])

    # Build ordered list of tools
    tools = []
    for t in turns:
        if isinstance(t, dict):
            name = t.get("tool", t.get("name", ""))
            if name:
                tools.append(name)
    for tc in tool_calls:
        if isinstance(tc, dict):
            name = tc.get("tool", tc.get("name", ""))
            if name and name not in tools:
                tools.append(name)

    if not tools:
        return "", []

    # Create canonical form: replace individual tool calls with phases
    phases = []
    current_phase = None
    for tool in tools:
        # Group by tool family
        family = _get_tool_family(tool)
        if family != current_phase:
            phases.append(family)
            current_phase = family

    sequence = "->".join(phases)
    return sequence, phases


def _get_tool_family(tool_name: str) -> str:
    """Map a tool name to its functional family."""
    tool_lower = tool_name.lower()

    families = [
        ("browser", ["browser_", "playwright", "puppeteer"]),
        ("file", ["read_file", "write_file", "patch", "search_files"]),
        ("terminal", ["terminal", "execute_code", "bash"]),
        ("database", ["mysql_query", "mcp_mysql", "sqlite"]),
        ("mcp", ["mcp_", "read_resource", "list_resources"]),
        ("search", ["web_search", "browser_navigate"]),
        ("communication", ["send_message", "text_to_speech"]),
        ("skill", ["skill_", "skill_manage", "skill_view"]),
        ("git", ["git_", "gh_"]),
        ("delegation", ["delegate_task"]),
        ("cron", ["cronjob"]),
        ("vision", ["vision_analyze", "get_images"]),
    ]

    for family, patterns in families:
        for pattern in patterns:
            if pattern in tool_lower:
                return family

    return "other"


def detect_cross_session_patterns(min_occurrences: int = 3, max_sessions: int = 50) -> list[SessionPattern]:
    """Detect recurring tool call patterns across recent sessions.

    Looks for tool chains that appear in multiple sessions but may not
    have been recognized as skill-worthy individually.

    Args:
        min_occurrences: Minimum number of sessions with this pattern to report.
        max_sessions: Maximum number of recent sessions to scan.

    Returns:
        List of SessionPattern objects sorted by count (most common first).
    """
    sessions = _get_recent_sessions(max_sessions)
    if not sessions:
        logger.debug("No sessions found for cross-session pattern detection")
        return []

    # Track patterns: sequence -> {count, domains, scores, session_ids, timestamps}
    pattern_data: dict[str, dict] = {}

    for session in sessions:
        sequence, phases = _extract_tool_chain(session)
        if not sequence or sequence == "other":
            continue

        # Get session metadata
        session_id = session.get("session_id", Path(session.get("_session_file", "")).stem)
        timestamp = session.get("created_at", session.get("start_time", ""))

        if sequence not in pattern_data:
            pattern_data[sequence] = {
                "count": 0,
                "domains": set(),
                "scores": [],
                "session_ids": [],
                "first_seen": timestamp,
                "last_seen": timestamp,
                "phases": phases,
            }

        data = pattern_data[sequence]
        data["count"] += 1
        data["session_ids"].append(session_id)

        # Try to get domain from trace
        trace = session.get("trace", session.get("self_improve_trace", {}))
        if isinstance(trace, dict):
            domain = trace.get("detected_domain", "general")
            data["domains"].add(domain)

        # Get skill suggestion score if available
        score = trace.get("score", {}).get("skill_suggestion_score")
        if score is not None:
            data["scores"].append(score)

        data["last_seen"] = timestamp

    # Filter to patterns that meet minimum occurrence threshold
    patterns = []
    for sequence, data in pattern_data.items():
        if data["count"] >= min_occurrences:
            avg_score = sum(data["scores"]) / len(data["scores"]) if data["scores"] else 0.0
            patterns.append(SessionPattern(
                tool_sequence=sequence,
                count=data["count"],
                domains=list(data["domains"]) or ["general"],
                avg_score=avg_score,
                first_seen=data["first_seen"],
                last_seen=data["last_seen"],
                session_ids=data["session_ids"],
            ))

    patterns.sort(key=lambda p: p.count, reverse=True)
    return patterns


def format_patterns(patterns: list[SessionPattern]) -> str:
    """Format patterns for display."""
    if not patterns:
        return "No recurring patterns found in recent sessions."

    lines = [f"=== Cross-Session Patterns ({len(patterns)} detected) ===\n"]

    for i, p in enumerate(patterns, 1):
        lines.append(f"\n[{i}] {p.tool_sequence}")
        lines.append(f"    Occurrences: {p.count} sessions")
        lines.append(f"    Domains: {', '.join(p.domains)}")
        lines.append(f"    Avg score: {p.avg_score:.2f}")
        lines.append(f"    First seen: {p.first_seen}")
        lines.append(f"    Last seen: {p.last_seen}")
        lines.append(f"    Sessions: {', '.join(p.session_ids[:5])}")

    lines.append("\nRecommendation: Review these patterns for potential skill creation.")
    return "\n".join(lines)
