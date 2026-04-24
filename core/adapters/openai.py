"""OpenAI-compatible adapter (works with OpenAI, Ollama, Groq, LiteLLM)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from core.adapters.base import BaseAdapter, ChatResponse, Message, ModelCapabilities, ToolDefinition

logger = logging.getLogger(__name__)

DEFAULT_CONTEXT_LIMITS = {
    "gpt-4": 8192,
    "gpt-4-turbo": 100000,
    "gpt-4o": 100000,
    "gpt-4o-mini": 16000,
    "gpt-3.5-turbo": 16385,
    "llama": 8192,
    "mistral": 8192,
    "mixtral": 32768,
    "qwen": 8192,
    "default": 8192,
}


@dataclass
class OpenAIAdapterConfig:
    """Configuration for OpenAI-compatible providers."""

    base_url: str = "https://api.openai.com/v1"
    api_key: str = "sk-"
    model: str = "gpt-4o-mini"
    max_context_tokens: int = 16000
    max_output_tokens: int = 4096
    timeout: float = 60.0


class OpenAIAdapter(BaseAdapter):
    """Adapter for OpenAI-compatible APIs (OpenAI, Ollama, Groq, LiteLLM)."""

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._cfg = OpenAIAdapterConfig(
            base_url=config.get("base_url", "https://api.openai.com/v1"),
            api_key=config.get("api_key", ""),
            model=config.get("model", "gpt-4o-mini"),
            max_context_tokens=config.get("max_context_tokens", 16000),
            max_output_tokens=config.get("max_output_tokens", 4096),
            timeout=config.get("timeout", 60.0),
        )
        self._client: httpx.AsyncClient | None = None
        self._capabilities: ModelCapabilities | None = None

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
        """Convert ToolDefinition list to OpenAI function format."""
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
        """Send chat request to OpenAI-compatible API."""
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
            logger.error(f"OpenAI API error: {e.response.status_code} - {e.response.text}")
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
                    # Parse and yield chunks
                    # This is a simplified streaming handler
                    yield line[6:]

    async def probe_capabilities(self) -> ModelCapabilities:
        """Probe provider capabilities."""
        base_model = self._cfg.model.split("-")[0].split(":")[0]
        context_limit = DEFAULT_CONTEXT_LIMITS.get(base_model, DEFAULT_CONTEXT_LIMITS["default"])

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
        """Return provider type string."""
        url = self._cfg.base_url.lower()
        if "anthropic" in url:
            return "anthropic"
        elif "ollama" in url or "localhost" in url:
            return "ollama"
        elif "groq" in url:
            return "groq"
        elif "azure" in url:
            return "azure"
        else:
            return "openai"
