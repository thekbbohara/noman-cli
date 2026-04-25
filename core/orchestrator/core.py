"""Orchestrator with ReAct loop."""

from __future__ import annotations

import json
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
    def __init__(self, tools: ToolBus, context: ContextManager | None = None) -> None:
        self._tools = tools
        self._context = context

    @property
    def AVAILABLE_TOOLS(self) -> str:
        """Dynamically generate the tool list from registered tools."""
        tool_names = self._tools.list_tools() or []
        return ", ".join(tool_names)

    @property
    def SYSTEM_PROMPT(self) -> str:
        tools_list = self.AVAILABLE_TOOLS
        return f"""You are NoMan, an autonomous coding agent.

You operate within a token budget. Be concise and efficient.

Response format — you MUST return this structure:
- If you need to use tools: `{{"content": "", "tool_calls": [...], "is_final_result": false}}`
- If you have the answer: `{{"content": "your answer", "tool_calls": [], "is_final_result": true}}`

RULES:
- `is_final_result: false` → you MUST include tool_calls. Do not return empty tool_calls.
- `is_final_result: true` → `content` must be the complete final answer. No tool_calls.
- NEVER return `is_final_result: true` while still having tools to call.
- ALWAYS call a tool if you need to check, search, read, or verify information.

Available tools: {tools_list}

Workflow per turn:
1. REASON - Think about what to do
2. ACT - Execute a tool or respond
3. OBSERVE - Process the result
4. FINAL - When you have the complete answer, set is_final_result: true"""

    def assemble(
        self, session: Session, task: str, budget: int,
    ) -> tuple[list[Message], list[ToolDefinition]]:
        messages: list[Message] = []

        # Load conversation history
        history = self._load_history()
        history_len = len(history) if history else 0
        if history:
            history_msg = f"Previous conversation:\n{history}\n\n---"
            messages.append(Message(role="system", content=history_msg))

        messages.append(Message(role="system", content=self.SYSTEM_PROMPT))

        # Calculate remaining budget accounting for history
        remaining = budget - len(self.SYSTEM_PROMPT) - history_len
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

    def _load_history(self) -> str:
        """Load conversation history from ~/.noman/history.txt."""
        from pathlib import Path
        history_file = Path.home() / ".noman" / "history.txt"
        if not history_file.exists():
            return ""
        content = history_file.read_text()
        # Return last ~2000 chars to stay within budget
        return content[-2000:] if len(content) > 2000 else content


class Orchestrator:
    MAX_TOOL_ITERATIONS = 20  # Hard cap to prevent infinite loops

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
        self._context_tokens: int | None = None

    async def _probe_context_tokens(self) -> int:
        """Probe adapter for context window size."""
        try:
            caps = await self._adapter.capabilities()
            return caps.max_context_tokens
        except Exception:
            logger.warning("Could not probe context window, using default")
            return self._cfg.max_tokens_per_turn

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
        finally:
            self._save_debug(messages)

    async def run(self, task: str) -> str:
        self._current_session = Session(id=self._new_session_id())
        turn = Turn(user_input=task)
        response = await self._execute_turn_with_tools(task)
        turn.assistant_output = response
        self._current_session.turns.append(turn)
        return response

    async def _execute_turn_with_tools(self, task: str) -> str:
        if self._context_tokens is None:
            self._context_tokens = await self._probe_context_tokens()
        budget = int(self._context_tokens * 0.8)
        messages, tool_defs = self._assembler.assemble(
            self._current_session, task, budget,
        )

        consecutive_non_tool_responses = 0
        for iteration in range(self.MAX_TOOL_ITERATIONS):
            self._state = OrchestratorState.PLANNING
            response = await self._resilient_chat(messages, tool_defs)
            if response is None:
                return "Sorry, I couldn't reach the AI provider. Check your network and try again."

            tool_calls = response.tool_calls
            raw_content = response.content or ""

            # Log raw response for debugging
            log_msg = (f"[iter={iteration}] tool_calls={bool(tool_calls)}, "
                       f"content_len={len(raw_content)}, content={raw_content[:200]}...")
            logger.debug(log_msg)

            # Parse is_final_result from JSON content
            is_final, content, parsed_calls = self._parse_response(raw_content, tool_calls)

            # If plain text (not JSON) after tool results → model gave up
            just_executed_tools = iteration > 0 and any(
                "Result:" in str(m.content) for m in messages if m.role == "user"
            )

            # Count consecutive non-tool responses
            if is_final:
                consecutive_non_tool_responses = 0
            elif just_executed_tools and not parsed_calls and raw_content.strip():
                consecutive_non_tool_responses += 1
                if consecutive_non_tool_responses >= 3:
                    logger.warning("Model stuck in loop, returning last content")
                    return content or raw_content

                messages.append(Message(role="assistant", content=raw_content))
                messages.append(Message(
                    role="user",
                    content=(
                        "You received tool results — use them. Call more tools if needed, "
                        "or synthesize results into final answer."
                    ),
                ))
                continue

            if is_final:
                return content or raw_content

            # is_final = false → must have tool_calls
            if not parsed_calls:
                messages.append(Message(role="assistant", content=raw_content))
                messages.append(Message(
                    role="user",
                    content=(
                        "ERROR: is_final_result: false but no tool_calls returned. "
                        "Call the necessary tool(s), then respond with is_final_result: true "
                        "when you have the complete answer."
                    ),
                ))
                continue

            consecutive_non_tool_responses = 0

            for tc in parsed_calls:
                self._state = OrchestratorState.EXECUTING
                tool_name = tc.get("function", {}).get("name", "")
                args = tc.get("function", {}).get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}

                if tool_name not in self._tools.list_tools():
                    result_str = f"Unknown tool: {tool_name}"
                    logger.warning("Unknown tool: %s", tool_name)
                else:
                    try:
                        result = await self._tools.execute(tool_name, args)
                        result_str = str(result)
                        logger.info("Tool %s executed, result_len=%d", tool_name, len(result_str))
                    except Exception as e:
                        result_str = f"Error: {e}"
                        logger.error("Tool %s failed: %s", tool_name, e)

                messages.append(Message(role="assistant", content=raw_content, tool_calls=[tc]))
                messages.append(Message(
                    role="user", content=result_str, tool_call_id=tc.get("id", ""),
                ))

        return raw_content or "Max tool call iterations reached."

    def _parse_response(
        self, raw_content: str, api_tool_calls: list,
    ) -> tuple[bool, str, list]:
        """Parse is_final_result from model JSON response."""
        if not raw_content:
            return False, "", api_tool_calls or []

        raw_content = raw_content.strip()
        try:
            parsed = json.loads(raw_content)
        except (json.JSONDecodeError, ValueError):
            return True, raw_content, []

        if not isinstance(parsed, dict):
            return True, raw_content, []

        is_final = bool(parsed.get("is_final_result", True))
        content = parsed.get("content", "") or ""
        parsed_calls = api_tool_calls or parsed.get("tool_calls", [])
        parsed_calls = _flatten_tool_calls(parsed_calls)
        if is_final and parsed_calls:
            is_final = False
        return is_final, content, parsed_calls

    def _new_session_id(self) -> str:
        return str(uuid.uuid4())[:8]

    def _save_debug(self, messages: list[Message]) -> None:
        """Save raw conversation to debug file."""
        from pathlib import Path
        debug_dir = Path.home() / ".noman" / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        debug_file = debug_dir / f"trace_{uuid.uuid4().hex[:8]}.txt"
        content = []
        for m in messages:
            content.append(f"\n=== {m.role.upper()} ===\n{m.content or ''}")
        debug_file.write_text("\n".join(content))

    @property
    def state(self) -> OrchestratorState:
        return self._state

    @property
    def session(self) -> Session | None:
        return self._current_session


def _flatten_tool_calls(calls) -> list:
    """Recursively flatten and normalize tool calls from any nesting level."""
    if not isinstance(calls, list):
        return []
    result = []
    for tc in calls:
        if not isinstance(tc, dict):
            continue
        if "function" in tc:
            result.append(tc)
        elif "name" in tc:
            result.append({
                "id": tc.get("id", f"call_{tc['name']}"),
                "type": "function",
                "function": {
                    "name": tc["name"],
                    "arguments": tc.get("args") or tc.get("arguments") or "{}",
                },
            })
        elif "tool_calls" in tc:
            result.extend(_flatten_tool_calls(tc["tool_calls"]))
    return result
