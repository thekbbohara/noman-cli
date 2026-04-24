"""Anthropic adapter for Claude models."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from core.adapters.base import BaseAdapter, ChatResponse, Message, ModelCapabilities, ToolDefinition

logger = logging.getLogger(__name__)

DEFAULT_CONTEXT_LIMITS = {
    "claude-3-opus": 200000,
    "claude-3-sonnet": 200000,
    "claude-3-5-sonnet": 200000,
    "claude-3-haiku": 200000,
    "claude-sonnet": 200000,
    "claude-opus": 200000,
    "claude-haiku": 200000,
    "default": 100000,
}


@dataclass
class AnthropicConfig:
    """Configuration for Anthropic provider."""

    api_key: str = ""
    model: str = "claude-sonnet-4-20250514"
    max_context_tokens: int = 200000
    max_output_tokens: int = 8192
    timeout: float = 60.0


class AnthropicAdapter(BaseAdapter):
    """Adapter for Anthropic Claude API."""

    API_VERSION = "2023-06-01"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._cfg = AnthropicConfig(
            api_key=config.get("api_key", ""),
            model=config.get("model", "claude-sonnet-4-20250514"),
            max_context_tokens=config.get("max_context_tokens", 200000),
            max_output_tokens=config.get("max_output_tokens", 8192),
            timeout=config.get("timeout", 60.0),
        )
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url="https://api.anthropic.com",
                headers={
                    "x-api-key": self._cfg.api_key,
                    "anthropic-version": self.API_VERSION,
                    "Content-Type": "application/json",
                },
                timeout=self._cfg.timeout,
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _to_anthropic_messages(
        self, messages: list[Message]
    ) -> list[dict[str, Any]]:
        """Convert Message list to Anthropic format."""
        result = []
        for msg in messages:
            if msg.role == "tool":
                result.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": msg.tool_call_id,
                            "content": msg.content,
                        }
                    ],
                })
            else:
                content = msg.content
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        content += f"\n\n[Tool call: {tc}]"
                result.append({"role": msg.role, "content": content})
        return result

    def _to_anthropic_tools(self, tools: list[ToolDefinition]) -> list[dict[str, Any]]:
        """Convert ToolDefinition to Anthropic tool format."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.parameters,
            }
            for t in tools
        ]

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        stream: bool = False,
    ) -> ChatResponse | Any:
        """Send chat request to Anthropic API."""
        client = await self._get_client()

        payload: dict[str, Any] = {
            "model": self._cfg.model,
            "messages": self._to_anthropic_messages(messages),
            "max_tokens": self._cfg.max_output_tokens,
            "stream": stream,
        }

        if tools:
            payload["tools"] = self._to_anthropic_tools(tools)

        try:
            if stream:
                return self._stream_response(client, payload)
            else:
                resp = await client.post("/v1/messages", json=payload)
                resp.raise_for_status()
                data = resp.json()

                content = ""
                tool_calls = []
                for block in data.get("content", []):
                    if block.get("type") == "text":
                        content += block.get("text", "")
                    elif block.get("type") == "tool_use":
                        tool_calls.append({
                            "id": block.get("id"),
                            "name": block.get("name"),
                            "input": block.get("input", {}),
                        })

                return ChatResponse(
                    content=content,
                    tool_calls=tool_calls,
                    usage={
                        "prompt_tokens": data.get("usage", {}).get("input_tokens", 0),
                        "completion_tokens": data.get("usage", {}).get("output_tokens", 0),
                        "total_tokens": data.get("usage", {}).get("input_tokens", 0)
                        + data.get("usage", {}).get("output_tokens", 0),
                    },
                    model=data.get("model", self._cfg.model),
                )
        except httpx.HTTPStatusError as e:
            logger.error(f"Anthropic API error: {e.response.status_code}")
            raise

    async def _stream_response(
        self, client: httpx.AsyncClient, payload: dict[str, Any]
    ) -> Any:
        """Handle streaming responses."""
        async with client.stream("POST", "/v1/messages", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    if line == "data: [DONE]":
                        break
                    yield line[6:]

    async def probe_capabilities(self) -> ModelCapabilities:
        """Probe Anthropic capabilities."""
        model_id = self._cfg.model.split("-")[0]
        context_limit = DEFAULT_CONTEXT_LIMITS.get(
            self._cfg.model.split("-")[0], DEFAULT_CONTEXT_LIMITS["default"]
        )

        return ModelCapabilities(
            model_name=self._cfg.model,
            max_context_tokens=self._cfg.max_context_tokens or context_limit,
            max_output_tokens=self._cfg.max_output_tokens,
            supports_tool_calling=True,
            supports_streaming=True,
            safe_context_limit=int(context_limit * 0.8),
        )

    @property
    def provider_type(self) -> str:
        return "anthropic"
