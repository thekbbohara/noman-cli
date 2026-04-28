"""Orchestrator with ReAct loop."""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from core.adapters import BaseAdapter, Message
from core.adapters.base import ToolDefinition
from core.context import ContextManager
from core.errors.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError
from core.memory import MemorySystem
from core.tools import ToolBus
from core.utils.prompt_budget import PromptBudgetConfig, PromptContributor, apply_prompt_part_budget
from core.utils.retry import RetryConfig, RetryManager
from core.wiki import Wiki

logger = logging.getLogger(__name__)
if os.environ.get("NOMAN_DEBUG"):
    logging.getLogger().setLevel(logging.DEBUG)
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)


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
    def __init__(
        self,
        tools: ToolBus,
        context: ContextManager | None = None,
        wiki: Wiki | None = None,
    ) -> None:
        self._tools = tools
        self._context = context
        self._wiki = wiki

    @property
    def available_tools(self) -> str:
        """Dynamically generate the tool list from registered tools."""
        tool_names = self._tools.list_tools() or []
        return ", ".join(tool_names)

    @property
    def system_prompt(self) -> str:
        tools_list = self.available_tools
        wiki_info = ""
        if self._wiki:
            summary = self._wiki.graph.summarize()
            wiki_info = f"""

Knowledge graph: {summary['entity_count']} entities, {summary['edge_count']} edges."""

        return f"""You are NoMan, autonomous coding agent.

IMPORTANT RULES:
- Only call tools when task actually needs file/command execution  
- After tool result, PROVIDE YOUR ANSWER first, then add "Done." at the end
- Never respond with just "Done." alone — include your actual answer before it

TOKEN-SAVING FORMAT (always prefer):
- Plain text over markdown: no headings, bullets, code fences, or speaker labels when possible
- Short labels: prefer concise over verbose
- Lean refs: `[tool 1] arg` not `ToolName(arg=value)` full form
- Skip summaries: omit link destinations, label quotes, filler politeness

RESPONSE FORMAT:

Tool call — staging + _____tool block:
tool_name arg1=value1

Final — YOUR ANSWER + "Done."
Example: "The project has 50 files. Done."

_____tool separator triggers tool call.

Available: {tools_list}{wiki_info}

Workflow:
1. REASON - think
2. ACT - call tool if needed
3. OBSERVE - process result
4. FINAL - give answer + Done."""

    def _count_tokens(self, text: str) -> int:
        """Estimate token count (rough ~4 chars per token)."""
        return max(1, len(text) // 4)

    def assemble(
        self, session: Session, task: str, budget: int,
    ) -> tuple[list[Message], list[ToolDefinition]]:
        messages: list[Message] = []

        # Build budget config
        budget_config = PromptBudgetConfig(max_tokens=budget)

        # 1. System prompt (always first)
        system_text = self.system_prompt
        system_tokens = self._count_tokens(system_text)

        # Apply system budget with trimming if needed
        if system_tokens > budget_config.system_budget:
            # Trim system prompt
            ratio = budget_config.system_budget / max(1, system_tokens)
            chars = int(len(system_text) * ratio)
            system_text = system_text[:chars].rsplit("\n", 1)[0]

        messages.append(Message(role="system", content=system_text))

        # 2. Convert session.turns into messages (last 10 turns = 5 user/assistant pairs)
        # Use budget config to trim history
        history_contributors: list[PromptContributor] = []

        recent_turns = session.turns[-10:]  # 10 turns max to avoid token overflow
        for i, turn in enumerate(recent_turns):
            # Build history text
            history_text = f"User: {turn.user_input}"
            if turn.assistant_output:
                history_text += f"\nAssistant: {turn.assistant_output}"
            for result in turn.tool_results:
                history_text += f"\nResult: {result}"

            history_contributors.append(PromptContributor(
                key=f"turn_{i}",
                original_text=history_text,
                token_count=self._count_tokens(history_text),
                order=i,
                trim_priority=10,
            ))

        # Apply history budget with thresholded trimming
        history_contributors = apply_prompt_part_budget(
            history_contributors,
            budget_config.history_budget,
            self._count_tokens,
        )

        for contributor in history_contributors:
            messages.append(Message(role="user", content=contributor.current_text))

        # 3. Current task
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
    MAX_TOOL_ITERATIONS = 100  # Allow many iterations for complex tasks

    def __init__(
        self,
        adapter: BaseAdapter,
        tools: ToolBus,
        config: OrchestratorConfig | None = None,
        context: ContextManager | None = None,
        memory: MemorySystem | None = None,
        wiki: Wiki | None = None,
    ) -> None:
        self._adapter = adapter
        self._tools = tools
        self._cfg = config or OrchestratorConfig()
        self._context = context
        self._memory = memory
        self._wiki = wiki
        self._assembler = PromptAssembler(tools, context, wiki)
        self._state = OrchestratorState.IDLE
        self._current_session: Session | None = None
        self._breaker = CircuitBreaker("adapter")
        self._retry = RetryManager(RetryConfig(
            max_attempts=3,
            base_delay_sec=1.0,
            retryable_exceptions=(ConnectionError, TimeoutError),
        ))
        self._context_tokens: int | None = None

        # Restore session from disk if it exists
        self._load_session()

    async def _probe_context_tokens(self) -> int:
        """Probe adapter for context window size."""
        try:
            caps = await self._adapter.capabilities()
            return caps.max_context_tokens
        except Exception:
            logger.warning("Could not probe context window, using default")
            return self._cfg.max_tokens_per_turn

    @property
    def tool_bus(self) -> ToolBus:
        """Access tool bus."""
        return self._tools

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
        except (ConnectionError, TimeoutError, httpx.HTTPError, httpx.TimeoutException) as e:
            logger.error("Adapter call failed after retries: %s", e)
            return None
        except Exception as e:
            logger.exception("Unexpected adapter error: %s", e)
            return None
        finally:
            self._save_debug(messages)

    async def run(self, task: str) -> str:
        # Simple inputs that don't need the model
        simple_greetings = {"hi", "hello", "hey", "hi there", "hello!", "hey!", "hi!", "hi."}
        if task.lower().strip().rstrip("!").rstrip(".") in simple_greetings:
            return "Hello! I'm NoMan. What would you like me to help you with?"

        # Load latest session from disk before processing
        self._load_session()

        # Reuse existing session or create new one
        if self._current_session is None:
            self._current_session = Session(id=self._new_session_id())
            logger.info("Created new session %s", self._current_session.id)

        turn = Turn(user_input=task)
        response = await self._execute_turn_with_tools(task)
        turn.assistant_output = response
        self._current_session.turns.append(turn)

        # Persist session to disk
        self._save_session()

        return response

    def reset_session(self) -> None:
        """Reset the current session. Call from TUI on /reset command."""
        self._current_session = None
        # Remove persisted session file
        session_dir = Path.home() / ".noman" / "sessions"
        if session_dir.exists():
            for f in session_dir.glob("*.json"):
                f.unlink()
        logger.info("Session reset and disk files cleared")

    def _get_session_path(self) -> Path:
        """Get the session file path in current dir."""
        session_dir = Path.home() / ".noman" / "sessions"
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir / "active_session.json"

    def _save_session(self) -> None:
        """Persist current session to disk."""
        if not self._current_session:
            return
        session_path = self._get_session_path()
        turns_data = [
            {
                "user_input": t.user_input,
                "assistant_output": t.assistant_output,
                "tool_calls": t.tool_calls,
                "tool_results": t.tool_results,
                "tokens_used": t.tokens_used,
            }
            for t in self._current_session.turns
        ]
        data = {
            "id": self._current_session.id,
            "turns": turns_data,
            "total_tokens": self._current_session.total_tokens,
            "created_at": self._current_session.created_at,
        }
        session_path.write_text(json.dumps(data, indent=2))

    def _load_session(self) -> None:
        """Restore session from disk if it exists."""
        session_path = self._get_session_path()
        if not session_path.exists():
            return
        try:
            data = json.loads(session_path.read_text())
            turns = [
                Turn(
                    user_input=t["user_input"],
                    assistant_output=t.get("assistant_output", ""),
                    tool_calls=t.get("tool_calls", []),
                    tool_results=t.get("tool_results", []),
                    tokens_used=t.get("tokens_used", 0),
                )
                for t in data["turns"]
            ]
            self._current_session = Session(
                id=data["id"],
                turns=turns,
                total_tokens=data.get("total_tokens", 0),
                created_at=data.get("created_at", 0.0),
            )
            logger.info("Loaded session with %d turns", len(turns))
        except Exception as e:
            logger.error("Failed to load session: %s", e)

    async def _execute_turn_with_tools(self, task: str) -> str:
        if self._current_session is None:
            return "No active session. Start a session first."
        if self._context_tokens is None:
            self._context_tokens = await self._probe_context_tokens()
        budget = int(self._context_tokens * 0.8)
        assert self._current_session is not None
        messages, tool_defs = self._assembler.assemble(
            self._current_session, task, budget,
        )

        consecutive_non_tool_responses = 0
        last_tool_called = None
        same_tool_count = 0
        request_count = 0
        for iteration in range(self.MAX_TOOL_ITERATIONS):
            self._state = OrchestratorState.PLANNING
            request_count += 1
            logger.debug(f"Request #{request_count}, iteration={iteration}")
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
            logger.debug(f"is_final={is_final}, parsed_calls={len(parsed_calls) if parsed_calls else 0}, api_tool_calls={len(tool_calls) if tool_calls else 0}")
            # If API returns tool_calls but parse found none, use API tool_calls
            if not parsed_calls and tool_calls:
                logger.debug("Using API tool_calls directly")
                parsed_calls = tool_calls

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
                logger.debug(f"Returning final: content={repr(content[:50] if content else '')}, raw={repr(raw_content[:50] if raw_content else '')}")
                return content or raw_content

            # is_final = false → must have tool_calls
            if not parsed_calls:
                messages.append(Message(role="assistant", content=raw_content))
                messages.append(Message(
                    role="user",
                    content=(
                        "ERROR: f:false but no t. "
                        "Call tool(s), then respond with f:true when done."
                    ),
                ))
                continue

            consecutive_non_tool_responses = 0

            for tc in parsed_calls:
                self._state = OrchestratorState.EXECUTING
                tool_name = tc.get("function", {}).get("name", "") or tc.get("tool", "")
                args = tc.get("function", {}).get("arguments", {}) or tc.get("args", {})
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
                # Summarize large tool results to preserve key info
                if len(result_str) > 10000:
                    summarized = self._summarize_result(result_str, tool_name)
                    logger.info("Summarized %s result: %d -> %d chars", tool_name, len(result_str), len(summarized))
                    result_str = summarized
                messages.append(Message(
                    role="user", content=result_str, tool_call_id=tc.get("id", ""),
                ))

                # Track same-tool repetition
                if tool_name == last_tool_called:
                    same_tool_count += 1
                    if same_tool_count >= 2:
                        logger.warning("Model repeated tool %s twice, returning last result")
                        return f"Tool {tool_name} returned: {result_str}"
                else:
                    last_tool_called = tool_name
                    same_tool_count = 0

        return raw_content or "Max tool call iterations reached."

    def _summarize_result(self, result: str, tool_name: str) -> str:
        """Summarize large tool results to preserve key information."""
        lines = result.strip().split("\n")
        line_count = len(lines)

        # Summarize by type
        if tool_name == "get_file_tree":
            dirs = [l for l in lines if l.endswith("/")]
            files = [l for l in lines if not l.endswith("/")]
            return f"Project structure: {len(dirs)} directories, {len(files)} files\nTop directories: {dirs[:10]}\nTop files: {files[:10]}"

        elif tool_name == "search_code":
            # Count matches and show first few
            matches = [l for l in lines if ":" in l][:10]
            return f"Found ~{line_count} matches. First 10:\n" + "\n".join(matches)

        elif tool_name == "list_dir":
            dirs = [l for l in lines if l.endswith("/")]
            files = [l for l in lines if not l.endswith("/")]
            return f"{len(dirs)} dirs, {len(files)} files: {lines[:20]}"

        elif tool_name == "read_file":
            return f"File has {line_count} lines. First 100 lines:\n" + "\n".join(lines[:100])

        # Generic: show first + last chunks
        return f"Output: {line_count} lines. First 20:\n" + "\n".join(lines[:20])

    def _parse_response(
        self, raw_content: str, api_tool_calls: list,
    ) -> tuple[bool, str, list]:
        """Parse _____tool format only (most token-efficient)."""
        # Match any number of underscores (model sometimes uses 6)
        import re
        TOOL_PATTERN = re.compile(r'_+tool\b')

        if not raw_content:
            return False, "", api_tool_calls or []

        raw = raw_content.strip()

        # Check for _____tool block (any underscore count)
        if TOOL_PATTERN.search(raw):
            lines = raw.split("\n")
            tool_calls = []
            staging = []
            in_tool_block = False
            found_tool_call = False

            for line in lines:
                if TOOL_PATTERN.search(line):
                    in_tool_block = True
                    found_tool_call = True
                    # If tool call is on same line (e.g., "_____tool list_dir path=.")
                    # parse it immediately instead of skipping
                    match = TOOL_PATTERN.search(line)
                    if match:
                        rest = line[match.end():].strip()
                        if rest:
                            parts = rest.split()
                            if parts and parts[0]:
                                tool_name = parts[0].strip()
                                if tool_name.replace("_", "").replace("-", "").isalnum() and tool_name in self._tools.list_tools():
                                    args = {}
                                    for part in parts[1:]:
                                        if "=" in part:
                                            k, v = part.split("=", 1)
                                            args[k] = v
                                    tool_calls.append({"tool": tool_name, "args": args})
                                    logger.debug(f"Parsed inline tool: {tool_name} {args}")
                                    continue
                    continue
                if in_tool_block:
                    line = line.strip()
                    if line in ("f:true", "f:false") or line.startswith("f:") or line.startswith("<"):
                        continue
                    parts = line.split()
                    if parts and parts[0]:
                        tool_name = parts[0].strip()
                        if tool_name in ("f:true", "f:false") or tool_name.startswith("f:") or tool_name.startswith("<"):
                            logger.debug(f"Skipping f: marker: {tool_name}")
                            continue
                        if not tool_name.replace("_", "").replace("-", "").isalnum():
                            logger.debug(f"Skipping non-alnum tool: {tool_name}")
                            continue
                        if tool_name not in self._tools.list_tools():
                            logger.debug(f"Skipping unknown tool: {tool_name}")
                            continue
                        args = {}
                        for part in parts[1:]:
                            if "=" in part:
                                k, v = part.split("=", 1)
                                args[k] = v
                        if tool_name and tool_name in self._tools.list_tools():
                            tool_calls.append({"tool": tool_name, "args": args})
                            found_tool_call = True
                elif line.strip():
                    staging.append(line.strip())

            if tool_calls:
                return False, " ".join(staging), tool_calls

        # Plain answer is final (Done variants, or f:true)
        short = raw.strip().lower()
        logger.debug(f"parse_response checking: raw={repr(raw[:100])}, short={repr(short)}")
        # Check for f:true at end (with possible content before it)
        is_final = short == "f:true" or short.endswith("\nf:true") or short.endswith(" f:true")
        if not is_final:
            is_final = short in ("done.", "done", "completed", "finished")
        if not is_final:
            is_final = len(raw) < 30 and "tool" not in short and short.startswith("done")
        # Extract content before f:true/done if present
        content = raw
        if is_final:
            # Check for markers at end (with possible content before)
            for marker in ["\nf:true", " f:true", "\nDone.", " Done.", "Done.", "done", "Done", "f:true"]:
                if raw.strip().endswith(marker):
                    content = raw.strip()[:-len(marker)].strip()
                    break
            # If content is empty but there's text, use full raw
            if not content and raw.strip():
                content = raw.strip()
        return is_final, content, []

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
            tool_name = tc["name"]
            result.append({
                "id": tc.get("id", f"call_{tool_name}"),
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": tc.get("args") or tc.get("arguments") or "{}",
                },
            })
        elif "tool_calls" in tc:
            result.extend(_flatten_tool_calls(tc["tool_calls"]))
    return result
