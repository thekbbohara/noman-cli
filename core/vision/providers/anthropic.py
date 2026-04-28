"""Anthropic Claude Vision provider.

Uses Anthropic's Claude 3 API for image analysis.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class AnthropicProvider:
    """Anthropic Claude 3 Vision API provider.

    Supports Claude 3, Claude 3.5, and Claude 4 vision models.
    """

    PROVIDER_NAME = "anthropic"
    DEFAULT_MODEL = "claude-3-5-sonnet-20241022"
    SUPPORTED_MODELS = frozenset([
        "claude-3-5-sonnet-20241022",
        "claude-3-5-haiku-20241022",
        "claude-3-opus-20240229",
        "claude-3-haiku-20240307",
    ])

    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        """Initialize Anthropic provider.

        Args:
            api_key: Anthropic API key. Auto-detected from config/env if None.
            base_url: Custom API base URL.
        """
        self._api_key = api_key
        self._base_url = base_url or "https://api.anthropic.com/v1"

    async def analyze(
        self,
        image: dict[str, str],
        task: str,
        prompt: str | None = None,
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Analyze an image using Claude 3 Vision API.

        Args:
            image: Image dict with 'type' (url/base64) and 'data'.
            task: Analysis task type.
            prompt: Custom prompt.
            config: Provider config.
            **kwargs: Additional options.

        Returns:
            Analysis result dict.
        """
        import httpx

        model = config.get("model", self.DEFAULT_MODEL) if config else self.DEFAULT_MODEL
        temperature = config.get("temperature", 0.1) if config else 0.1
        api_key = self._get_api_key()

        # Build image content
        if image.get("type") == "url":
            # For URLs, we'd need to fetch the image first
            # For now, fall back to base64 approach
            async with httpx.AsyncClient(timeout=30.0) as img_client:
                resp = await img_client.get(image["data"])
                resp.raise_for_status()
                b64_data = resp.content
                mime = image.get("mime", "image/png")
        else:
            b64_data = image["data"].encode("utf-8") if isinstance(image["data"], str) else image["data"]
            mime = image.get("mime", "image/png")

        # Claude 3 uses a specific image format
        image_block = {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": mime,
                "data": image["data"] if isinstance(image["data"], str) else "",
            },
        }

        system_prompt = prompt or self._get_default_prompt(task)

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self._base_url}/messages",
                json={
                    "model": model,
                    "max_tokens": kwargs.get("max_tokens", 1000),
                    "temperature": temperature,
                    "system": system_prompt,
                    "messages": [
                        {
                            "role": "user",
                            "content": [image_block],
                        }
                    ],
                },
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        # Parse response
        content_blocks = data.get("content", [])
        text = ""
        for block in content_blocks:
            if block.get("type") == "text":
                text += block.get("text", "")

        return {
            "text": text,
            "confidence": 0.0,
            "objects": [],
            "ocr_text": text if task == "ocr" else "",
            "raw_response": data,
        }

    def _get_default_prompt(self, task: str) -> str:
        """Get default prompt for a task type."""
        prompts = {
            "describe": "Describe this image in detail.",
            "ocr": "Extract all text from this image. Return the exact text.",
            "object_detection": "Detect and list all objects in this image with their positions.",
            "analysis": "Analyze this image thoroughly.",
            "question_answer": "",
        }
        return prompts.get(task, "Describe this image in detail.")

    def _get_api_key(self) -> str:
        """Get API key from instance, config, or environment."""
        if self._api_key:
            return self._api_key
        import os
        return os.environ.get("ANTHROPIC_API_KEY", "")
