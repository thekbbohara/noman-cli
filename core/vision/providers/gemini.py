"""Google Gemini Vision provider.

Uses Google's Gemini API for image analysis.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class GeminiProvider:
    """Google Gemini Vision API provider.

    Supports Gemini Flash and Gemini Pro Vision models.
    """

    PROVIDER_NAME = "gemini"
    DEFAULT_MODEL = "gemini-2.0-flash"
    SUPPORTED_MODELS = frozenset([
        "gemini-2.0-flash",
        "gemini-1.5-flash",
        "gemini-1.5-pro",
        "gemini-pro-vision",
    ])

    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        """Initialize Gemini provider.

        Args:
            api_key: Gemini API key. Auto-detected from config/env if None.
            base_url: Custom API base URL.
        """
        self._api_key = api_key
        self._base_url = base_url or "https://generativelanguage.googleapis.com/v1beta"

    async def analyze(
        self,
        image: dict[str, str],
        task: str,
        prompt: str | None = None,
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Analyze an image using Google Gemini Vision API.

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
        temperature = config.get("temperature", 0.2) if config else 0.2

        # Build the request body for Gemini API
        content_parts = []

        if image.get("type") == "url":
            content_parts.append({
                "text": prompt or self._get_default_prompt(task),
            })
        else:
            # Base64 image
            mime = image.get("mime", "image/png")
            content_parts.append({
                "inline_data": {
                    "mime_type": mime,
                    "data": image["data"],
                },
            })
            content_parts.append({
                "text": prompt or self._get_default_prompt(task),
            })

        api_key = self._get_api_key()
        url = f"{self._base_url}/models/{model}:generateContent?key={api_key}"

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                url,
                json={
                    "contents": [{"parts": content_parts}],
                    "generationConfig": {
                        "temperature": temperature,
                        "maxOutputTokens": kwargs.get("max_tokens", 1000),
                    },
                },
            )
            resp.raise_for_status()
            data = resp.json()

        # Parse Gemini response
        candidates = data.get("candidates", [])
        if candidates:
            text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            return {
                "text": text,
                "confidence": 0.0,
                "objects": [],
                "ocr_text": text if task == "ocr" else "",
                "raw_response": data,
            }
        return {
            "text": "(no response)",
            "confidence": 0.0,
            "objects": [],
            "ocr_text": "",
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
        return os.environ.get("GEMINI_API_KEY", "")
