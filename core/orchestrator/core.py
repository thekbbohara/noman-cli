"""Orchestrator with ReAct loop."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.adapters import BaseAdapter, Message
from core.adapters.base import ToolDefinition
from core.context import ContextManager
from core.errors.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError
from core.memory import MemorySystem
from core.tools import ToolBus
from core.utils.retry import RetryConfig, RetryManager

logger = logging.getLogger(__name__)


class OrchestratorState(Enum):
    IDLE = "idle"
    PLANNING = "planning"
    EXECUTING = "executing"
    OBSERVING = "observing"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class Turn:
    user_input: str
    assistant_output: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[str] = field(default_factory=list)
    tokens_used: int = 0


@dataclass
class Session:
    id: str
    turns: list[Turn] = field(default_factory=list)
    total_tokens: int = 0
    created_at: float = 0.0


@dataclass
class OrchestratorConfig:
    max_turns: int = 20
    max_tokens_per_turn: int = 8000
    max_tool_calls_per_turn: int = 10
    planning_timeout_sec: float = 30.0
    execution_timeout_sec: float = 60.0


@dataclass
class ReActStep:
    thought: str
    action: str
    observation: str = ""
    is_final: bool = False


class PromptAssembler:
    AVAILABLE_TOOLS = (
    "run_shell, list_dir, read_file, search_code, glob, find, write_file, "
    "append_file, mkdir, copy_file, move_file, delete_file, path_exists, path_type, "
    "git_status, git_current_branch, git_push, git_reset, git_delete_branch, "
    "get_env, set_env, list_processes, kill_process, docker_ps, docker_logs, docker_exec, "
    "run_tests, explain_code, find_symbol, find_references, get_file_tree, list_imports, "
    "memory_search, skill_list, skill_load"
)

    SYSTEM_PROMPT = f"""You are NoMan, an autonomous coding agent.

You operate within a token budget. Be concise and efficient.

Response format — you MUST return this structure:
- If you need to use tools: `{{"content": "", "tool_calls": [...], "is_final_result": false}}`
- If you have the answer: `{{"content": "your answer", "tool_calls": [], "is_final_result": true}}`

RULES:
- `is_final_result: false` → you MUST include tool_calls. Do not return empty tool_calls.
- `is_final_result: true` → `content` must be your complete final answer. No tool_calls.
- NEVER return `is_final_result: true` while still having tools to call.
- ALWAYS call a tool if you need to check, search, read, or verify information.

Available tools: {AVAILABLE_TOOLS}

Workflow per turn:
1. REASON - Think about what to do
2. ACT - Execute a tool or respond
3. OBSERVE - Process the result
4. FINAL - When you have the complete answer, set is_final_result: true"""

    def __init__(self, tools: ToolBus, context: ContextManager | None = None) -> None:
        self._tools = tools
        self._context = context

    def assemble(
        self, session: Session, task: str, budget: int,
    ) -> tuple[list[Message], list[ToolDefinition]]:
        messages: list[Message] = []
        messages.append(Message(role="system", content=self.SYSTEM_PROMPT))

        remaining = budget - len(self.SYSTEM_PROMPT)
        for turn in session.turns[-5:]:
            if turn.assistant_output:
                messages.append(Message(role="assistant", content=turn.assistant_output))
                remaining -= len(turn.assistant_output)
            for result in turn.tool_results:
                messages.append(Message(role="user", content=f"Result: {result}"))
                remaining -= len(result)
            if remaining < 1000:
                break

        messages.append(Message(role="user", content=task))
        return messages, self._build_tool_defs()

    def _build_tool_defs(self) -> list[ToolDefinition]:
        defs = []
        for name in self._tools.list_tools() or []:
            tool = self._tools._tools.get(name)
            if tool:
                defs.append(ToolDefinition(
                    name=tool.name,
                    description=tool.description,
                    parameters=tool.parameters,
                ))
        return defs


class Orchestrator:
    def __init__(
        self,
        adapter: BaseAdapter,
        tools: ToolBus,
        config: OrchestratorConfig | None = None,
        context: ContextManager | None = None,
        memory: MemorySystem | None = None,
    ) -> None:
        self._adapter = adapter
        self._tools = tools
        self._cfg = config or OrchestratorConfig()
        self._context = context
        self._memory = memory
        self._assembler = PromptAssembler(tools, context)
        self._state = OrchestratorState.IDLE
        self._current_session: Session | None = None
        self._breaker = CircuitBreaker("adapter")
        self._retry = RetryManager(RetryConfig(
            max_attempts=3,
            base_delay_sec=1.0,
            retryable_exceptions=(ConnectionError, TimeoutError),
        ))

    async def _resilient_chat(
        self, messages: list[Message], tool_defs: list[ToolDefinition],
    ) -> Any:
        import httpx

        async def _call():
            return await self._adapter.chat(messages, tool_defs)

        try:
            async def _call_with_retry():
                return await self._retry.execute(_call)

            return await self._breaker.call(_call_with_retry)
        except CircuitBreakerOpenError:
            logger.error("Circuit breaker OPEN — adapter unavailable")
            return None
        except (ConnectionError, TimeoutError, httpx.HTTPError, httpx.TimeoutException):
            logger.error("Adapter call failed after retries")
            return None
        except Exception:
            logger.exception("Unexpected adapter error")
            return None

    async def run(self, task: str) -> str:
        self._current_session = Session(id=self._new_session_id())
        turn = Turn(user_input=task)
        response = await self._execute_turn_with_tools(task)
        turn.assistant_output = response
        self._current_session.turns.append(turn)
        return response

    async def _execute_turn_with_tools(self, task: str) -> str:
        messages, tool_defs = self._assembler.assemble(
            self._current_session, task, self._cfg.max_tokens_per_turn,
        )

        for _ in range(self._cfg.max_tool_calls_per_turn):
            self._state = OrchestratorState.PLANNING
            response = await self._resilient_chat(messages, tool_defs)
            if response is None:
                return "Sorry, I couldn't reach the AI provider. Check your network and try again."

            tool_calls = response.tool_calls
            raw_content = response.content or ""

            # Parse is_final_result from JSON content
            is_final, content, parsed_calls = self._parse_response(raw_content, tool_calls)

            if is_final:
                return content or raw_content

            # is_final = false → must have tool_calls
            if not parsed_calls:
                messages.append(Message(
                    role="assistant",
                    content=raw_content,
                ))
                messages.append(Message(
                    role="user",
                    content=(
                        "ERROR: is_final_result: false but no tool_calls returned. "
                        "Call the necessary tool(s), then respond with is_final_result: true "
                        "when you have the complete answer."
                    ),
                ))
                continue

            for tc in parsed_calls:
                self._state = OrchestratorState.EXECUTING
                tool_name = tc.get("function", {}).get("name", "")
                args = tc.get("function", {}).get("arguments", {})
                if isinstance(args, str):
                    try:
                        import json
                        args = json.loads(args)
                    except Exception:
                        args = {}

                if tool_name not in self._tools.list_tools():
                    result_str = f"Unknown tool: {tool_name}"
                else:
                    try:
                        result = await self._tools.execute(tool_name, args)
                        result_str = str(result)
                    except Exception as e:
                        result_str = f"Error: {e}"

                messages.append(Message(role="assistant", content=raw_content, tool_calls=[tc]))
                messages.append(Message(
                    role="user", content=result_str, tool_call_id=tc.get("id", ""),
                ))

        return raw_content or "Max tool call iterations reached."

    def _parse_response(
        self, raw_content: str, api_tool_calls: list,
    ) -> tuple[bool, str, list]:
        """Parse is_final_result from model JSON response."""
        import json

        if not raw_content:
            return False, "", api_tool_calls or []

        raw_content = raw_content.strip()
        try:
            parsed = json.loads(raw_content)
        except (json.JSONDecodeError, ValueError):
            # Not JSON — treat as plain text response (model gave up)
            return True, raw_content, []

        is_final = bool(parsed.get("is_final_result", True))
        content = parsed.get("content", "") or ""
        # Prefer API tool_calls, fall back to parsed JSON tool_calls
        parsed_calls = api_tool_calls or parsed.get("tool_calls", [])
        return is_final, content, parsed_calls

    async def _react_loop(self, task: str, turn_num: int) -> list[ReActStep]:
        if self._context:
            self._context.get_context(self._cfg.max_tokens_per_turn)

        messages, tool_defs = self._assembler.assemble(
            self._current_session, task, self._cfg.max_tokens_per_turn,
        )

        self._state = OrchestratorState.PLANNING
        response = await self._resilient_chat(messages, tool_defs)
        if response is None:
            return [ReActStep(thought="AI provider unreachable", action="respond", is_final=True)]

        steps = self._parse_react_response(response.content)
        if not steps:
            steps = [ReActStep(thought=response.content, action="respond", is_final=True)]

        self._state = OrchestratorState.OBSERVING
        return steps

    def _parse_react_response(self, response: str) -> list[ReActStep]:
        steps: list[ReActStep] = []
        lines = response.split("\n")
        current_thought = ""
        current_action = ""
        is_final = False

        for line in lines:
            line = line.strip()
            if line.startswith("Thought:") or line.startswith("Think:"):
                if current_thought:
                    steps.append(ReActStep(
                        thought=current_thought, action=current_action, is_final=is_final,
                    ))
                current_thought = line.split(":", 1)[1].strip()
                current_action = ""
                is_final = False
            elif line.startswith("Action:") or line.startswith("Act:"):
                current_action = line.split(":", 1)[1].strip()
            elif line.startswith("Observation:") or line.startswith("Obs:"):
                observation = line.split(":", 1)[1].strip()
                if not is_final:
                    steps.append(ReActStep(
                        thought=current_thought, action=current_action, observation=observation,
                    ))
                    current_thought = ""
                    current_action = ""
            elif line.startswith("Final:") or line.startswith("Answer:"):
                current_thought += " " + line.split(":", 1)[1].strip()
                is_final = True

        if current_thought:
            steps.append(ReActStep(
                thought=current_thought, action=current_action, is_final=is_final,
            ))

        if not steps and response.strip():
            steps.append(ReActStep(thought=response.strip(), action="respond", is_final=True))

        return steps

    async def _execute_action(self, action: str) -> str:
        self._state = OrchestratorState.EXECUTING
        parts = action.split(maxsplit=1)
        if not parts:
            return "No action specified"
        tool_name = parts[0]
        args: dict[str, str] = {}
        if len(parts) > 1:
            for ap in parts[1].split():
                if "=" in ap:
                    k, v = ap.split("=", 1)
                    args[k] = v
        try:
            result = await self._tools.execute(tool_name, args)
            return str(result)
        except Exception as e:
            return f"Error executing {tool_name}: {e}"

    def _new_session_id(self) -> str:
        return str(uuid.uuid4())[:8]

    @property
    def state(self) -> OrchestratorState:
        return self._state

    @property
    def session(self) -> Session | None:
        return self._current_session
