"""OpenAI DALL-E image generation provider.

Uses OpenAI's DALL-E 3 API for image generation.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class OpenAIProvider:
    """OpenAI DALL-E image generation provider."""

    PROVIDER_NAME = "openai"
    DEFAULT_MODEL = "dall-e-3"
    SUPPORTED_MODELS = frozenset(["dall-e-3", "dall-e-2"])

    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        """Initialize OpenAI provider.

        Args:
            api_key: OpenAI API key. Auto-detected from config/env if None.
            base_url: Custom API base URL.
        """
        self._api_key = api_key
        self._base_url = base_url or "https://api.openai.com/v1"

    async def generate(
        self,
        prompt: str,
        negative_prompt: str | None = None,
        width: int = 1024,
        height: int = 1024,
        model: str | None = None,
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate an image using DALL-E 3 API.

        Args:
            prompt: Image generation prompt.
            negative_prompt: Not supported by DALL-E (ignored).
            width: Image width (DALL-E 3 only supports specific sizes).
            height: Image height.
            model: Model to use (dall-e-3 or dall-e-2).
            config: Provider config.
            **kwargs: Additional options (quality, style, response_format).

        Returns:
            Dict with image_url and metadata.
        """
        import httpx

        api_key = self._get_api_key()
        model_name = model or config.get("model", self.DEFAULT_MODEL) if config else self.DEFAULT_MODEL

        # DALL-E size mappings
        size_map = {
            "dall-e-3": {
                (1024, 1024): "1024x1024",
                (1024, 1792): "1024x1792",
                (1792, 1024): "1792x1024",
            },
            "dall-e-2": {
                (1024, 1024): "1024x1024",
                (512, 512): "512x512",
                (256, 256): "256x256",
            },
        }

        size_key = (width, height)
        size = size_map.get(model_name, {}).get(size_key, "1024x1024")

        quality = config.get("quality", "hd") if config else kwargs.get("quality", "hd")
        style = config.get("style", "natural") if config else kwargs.get("style", "natural")
        response_format = config.get("response_format", "url") if config else kwargs.get("response_format", "url")

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self._base_url}/images/generations",
                json={
                    "model": model_name,
                    "prompt": prompt,
                    "n": kwargs.get("n", 1),
                    "size": size,
                    "quality": quality,
                    "style": style,
                    "response_format": response_format,
                },
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        # Parse response
        images = data.get("data", [])
        image_url = None
        if images:
            img = images[0]
            if response_format == "b64_json":
                import base64
                image_url = f"data:image/png;base64,{img.get('b64_json', '')}"
            else:
                image_url = img.get("url")

        return {
            "image_url": image_url,
            "image_path": None,
            "raw_response": data,
            "nsfw_score": 0.0,
        }

    def _get_api_key(self) -> str:
        """Get API key from instance, config, or environment."""
        if self._api_key:
            return self._api_key
        import os
        return os.environ.get("OPENAI_API_KEY", "")
