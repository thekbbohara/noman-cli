"""OpenAI Vision provider (GPT-4V).

Uses OpenAI's GPT-4 Vision API for image analysis.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class OpenAIProvider:
    """OpenAI Vision API provider (GPT-4V, GPT-4o, GPT-4o-mini)."""

    PROVIDER_NAME = "openai"
    DEFAULT_MODEL = "gpt-4o"
    SUPPORTED_MODELS = frozenset(["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"])

    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        """Initialize OpenAI provider.

        Args:
            api_key: OpenAI API key. Auto-detected from config/env if None.
            base_url: Custom API base URL (for proxies).
        """
        self._api_key = api_key
        self._base_url = base_url or "https://api.openai.com/v1"

    async def analyze(
        self,
        image: dict[str, str],
        task: str,
        prompt: str | None = None,
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Analyze an image using OpenAI Vision API.

        Args:
            image: Image dict with 'type' (url/base64) and 'data' (url string or base64).
            task: Analysis task type.
            prompt: Custom prompt for analysis.
            config: Provider config dict.
            **kwargs: Additional options.

        Returns:
            Analysis result dict.
        """
        import httpx

        model = config.get("model", self.DEFAULT_MODEL) if config else self.DEFAULT_MODEL
        temperature = config.get("temperature", 0.1) if config else 0.1

        # Build content
        content = self._build_content(image, prompt, task)

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self._base_url}/chat/completions",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": content}],
                    "max_tokens": kwargs.get("max_tokens", 1000),
                    "temperature": temperature,
                },
                headers={
                    "Authorization": f"Bearer {self._get_api_key()}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        text = data["choices"][0]["message"]["content"]
        return {
            "text": text,
            "confidence": 0.0,  # OpenAI doesn't return confidence
            "objects": [],
            "ocr_text": "",
            "raw_response": data,
        }

    def _build_content(
        self, image: dict[str, str], prompt: str | None, task: str
    ) -> list[dict[str, Any]]:
        """Build the content array for the OpenAI API request."""
        content = []

        if image.get("type") == "url":
            content.append({
                "type": "text",
                "text": prompt or self._get_default_prompt(task),
            })
            content.append({
                "type": "image_url",
                "image_url": {"url": image["data"]},
            })
        else:
            # Base64
            mime = image.get("mime", "image/png")
            content.append({
                "type": "text",
                "text": prompt or self._get_default_prompt(task),
            })
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mime};base64,{image['data']}",
                    "detail": "high",
                },
            })

        return content

    def _get_default_prompt(self, task: str) -> str:
        """Get default prompt for a task type."""
        prompts = {
            "describe": "Describe this image in detail. What do you see?",
            "ocr": "Extract all text from this image. Return the exact text content.",
            "object_detection": "Detect and list all objects in this image. Include their positions and descriptions.",
            "analysis": "Analyze this image thoroughly. Describe the content, style, and any notable elements.",
            "question_answer": "",
        }
        return prompts.get(task, "Describe this image in detail.")

    def _get_api_key(self) -> str:
        """Get API key from instance, config, or environment."""
        if self._api_key:
            return self._api_key
        import os
        return os.environ.get("OPENAI_API_KEY", "")
