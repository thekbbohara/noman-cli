"""Ollama Vision provider.

Uses local Ollama API for vision model inference.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class OllamaProvider:
    """Ollama local vision model provider.

    Uses Ollama's /api/chat endpoint with vision-capable models.
    Supports llava, moondream, and other vision models.
    """

    PROVIDER_NAME = "ollama"
    DEFAULT_MODEL = "llava"
    SUPPORTED_MODELS = frozenset([
        "llava",
        "moondream",
        "llama3.2-vision",
        "llama3.2",
        "llama3.1",
        "phi3.5-vision",
    ])

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        """Initialize Ollama provider.

        Args:
            base_url: Ollama API base URL. Defaults to http://localhost:11434/v1.
            model: Vision model name. Auto-detected from config if None.
        """
        self._base_url = base_url or "http://localhost:11434/v1"
        self._model = model

    async def analyze(
        self,
        image: dict[str, str],
        task: str,
        prompt: str | None = None,
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Analyze an image using Ollama's chat API.

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

        model = self._model or config.get("model", self.DEFAULT_MODEL) if config else self.DEFAULT_MODEL

        # Build the message with image
        if image.get("type") == "url":
            # Download image from URL
            async with httpx.AsyncClient(timeout=30.0) as img_client:
                resp = await img_client.get(image["data"])
                resp.raise_for_status()
                b64_data = resp.content
            mime = image.get("mime", "image/png")
        else:
            b64_data = image["data"].encode("utf-8") if isinstance(image["data"], str) else image["data"]
            mime = image.get("mime", "image/png")

        # Ollama chat format with image
        messages = [
            {
                "role": "user",
                "content": prompt or self._get_default_prompt(task),
                "images": [b64_data],
            }
        ]

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{self._base_url}/chat",
                json={
                    "model": model,
                    "messages": messages,
                    "stream": False,
                    **kwargs.get("extra", {}),
                },
            )
            resp.raise_for_status()
            data = resp.json()

        # Parse Ollama response
        message = data.get("message", {})
        text = message.get("content", "")

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
            "ocr": "Extract all text from this image.",
            "object_detection": "Detect all objects in this image.",
            "analysis": "Analyze this image thoroughly.",
            "question_answer": "",
        }
        return prompts.get(task, "Describe this image in detail.")
