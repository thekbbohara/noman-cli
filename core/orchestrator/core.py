"""Orchestrator with ReAct loop."""

from __future__ import annotations

import logging
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
    """Single turn in a conversation."""

    user_input: str
    assistant_output: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[str] = field(default_factory=list)
    tokens_used: int = 0


@dataclass
class Session:
    """A complete session with multiple turns."""

    id: str
    turns: list[Turn] = field(default_factory=list)
    total_tokens: int = 0
    created_at: float = 0.0


@dataclass
class OrchestratorConfig:
    """Configuration for orchestrator."""

    max_turns: int = 20
    max_tokens_per_turn: int = 8000
    max_tool_calls_per_turn: int = 10
    planning_timeout_sec: float = 30.0
    execution_timeout_sec: float = 60.0


@dataclass
class ReActStep:
    """Single step in ReAct reasoning."""

    thought: str
    action: str
    observation: str = ""
    is_final: bool = False


class PromptAssembler:
    """Assemble prompts from context, memory, and conversation."""

    SYSTEM_PROMPT = """You are NoMan, an autonomous coding agent.

You operate within a token budget. Be concise and efficient.

Your workflow per turn:
1. REASON - Think about what to do
2. ACT - Execute a tool or respond
3. OBSERVE - Process the result

Before acting, check if you have the context you need.
Use JIT loading to fetch specific code when needed.
"""

    def __init__(self, tools: ToolBus, context: ContextManager | None = None) -> None:
        self._tools = tools
        self._context = context

    def assemble(
        self,
        session: Session,
        task: str,
        budget: int,
    ) -> tuple[list[Message], list[ToolDefinition]]:
        """Assemble prompt for a turn. Returns (messages, tool_defs)."""
        messages: list[Message] = []

        # System prompt
        system_content = self.SYSTEM_PROMPT
        messages.append(Message(role="system", content=system_content))

        # Prior turns (truncated to fit budget)
        remaining = budget - len(system_content)
        for turn in session.turns[-5:]:
            if turn.assistant_output:
                messages.append(Message(role="assistant", content=turn.assistant_output))
                remaining -= len(turn.assistant_output)

            for result in turn.tool_results:
                messages.append(Message(role="user", content=f"Result: {result}"))
                remaining -= len(result)

            if remaining < 1000:
                break

        # Current task
        messages.append(Message(role="user", content=task))

        # Build tool definitions from registered tools
        tool_defs = self._build_tool_defs()
        return messages, tool_defs

    def _build_tool_defs(self) -> list[ToolDefinition]:
        """Convert registered Tool objects to ToolDefinition for the model."""
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
    """Main orchestrator with ReAct loop."""

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
        """adapter.chat() wrapped with circuit breaker + retry + error boundary."""
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
        """Run a task to completion. Returns final response."""
        self._current_session = Session(id=self._new_session_id())
        turn = Turn(user_input=task)
        response = await self._execute_turn_with_tools(task)
        turn.assistant_output = response
        self._current_session.turns.append(turn)
        return response

    async def _execute_turn_with_tools(self, task: str) -> str:
        """Execute a turn with native tool-calling loop."""
        messages, tool_defs = self._assembler.assemble(
            self._current_session, task, self._cfg.max_tokens_per_turn,
        )

        for _ in range(self._cfg.max_tool_calls_per_turn):
            self._state = OrchestratorState.PLANNING
            response = await self._resilient_chat(messages, tool_defs)
            if response is None:
                return "Sorry, I couldn't reach the AI provider. Check your network and try again."
            content = response.content

            # Use native tool_calls if adapter returned them
            tool_calls = response.tool_calls
            if not tool_calls:
                return content  # No more tool calls → final response

            # Execute each tool call
            for tc in tool_calls:
                self._state = OrchestratorState.EXECUTING
                tool_name = tc.get("function", {}).get("name", "")
                args = tc.get("function", {}).get("arguments", {})

                if isinstance(args, str):
                    import json
                    try:
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

                messages.append(Message(
                    role="assistant",
                    content="",
                    tool_calls=[tc],
                ))
                messages.append(Message(
                    role="user",
                    content=result_str,
                    tool_call_id=tc.get("id", ""),
                ))

        return content  # Max iterations reached

    async def _react_loop(self, task: str, turn_num: int) -> list[ReActStep]:
        """Execute ReAct reasoning for one turn."""
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
        """Parse model response into ReAct steps."""
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
                        thought=current_thought,
                        action=current_action,
                        is_final=is_final,
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
                        thought=current_thought,
                        action=current_action,
                        observation=observation,
                    ))
                    current_thought = ""
                    current_action = ""

            elif line.startswith("Final:") or line.startswith("Answer:"):
                current_thought += " " + line.split(":", 1)[1].strip()
                is_final = True

        if current_thought:
            steps.append(ReActStep(
                thought=current_thought,
                action=current_action,
                is_final=is_final,
            ))

        if not steps and response.strip():
            steps.append(ReActStep(
                thought=response.strip(),
                action="respond",
                is_final=True,
            ))

        return steps

    async def _execute_action(self, action: str) -> str:
        """Execute a tool action."""
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
        import uuid
        return str(uuid.uuid4())[:8]

    @property
    def state(self) -> OrchestratorState:
        return self._state

    @property
    def session(self) -> Session | None:
        return self._current_session
