"""Stability AI image generation provider.

Uses Stability AI's API for Stable Diffusion models.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class StabilityProvider:
    """Stability AI image generation provider."""

    PROVIDER_NAME = "stability"
    DEFAULT_MODEL = "stable-diffusion-xl-1024-v1-0"
    SUPPORTED_MODELS = frozenset([
        "stable-diffusion-xl-1024-v1-0",
        "stable-diffusion-512-v2-1",
        "stable-diffusion-v1-6",
        "sdxl",
    ])

    def __init__(self, api_key: str | None = None) -> None:
        """Initialize Stability AI provider.

        Args:
            api_key: Stability API key. Auto-detected from config/env if None.
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
        """Generate an image using Stability AI API.

        Args:
            prompt: Image generation prompt.
            negative_prompt: What to exclude.
            width: Image width.
            height: Image height.
            model: Model to use.
            config: Provider config.
            **kwargs: Additional options (steps, cfg_scale, seed, sampler).

        Returns:
            Dict with image_path (base64) and metadata.
        """
        import httpx

        api_key = self._get_api_key()
        model_name = model or config.get("model", self.DEFAULT_MODEL) if config else self.DEFAULT_MODEL
        steps = config.get("steps", kwargs.get("steps", 30)) if config else kwargs.get("steps", 30)
        cfg_scale = config.get("cfg_scale", kwargs.get("cfg_scale", 7.0)) if config else kwargs.get("cfg_scale", 7.0)
        seed = config.get("seed", kwargs.get("seed", 42)) if config else kwargs.get("seed", 42)

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"https://api.stability.ai/v1/generation/{model_name}/text-to-image",
                json={
                    "text_prompts": [
                        {"text": prompt, "weight": 1},
                    ] + ([{"text": negative_prompt, "weight": -1}] if negative_prompt else []),
                    "cfg_scale": cfg_scale,
                    "width": width,
                    "height": height,
                    "steps": steps,
                    "seed": seed,
                    "samples": kwargs.get("samples", 1),
                },
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "Accept": "image/png",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        # Parse response (Stability API returns images as base64)
        images = data.get("artifacts", [])
        image_path = None
        nsfw_score = 0.0

        if images:
            first = images[0]
            if first.get("base64"):
                image_path = first["base64"]

        return {
            "image_url": None,
            "image_path": image_path,
            "raw_response": data,
            "seed": seed,
            "nsfw_score": nsfw_score,
        }

    def _get_api_key(self) -> str:
        """Get API key from instance, config, or environment."""
        if self._api_key:
            return self._api_key
        import os
        return os.environ.get("STABILITY_API_KEY", "")
