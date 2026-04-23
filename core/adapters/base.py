"""Model adapter base with OpenAI-compatible contract."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Dict, List

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Message:
    role: str  # system | user | assistant | tool
    content: str
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    tool_call_id: str | None = None


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema


@dataclass
class ChatResponse:
    content: str
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    usage: Dict[str, int] = field(default_factory=dict)
    model: str = ""


@dataclass(frozen=True)
class ModelCapabilities:
    model_name: str
    max_context_tokens: int
    max_output_tokens: int
    supports_tool_calling: bool
    supports_streaming: bool
    safe_context_limit: int  # 80 % of max for headroom


class BaseAdapter(ABC):
    """Abstract contract every LLM backend must satisfy."""

    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config
        self._capabilities: ModelCapabilities | None = None

    @abstractmethod
    async def chat(
        self,
        messages: List[Message],
        tools: List[ToolDefinition] | None = None,
        stream: bool = False,
    ) -> ChatResponse | AsyncIterator[str]:
        ...

    @abstractmethod
    async def probe_capabilities(self) -> ModelCapabilities:
        """Probe (and cache) provider capabilities."""
        ...

    async def capabilities(self) -> ModelCapabilities:
        if self._capabilities is None:
            self._capabilities = await self.probe_capabilities()
        return self._capabilities

    @property
    def role(self) -> str:
        """Return the configured role (planner/executor/critic/embedder)."""
        return self.config.get("role", "executor")
