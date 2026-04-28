"""Google Gemini adapter."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from core.adapters.base import BaseAdapter, ChatResponse, Message, ModelCapabilities, ToolDefinition
from core.errors import ProviderConfigError

logger = logging.getLogger(__name__)

DEFAULT_CONTEXT_LIMITS = {
    "gemini-2.5-pro": 1048576,
    "gemini-2.5-flash": 1048576,
    "gemini-2.0-flash": 1048576,
    "gemini-1.5-pro": 2097152,
    "gemini-1.5-flash": 1048576,
    "gemini-pro": 32768,
    "default": 32768,
}


@dataclass
class GeminiConfig:
    """Configuration for Google Gemini provider."""

    api_key: str = ""
    model: str = "gemini-2.5-flash"
    base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    max_context_tokens: int = 0
    max_output_tokens: int = 8192
    timeout: float = 60.0


class GeminiAdapter(BaseAdapter):
    """Adapter for Google Gemini API."""

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        if not config.get("api_key"):
            raise ProviderConfigError("Gemini adapter requires api_key")
        self._cfg = GeminiConfig(
            api_key=config["api_key"],
            model=config.get("model", "gemini-2.5-flash"),
            base_url=config.get("base_url", "https://generativelanguage.googleapis.com/v1beta"),
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
                    "x-goog-api-key": self._cfg.api_key,
                    "Content-Type": "application/json",
                },
                timeout=self._cfg.timeout,
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _to_gemini_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        """Convert Message list to Gemini format."""
        parts = []
        for msg in messages:
            if msg.role == "system":
                continue  # Gemini uses system_instruction instead
            parts.append({
                "role": "user" if msg.role == "user" else "model",
                "parts": [{"text": msg.content}],
            })
        return parts

    def _to_gemini_tools(self, tools: list[ToolDefinition]) -> list[dict[str, Any]]:
        """Convert ToolDefinition to Gemini function format."""
        return [
            {
                "functionDeclarations": [
                    {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    }
                ]
            }
            for t in tools
        ]

    def _to_gemini_system(self, messages: list[Message]) -> str | None:
        """Extract system message for Gemini system_instruction."""
        for msg in messages:
            if msg.role == "system":
                return msg.content
        return None

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        stream: bool = False,
    ) -> ChatResponse | Any:
        """Send chat request to Gemini API."""
        client = await self._get_client()
        model_name = self._cfg.model.replace("models/", "")

        payload: dict[str, Any] = {
            "contents": self._to_gemini_messages(messages),
            "generationConfig": {
                "maxOutputTokens": self._cfg.max_output_tokens,
                "stream": stream,
            },
        }

        system = self._to_gemini_system(messages)
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        if tools:
            payload["tools"] = self._to_gemini_tools(tools)

        try:
            if stream:
                return self._stream_response(client, model_name, payload)
            else:
                resp = await client.post(f"/chat/{model_name}")
                resp.raise_for_status()
                data = resp.json()

                candidates = data.get("candidates", [])
                if not candidates:
                    return ChatResponse(content="", model=self._cfg.model)

                choice = candidates[0]
                content_part = choice["content"]["parts"][0] if choice["content"].get("parts") else {}
                content = content_part.get("text", "")

                tool_calls = []
                for part in choice["content"].get("parts", []):
                    if "functionCall" in part:
                        tool_calls.append({
                            "id": part["functionCall"].get("name", ""),
                            "name": part["functionCall"].get("name", ""),
                            "input": part["functionCall"].get("args", {}),
                        })

                return ChatResponse(
                    content=content,
                    tool_calls=tool_calls,
                    usage={
                        "prompt_tokens": data.get("usageMetadata", {}).get("promptTokenCount", 0),
                        "completion_tokens": data.get("usageMetadata", {}).get("candidatesTokenCount", 0),
                        "total_tokens": data.get("usageMetadata", {}).get("totalTokenCount", 0),
                    },
                    model=data.get("model", self._cfg.model),
                )
        except httpx.HTTPStatusError as e:
            logger.error(f"Gemini API error: {e.response.status_code} - {e.response.text}")
            raise

    async def _stream_response(
        self, client: httpx.AsyncClient, model_name: str, payload: dict[str, Any]
    ) -> Any:
        """Handle streaming responses."""
        async with client.stream("POST", f"/chat/{model_name}", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    if line == "data: [DONE]":
                        break
                    yield line[6:]

    async def probe_capabilities(self) -> ModelCapabilities:
        """Probe Gemini capabilities."""
        model_key = self._cfg.model.lower().split("/")[-1]
        limit = DEFAULT_CONTEXT_LIMITS.get(model_key, DEFAULT_CONTEXT_LIMITS["default"])

        # Check for known model families
        if "gemini-2.5" in model_key:
            limit = 1048576
        elif "gemini-2.0" in model_key:
            limit = 1048576
        elif "gemini-1.5" in model_key:
            limit = 2097152 if "pro" in model_key else 1048576

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
        return "gemini"
