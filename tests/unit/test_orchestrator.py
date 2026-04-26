"""Tests for core/orchestrator/core.py — ReAct loop orchestrator."""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.orchestrator.core import (
    Orchestrator,
    OrchestratorConfig,
    OrchestratorState,
    PromptAssembler,
    ReActStep,
    Session,
    Turn,
    _flatten_tool_calls,
)


# ── Dataclasses ──────────────────────────────────────────────────────

def test_turn_default_values():
    turn = Turn(user_input="hello")
    assert turn.user_input == "hello"
    assert turn.assistant_output == ""
    assert turn.tool_calls == []
    assert turn.tool_results == []
    assert turn.tokens_used == 0


def test_session_default_values():
    session = Session(id="abc123")
    assert session.id == "abc123"
    assert session.turns == []
    assert session.total_tokens == 0
    assert session.created_at == 0.0


def test_orchestrator_config_defaults():
    cfg = OrchestratorConfig()
    assert cfg.max_turns == 20
    assert cfg.max_tokens_per_turn == 8000
    assert cfg.max_tool_calls_per_turn == 10
    assert cfg.planning_timeout_sec == 30.0
    assert cfg.execution_timeout_sec == 60.0


def test_orchestrator_state_enum():
    assert OrchestratorState.IDLE.value == "idle"
    assert OrchestratorState.PLANNING.value == "planning"
    assert OrchestratorState.EXECUTING.value == "executing"
    assert OrchestratorState.OBSERVING.value == "observing"
    assert OrchestratorState.COMPLETE.value == "complete"
    assert OrchestratorState.ERROR.value == "error"


# ── PromptAssembler ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_prompt_assembler_system_prompt():
    tools = MagicMock()
    tools.list_tools.return_value = ["read_file", "edit_file"]
    pa = PromptAssembler(tools)
    assert "Available tools" in pa.SYSTEM_PROMPT
    assert "read_file" in pa.AVAILABLE_TOOLS
    assert "edit_file" in pa.AVAILABLE_TOOLS


@pytest.mark.asyncio
async def test_prompt_assembler_assemble():
    tools = MagicMock()
    tools.list_tools.return_value = ["read_file", "edit_file"]
    pa = PromptAssembler(tools)

    session = Session(id="test", turns=[
        Turn(user_input="what is this?", assistant_output='{"content": "here", "is_final_result": true}'),
    ])
    messages, tool_defs = pa.assemble(session, "new task", 4000)

    assert len(messages) >= 3  # system + user turn + new task
    roles = [m.role for m in messages]
    assert "system" in roles
    assert "user" in roles


# ── _flatten_tool_calls ──────────────────────────────────────────────

def test_flatten_nested_tool_calls():
    nested = [
        {
            "tool_calls": [
                {"id": "1", "name": "tool_a", "args": {"x": 1}},
                {"function": {"name": "tool_b", "arguments": {"y": 2}}},
            ]
        }
    ]
    result = _flatten_tool_calls(nested)
    names = [tc["function"]["name"] for tc in result]
    assert "tool_a" in names
    assert "tool_b" in names


def test_flatten_flat_tool_calls():
    calls = [
        {"function": {"name": "foo", "arguments": {}}},
        {"function": {"name": "bar", "arguments": {"k": "v"}}},
    ]
    result = _flatten_tool_calls(calls)
    assert len(result) == 2
    names = [tc["function"]["name"] for tc in result]
    assert "foo" in names
    assert "bar" in names


def test_flatten_empty():
    assert _flatten_tool_calls([]) == []
    assert _flatten_tool_calls(None) == []
    assert _flatten_tool_calls("not a list") == []
