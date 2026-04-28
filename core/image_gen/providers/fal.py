"""FAL.ai image generation provider.

Uses FAL.ai's rapid inference API for image generation.
Supports FLUX, Stable Diffusion, and other models.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class FALProvider:
    """FAL.ai image generation provider."""

    PROVIDER_NAME = "fal"
    DEFAULT_MODEL = "fal-ai/fast-sdxl"
    SUPPORTED_MODELS = frozenset([
        "fal-ai/fast-sdxl",
        "fal-ai/fast-flux",
        "fal-ai/flux-dev",
        "fal-ai/flux-schnell",
        "fal-ai/stable-diffusion-v15",
        "fal-ai/stable-diffusion-xl",
    ])

    def __init__(self, api_key: str | None = None) -> None:
        """Initialize FAL provider.

        Args:
            api_key: FAL API key. Auto-detected from config/env if None.
        """
        self._api_key = api_key

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
        """Generate an image using FAL.ai API.

        Args:
            prompt: Image generation prompt.
            negative_prompt: What to exclude.
            width: Image width.
            height: Image height.
            model: Model to use.
            config: Provider config.
            **kwargs: Additional options (scheduler, steps, guidance_scale, etc.).

        Returns:
            Dict with image_url and metadata.
        """
        import httpx

        api_key = self._get_api_key()
        model_name = model or config.get("model", self.DEFAULT_MODEL) if config else self.DEFAULT_MODEL
        steps = config.get("steps", kwargs.get("steps", 25)) if config else kwargs.get("steps", 25)
        guidance_scale = config.get("guidance_scale", kwargs.get("guidance_scale", 8.0)) if config else kwargs.get("guidance_scale", 8.0)
        seed = kwargs.get("seed")

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"https://fal.run/{model_name}",
                json={
                    "prompt": prompt,
                    "negative_prompt": negative_prompt,
                    "image_size": {"width": width, "height": height},
                    "num_steps": steps,
                    "guidance_scale": guidance_scale,
                    "seed": seed,
                },
                headers={
                    "Authorization": f"Key {api_key}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        # FAL returns images in various formats depending on model
        image_url = None
        if isinstance(data, dict):
            # Check for images in various locations
            for key in ("images", "image", "output", "files"):
                if key in data:
                    val = data[key]
                    if isinstance(val, list) and val:
                        if isinstance(val[0], dict):
                            image_url = val[0].get("url") or val[0].get("file_url")
                        elif isinstance(val[0], str):
                            image_url = val[0]
                    elif isinstance(val, dict):
                        image_url = val.get("url") or val.get("file_url")
                    elif isinstance(val, str):
                        image_url = val
                    if image_url:
                        break

        return {
            "image_url": image_url,
            "image_path": None,
            "raw_response": data,
            "seed": seed,
            "nsfw_score": 0.0,
        }

    def _get_api_key(self) -> str:
        """Get API key from instance, config, or environment."""
        if self._api_key:
            return self._api_key
        import os
        return os.environ.get("FAL_KEY", "")
