"""Mistral AI adapter."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from core.adapters.base import BaseAdapter, ChatResponse, Message, ModelCapabilities, ToolDefinition
from core.errors import ProviderConfigError

logger = logging.getLogger(__name__)

DEFAULT_CONTEXT_LIMITS = {
    "mistral-large-latest": 131072,
    "mistral-medium-latest": 32768,
    "mistral-small-latest": 32768,
    "codestral-latest": 32768,
    "open-mistral-7b": 32768,
    "open-mixtral-8x7b": 32768,
    "open-mixtral-8x22b": 65536,
    "open-codestral-mamba": 256000,
    "ministral-8b-latest": 131072,
    "ministral-3b-latest": 131072,
    "default": 32768,
}


@dataclass
class MistralConfig:
    """Configuration for Mistral provider."""

    api_key: str = ""
    model: str = "mistral-large-latest"
    base_url: str = "https://api.mistral.ai/v1"
    max_context_tokens: int = 0
    max_output_tokens: int = 8192
    timeout: float = 60.0


class MistralAdapter(BaseAdapter):
    """Adapter for Mistral AI API."""

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        if not config.get("api_key"):
            raise ProviderConfigError("Mistral adapter requires api_key")
        self._cfg = MistralConfig(
            api_key=config["api_key"],
            model=config.get("model", "mistral-large-latest"),
            base_url=config.get("base_url", "https://api.mistral.ai/v1"),
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
        """Send chat request to Mistral API."""
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
            logger.error(f"Mistral API error: {e.response.status_code} - {e.response.text}")
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
        """Probe Mistral capabilities."""
        model_key = self._cfg.model.lower()
        limit = DEFAULT_CONTEXT_LIMITS.get(model_key, DEFAULT_CONTEXT_LIMITS["default"])
        if "mistral-large" in model_key:
            limit = 131072
        elif "ministral" in model_key:
            limit = 131072
        elif "open-codestral-mamba" in model_key:
            limit = 256000

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
        return "mistral"
