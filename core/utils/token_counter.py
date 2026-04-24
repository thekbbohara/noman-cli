"""Token counting with tiktoken fallback."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _try_tiktoken() -> object | None:
    try:
        import tiktoken
        return tiktoken
    except ImportError:
        return None


def count_tokens(text: str, model: str = "gpt-4") -> int:
    """Count tokens in *text*. Falls back to char/4 estimate."""
    tiktoken = _try_tiktoken()
    if tiktoken:
        try:
            enc = tiktoken.encoding_for_model(model)  # type: ignore[attr-defined]
            return len(enc.encode(text))
        except KeyError:
            pass
    return max(1, len(text) // 4)


def count_message_tokens(messages: list[dict], model: str = "gpt-4") -> int:
    """Count tokens for a list of chat messages."""
    total = 0
    for msg in messages:
        total += count_tokens(msg.get("content", ""), model)
        total += count_tokens(msg.get("role", ""), model)
        # Format overhead per message (~4 tokens)
        total += 4
    return total
