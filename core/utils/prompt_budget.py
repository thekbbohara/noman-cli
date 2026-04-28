"""Prompt budget: token allocation across system/history/transient."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PromptBudgetRatios:
    system: int = 15      # % for system prompt
    history: int = 70    # % for conversation history
    transient: int = 10   # % for transient context
    single_message: int = 25  # % of history for single message cap


@dataclass
class PromptBudgetConfig:
    max_tokens: int = 8000
    ratios: PromptBudgetRatios = field(default_factory=PromptBudgetRatios)

    @property
    def system_budget(self) -> int:
        return max(0, (self.max_tokens * self.ratios.system) // 100)

    @property
    def history_budget(self) -> int:
        return max(0, (self.max_tokens * self.ratios.history) // 100)

    @property
    def transient_budget(self) -> int:
        return max(0, (self.max_tokens * self.ratios.transient) // 100)

    @property
    def single_message_budget(self) -> int:
        return max(0, (self.history_budget * self.ratios.single_message) // 100)


MIN_PROMPT_PART_TRIM_TOKENS = 250  # minimum trim threshold (from space-agent)


@dataclass
class PromptContributor:
    key: str
    original_text: str
    current_text: str = ""
    token_count: int = 0
    trim_allowed: bool = True
    trim_priority: int = 0
    order: int = 0
    exhausted: bool = False

    def __post_init__(self) -> None:
        if not self.current_text:
            self.current_text = self.original_text


def can_trim_contributor(contributor: PromptContributor) -> bool:
    """Check if contributor can be trimmed."""
    return (
        contributor.trim_allowed
        and bool(contributor.original_text.strip())
        and not contributor.exhausted
    )


def trim_contributor_by_overflow(
    contributor: PromptContributor,
    overflow_tokens: int,
    count_tokens: callable | None = None,
) -> bool:
    """Trim contributor to reduce token count."""
    if not can_trim_contributor(contributor):
        return False

    current = contributor.token_count
    target = max(0, current - overflow_tokens)

    if target >= current:
        contributor.exhausted = True
        return False

    # Simple trim: keep first N chars proportional to target
    ratio = target / max(1, current)
    chars_to_keep = max(24, int(len(contributor.original_text) * ratio))
    contributor.current_text = contributor.original_text[:chars_to_keep].rsplit(" ", 1)[0]

    if count_tokens:
        contributor.token_count = count_tokens(contributor.current_text)
    else:
        contributor.token_count = len(contributor.current_text) // 4

    return True


def apply_prompt_part_budget(
    contributors: list[PromptContributor],
    budget_tokens: int,
    count_tokens: callable | None = None,
) -> list[PromptContributor]:
    """Apply token budget to contributors with thresholded trimming."""
    total = sum(c.token_count for c in contributors)

    if total <= budget_tokens:
        return contributors

    overflow = total - budget_tokens
    trimmed = []

    # Sort by trim_priority (lower = trim first), then by order
    sorted_contributors = sorted(
        contributors,
        key=lambda c: (c.trim_priority, c.order),
    )

    for contributor in sorted_contributors:
        if overflow <= 0:
            trimmed.append(contributor)
            continue

        # Threshold: only trim if cut is at least MIN_PROMPT_PART_TRIM_TOKENS
        if contributor.token_count >= MIN_PROMPT_PART_TRIM_TOKENS:
            cut = min(contributor.token_count - 1, overflow)
            if trim_contributor_by_overflow(contributor, cut, count_tokens):
                overflow = max(0, overflow - cut)

        trimmed.append(contributor)

    return trimmed