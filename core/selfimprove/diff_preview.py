"""Generate human-readable diffs for proposed changes."""

from __future__ import annotations

from core.selfimprove.meta_agent import ImprovementProposal


def format_diff(proposal: ImprovementProposal) -> str:
    """Format a proposal as a unified diff for TUI display."""
    old_lines = proposal.old_content.splitlines()
    new_lines = proposal.new_content.splitlines()

    lines = [
        f"File: {proposal.target_file}",
        f"Type: {proposal.change_type.value}",
        f"Confidence: {proposal.confidence:.0%}",
        f"Requires approval: {proposal.requires_approval}",
        "",
        "--- old",
        "+++ new",
    ]

    # Simple line-by-line diff
    max_len = max(len(old_lines), len(new_lines))
    for i in range(max_len):
        old = old_lines[i] if i < len(old_lines) else None
        new = new_lines[i] if i < len(new_lines) else None

        if old == new:
            lines.append(f"  {old}")
        elif old is None:
            lines.append(f"+{new}")
        elif new is None:
            lines.append(f"-{old}")
        else:
            lines.append(f"-{old}")
            lines.append(f"+{new}")

    lines.append("")
    lines.append(f"Reason: {proposal.reasoning}")
    return "\n".join(lines)
