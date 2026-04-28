"""Custom/generic adapter for arbitrary OpenAI-compatible endpoints."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from core.adapters.base import BaseAdapter, ChatResponse, Message, ModelCapabilities, ToolDefinition
from core.errors import ProviderConfigError

logger = logging.getLogger(__name__)

DEFAULT_CONTEXT_LIMITS = {
    "default": 8192,
}


@dataclass
class CustomConfig:
    """Configuration for custom endpoint."""

    api_key: str = ""
    model: str = ""
    base_url: str = ""
    max_context_tokens: int = 0
    max_output_tokens: int = 4096
    timeout: float = 60.0
    headers: dict[str, str] = None  # type: ignore[assignment]
    extra_params: dict[str, Any] = None  # type: ignore[assignment]


class CustomAdapter(BaseAdapter):
    """Adapter for arbitrary OpenAI-compatible endpoints."""

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        base_url = config.get("base_url", "")
        if not base_url:
            raise ProviderConfigError("Custom adapter requires base_url")
        self._cfg = CustomConfig(
            api_key=config.get("api_key", ""),
            model=config.get("model", ""),
            base_url=base_url,
            max_context_tokens=config.get("max_context_tokens", 0),
            max_output_tokens=config.get("max_output_tokens", 4096),
            timeout=config.get("timeout", 60.0),
            headers=config.get("headers", {}),
            extra_params=config.get("extra_params", {}),
        )
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {
                "Content-Type": "application/json",
            }
            if self._cfg.api_key:
                headers["Authorization"] = f"Bearer {self._cfg.api_key}"
            # Merge custom headers
            if self._cfg.headers:
                headers.update(self._cfg.headers)
            self._client = httpx.AsyncClient(
                base_url=self._cfg.base_url,
                headers=headers,
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
                openai_tool_calls = []
                for tc in msg.tool_calls:
                    if "function" in tc:
                        openai_tool_calls.append(tc)
                    elif "tool" in tc and "args" in tc:
                        openai_tool_calls.append({
                            "type": "function",
                            "function": {
                                "name": tc["tool"],
                                "arguments": json.dumps(tc["args"]) if tc["args"] else "{}"
                            }
                        })
                m["tool_calls"] = openai_tool_calls if openai_tool_calls else None
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
        """Send chat request to custom endpoint."""
        client = await self._get_client()

        payload: dict[str, Any] = {
            "model": self._cfg.model,
            "messages": self._to_openai_messages(messages),
            "stream": stream,
        }

        if tools:
            payload["tools"] = self._to_openai_tools(tools)

        # Merge extra params from config
        payload.update(self._cfg.extra_params or {})

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
            logger.error(f"Custom endpoint error: {e.response.status_code} - {e.response.text}")
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
        """Probe custom endpoint capabilities."""
        max_ctx = self._cfg.max_context_tokens or DEFAULT_CONTEXT_LIMITS["default"]
        return ModelCapabilities(
            model_name=self._cfg.model or "custom",
            max_context_tokens=max_ctx,
            max_output_tokens=self._cfg.max_output_tokens,
            supports_tool_calling=True,
            supports_streaming=True,
            safe_context_limit=int(max_ctx * 0.8),
        )

    @property
    def provider_type(self) -> str:
        return "custom"
