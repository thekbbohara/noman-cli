"""Replicate image generation provider.

Uses Replicate's API for various image generation models.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ReplicateProvider:
    """Replicate image generation provider."""

    PROVIDER_NAME = "replicate"
    DEFAULT_MODEL = "stability-ai/sdxl"
    SUPPORTED_MODELS = frozenset([
        "stability-ai/sdxl",
        "stability-ai/sdxl-vacuum",
        "lucataco/realism-sfli",
        "cjwbw/controlnet",
        "black-forest-labs/flux-schnell",
        "black-forest-labs/flux-dev",
    ])

    def __init__(self, api_key: str | None = None) -> None:
        """Initialize Replicate provider.

        Args:
            api_key: Replicate API token. Auto-detected from config/env if None.
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
        """Generate an image using Replicate API.

        Uses Replicate's prediction API for async model execution.

        Args:
            prompt: Image generation prompt.
            negative_prompt: What to exclude.
            width: Image width.
            height: Image height.
            model: Model to use (version format: owner/model:version).
            config: Provider config.
            **kwargs: Additional options (steps, guidance, num_outputs, seed).

        Returns:
            Dict with image_url and metadata.
        """
        import httpx
        import time

        api_key = self._get_api_key()
        model_version = model or config.get("model", self.DEFAULT_MODEL) if config else self.DEFAULT_MODEL
        steps = config.get("steps", kwargs.get("steps", 50)) if config else kwargs.get("steps", 50)
        guidance = config.get("guidance", kwargs.get("guidance", 7.5)) if config else kwargs.get("guidance", 7.5)
        num_outputs = config.get("num_outputs", kwargs.get("num_outputs", 1)) if config else kwargs.get("num_outputs", 1)
        seed = config.get("seed", kwargs.get("seed", int(time.time()))) if config else kwargs.get("seed", int(time.time()))

        # Build input based on model
        input_data = {
            "prompt": prompt,
            "width": width,
            "height": height,
            "num_outputs": num_outputs,
            "guidance_scale": guidance,
            "num_inference_steps": steps,
        }
        if negative_prompt:
            input_data["negative_prompt"] = negative_prompt

        async with httpx.AsyncClient(timeout=120.0) as client:
            # Create prediction
            resp = await client.post(
                "https://api.replicate.com/v1/predictions",
                json={
                    "version": model_version,
                    "input": input_data,
                },
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "Prefer": "wait",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        # Poll for completion if not done
        image_url = None
        status = data.get("status", "")
        if status == "succeeded":
            output = data.get("output", [])
            if output and isinstance(output, list):
                image_url = output[0] if isinstance(output[0], str) else output[0].get("url")
        elif status == "starting" or status == "processing":
            # Poll for completion
            max_wait = kwargs.get("max_poll_wait", 300)
            poll_interval = kwargs.get("poll_interval", 2)
            poll_start = time.time()

            while status in ("starting", "processing") and (time.time() - poll_start) < max_wait:
                await asyncio.sleep(poll_interval)
                resp = await client.get(f"https://api.replicate.com/v1/predictions/{data['id']}")
                resp.raise_for_status()
                data = resp.json()
                status = data.get("status", "")

            if status == "succeeded":
                output = data.get("output", [])
                if output and isinstance(output, list):
                    image_url = output[0] if isinstance(output[0], str) else output[0].get("url")

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
        return os.environ.get("REPLICATE_API_KEY", "")


import asyncio  # noqa: E402
