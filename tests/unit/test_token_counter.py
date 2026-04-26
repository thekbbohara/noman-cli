"""Tests for core/utils/token_counter.py — Token counting."""

import pytest
from core.utils.token_counter import count_tokens, count_message_tokens


# ── count_tokens ─────────────────────────────────────────────────────

def test_count_tokens_empty():
    result = count_tokens("")
    assert result >= 1  # max(1, ...) ensures at least 1


def test_count_tokens_simple():
    result = count_tokens("hello world")
    # Without tiktoken, uses len(text) // 4
    assert result >= 1


def test_count_tokens_long_text():
    text = "a" * 400
    result = count_tokens(text)
    # Should scale roughly linearly
    assert result > 50


def test_count_tokens_unicode():
    result = count_tokens("Hello 世界 🌍")
    assert result >= 1


def test_count_tokens_with_model_param():
    result = count_tokens("test", model="gpt-3.5-turbo")
    assert result >= 1


def test_count_tokens_returns_int():
    result = count_tokens("test")
    assert isinstance(result, int)


# ── count_message_tokens ─────────────────────────────────────────────

def test_count_message_tokens_empty():
    result = count_message_tokens([])
    assert result == 0


def test_count_message_tokens_single():
    msgs = [{"role": "user", "content": "hello"}]
    result = count_message_tokens(msgs)
    # role + content + format overhead
    assert result > 0


def test_count_message_tokens_multiple():
    msgs = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "Hello!"},
    ]
    result = count_message_tokens(msgs)
    assert result > 0


def test_count_message_tokens_missing_keys():
    msgs = [{"content": "no role"}, {"role": "assistant"}]
    result = count_message_tokens(msgs)
    assert result > 0  # shouldn't crash
