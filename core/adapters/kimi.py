"""Moonshot/Kimi adapter."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from core.adapters.base import BaseAdapter, ChatResponse, Message, ModelCapabilities, ToolDefinition
from core.errors import ProviderConfigError

logger = logging.getLogger(__name__)

DEFAULT_CONTEXT_LIMITS = {
    "moonshot-v1-8k": 8192,
    "moonshot-v1-32k": 32768,
    "moonshot-v1-128k": 131072,
    "kimi-k2": 131072,
    "default": 8192,
}


@dataclass
class KimiConfig:
    """Configuration for Moonshot/Kimi provider."""

    api_key: str = ""
    model: str = "moonshot-v1-128k"
    base_url: str = "https://api.moonshot.cn/v1"
    max_context_tokens: int = 0
    max_output_tokens: int = 8192
    timeout: float = 60.0


class KimiAdapter(BaseAdapter):
    """Adapter for Moonshot/Kimi API (OpenAI-compatible)."""

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        if not config.get("api_key"):
            raise ProviderConfigError("Kimi adapter requires api_key")
        self._cfg = KimiConfig(
            api_key=config["api_key"],
            model=config.get("model", "moonshot-v1-128k"),
            base_url=config.get("base_url", "https://api.moonshot.cn/v1"),
            max_context_tokens=config.get("max_context_tokens", 0),
            max_output_tokens=config.get("max_output_tokens", 8192),
            timeout=config.get("timeout", 60.0),
        )
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._cfg.base_url,
                headers={
                    "Authorization": f"Bearer {self._cfg.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self._cfg.timeout,
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _to_openai_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        """Convert Message list to OpenAI format."""
        result = []
        for msg in messages:
            m: dict[str, Any] = {"role": msg.role, "content": msg.content}
            if msg.tool_call_id:
                m["tool_call_id"] = msg.tool_call_id
            if msg.tool_calls:
                m["tool_calls"] = msg.tool_calls
            result.append(m)
        return result

    def _to_openai_tools(self, tools: list[ToolDefinition]) -> list[dict[str, Any]]:
        """Convert ToolDefinition to OpenAI function format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        stream: bool = False,
    ) -> ChatResponse | Any:
        """Send chat request to Kimi/Moonshot API."""
        client = await self._get_client()

        payload: dict[str, Any] = {
            "model": self._cfg.model,
            "messages": self._to_openai_messages(messages),
            "stream": stream,
        }

        if tools:
            payload["tools"] = self._to_openai_tools(tools)

        try:
            if stream:
                return self._stream_response(client, payload)
            else:
                resp = await client.post("/chat/completions", json=payload)
                resp.raise_for_status()
                data = resp.json()

                return ChatResponse(
                    content=data["choices"][0]["message"]["content"],
                    tool_calls=data["choices"][0]["message"].get("tool_calls", []),
                    usage={
                        "prompt_tokens": data.get("usage", {}).get("prompt_tokens", 0),
                        "completion_tokens": data.get("usage", {}).get("completion_tokens", 0),
                        "total_tokens": data.get("usage", {}).get("total_tokens", 0),
                    },
                    model=data.get("model", self._cfg.model),
                )
        except httpx.HTTPStatusError as e:
            logger.error(f"Kimi API error: {e.response.status_code} - {e.response.text}")
            raise

    async def _stream_response(
        self, client: httpx.AsyncClient, payload: dict[str, Any]
    ) -> Any:
        """Handle streaming responses."""
        async with client.stream("POST", "/chat/completions", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    if line == "data: [DONE]":
                        break
                    yield line[6:]

    async def probe_capabilities(self) -> ModelCapabilities:
        """Probe Kimi capabilities."""
        model_key = self._cfg.model.lower()
        limit = DEFAULT_CONTEXT_LIMITS.get(model_key, DEFAULT_CONTEXT_LIMITS["default"])
        if "moonshot-v1-128k" in model_key:
            limit = 131072
        elif "moonshot-v1-32k" in model_key:
            limit = 32768
        elif "moonshot-v1-8k" in model_key:
            limit = 8192
        elif "kimi-k2" in model_key:
            limit = 131072

        max_ctx = self._cfg.max_context_tokens or limit
        return ModelCapabilities(
            model_name=self._cfg.model,
            max_context_tokens=max_ctx,
            max_output_tokens=self._cfg.max_output_tokens,
            supports_tool_calling=True,
            supports_streaming=True,
            safe_context_limit=int(max_ctx * 0.8),
        )

    @property
    def provider_type(self) -> str:
        return "kimi"
