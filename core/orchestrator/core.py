"""Orchestrator with ReAct loop."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.adapters import BaseAdapter, Message
from core.context import ContextManager, ContextView
from core.errors import BudgetExceededError
from core.memory import MemorySystem
from core.tools import ToolBus

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

Available tools: {tool_names}

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
    ) -> list[Message]:
        """Assemble prompt for a turn."""
        messages: list[Message] = []

        # System prompt
        tool_names = ", ".join(self._tools.list_tools() or ["none"])
        system_content = self.SYSTEM_PROMPT.format(tool_names=tool_names)
        messages.append(Message(role="system", content=system_content))

        # Prior turns (truncated to fit budget)
        remaining = budget - len(system_content)
        for turn in session.turns[-5:]:
            if turn.assistant_output:
                messages.append(Message(
                    role="assistant",
                    content=turn.assistant_output,
                ))
                remaining -= len(turn.assistant_output)

            for result in turn.tool_results:
                messages.append(Message(
                    role="user",
                    content=f"Result: {result}",
                ))
                remaining -= len(result)

            if remaining < 1000:
                break

        # Current task
        messages.append(Message(role="user", content=task))

        return messages


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

    async def run(self, task: str) -> str:
        """Run a task to completion. Returns final response."""
        self._current_session = Session(id=self._new_session_id())

        # Execute turn with potential tool calls
        turn = Turn(user_input=task)
        response = await self._execute_turn_with_tools(task)
        turn.assistant_output = response
        self._current_session.turns.append(turn)

        return response

    async def _execute_turn_with_tools(self, task: str) -> str:
        """Execute a turn with tool call parsing and execution."""
        messages = self._assembler.assemble(
            self._current_session,
            task,
            self._cfg.max_tokens_per_turn,
        )

        for _ in range(self._cfg.max_tool_calls_per_turn):
            self._state = OrchestratorState.PLANNING
            response = await self._adapter.chat(messages)
            content = response.content

            # Check for tool call pattern: `run_shell "command"`
            tool_result = await self._maybe_execute_tool(content)
            if tool_result is None:
                # No tool call detected, return as final response
                return content

            # Tool was executed, add result and continue loop
            self._state = OrchestratorState.EXECUTING
            result_str = str(tool_result)
            messages.append(Message(role="assistant", content=content))
            messages.append(Message(role="user", content=f"Result: {result_str}"))

        # Max iterations reached
        return content

    async def _maybe_execute_tool(self, response: str) -> str | None:
        """Parse and execute tool call from response. Returns None if no tool call."""
        import re

        # Match patterns like: run_shell "pwd", run_shell 'pwd', run_shell(pwd)
        patterns = [
            r'run_shell\s+["\']([^"\']+)["\']',
            r'run_shell\s*\(\s*["\']([^"\']+)["\']\s*\)',
            r'run_shell\(["\']([^"\']+)["\']\)',
        ]

        for pattern in patterns:
            match = re.search(pattern, response)
            if match:
                command = match.group(1)
                print(f"Executing: run_shell {command!r}")
                try:
                    result = await self._tools.execute("run_shell", {"command": command})
                    print(f"Result: {result!r}")
                    return result
                except Exception as e:
                    print(f"Error: {e}")
                    return f"Error: {e}"

        # Fallback: try to extract any shell command
        match = re.search(r'`(pwd|ls|ls -la|cat .+?)`', response)
        if match:
            command = match.group(1)
            print(f"Fallback executing: {command!r}")
            try:
                result = await self._tools.execute("run_shell", {"command": command})
                return result
            except Exception as e:
                return f"Error: {e}"

        return None

    async def _react_loop(self, task: str, turn_num: int) -> list[ReActStep]:
        """Execute ReAct reasoning for one turn."""
        # Get context
        context_view: ContextView | None = None
        if self._context:
            context_view = self._context.get_context(self._cfg.max_tokens_per_turn)

        # Assemble messages
        messages = self._assembler.assemble(
            self._current_session,
            task,
            self._cfg.max_tokens_per_turn,
        )

        # Get tool definitions
        tool_defs = None
        tool_list = self._tools.list_tools()
        if tool_list:
            # Simplified - would use ToolDefinition from bus
            tool_defs = None

        # Call model
        self._state = OrchestratorState.PLANNING
        response = await self._adapter.chat(messages, tool_defs)

        # Parse response into ReAct steps
        steps = self._parse_react_response(response.content)

        if not steps:
            # Plain response - treat as final answer
            steps = [
                ReActStep(
                    thought=response.content,
                    action="respond",
                    is_final=True,
                )
            ]

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

        # If no valid steps, treat entire response as final answer
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

        # Parse action (simple format: "tool_name arg")
        parts = action.split(maxsplit=1)
        if not parts:
            return "No action specified"

        tool_name = parts[0]
        args = {}
        if len(parts) > 1:
            # Simple arg parsing
            arg_parts = parts[1].split()
            for ap in arg_parts:
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
