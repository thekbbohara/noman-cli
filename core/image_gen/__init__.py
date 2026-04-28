"""Image generation module for noman-cli.

Image generation with multi-provider support.

Providers:
    - fal: FAL.ai (fast, various models)
    - openai: OpenAI DALL-E 3
    - stability: Stability AI (SDXL, etc.)
    - replicate: Replicate (various models)

Configuration (in ~/.noman/config.toml):
    [image_gen]
    default_provider = "fal"
    default_aspect = "square"  # landscape, square, portrait
    enhance_prompts = true

    [image_gen.providers.fal]
    api_key = "fal-..."

    [image_gen.providers.openai]
    api_key = "sk-..."

    [image_gen.providers.stability]
    api_key = "sk-..."

    [image_gen.providers.replicate]
    api_key = "rp-..."
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class AspectRatio(str, Enum):
    """Standard aspect ratios for image generation."""
    LANDSCAPE = "landscape"    # 16:9
    SQUARE = "square"          # 1:1
    PORTRAIT = "portrait"      # 9:16


@dataclass
class ImageGenerationResult:
    """Result from image generation."""
    image_url: str | None
    image_path: str | None
    provider: str
    prompt: str
    aspect_ratio: str
    model: str
    seed: int | None = None
    width: int = 1024
    height: int = 1024
    raw_response: dict[str, Any] | None = None
    nsfw_score: float = 0.0

    def __str__(self) -> str:
        path = self.image_path or self.image_url or "N/A"
        return f"ImageResult(provider={self.provider}, image={path}, prompt='{self.prompt[:50]}...')"


class ImageGenerator:
    """Multi-provider image generation engine.

    Supports FAL.ai, OpenAI DALL-E, Stability AI, and Replicate.
    Handles aspect ratio selection, prompt enhancement, and rate limiting.
    """

    VALID_PROVIDERS = frozenset(["fal", "openai", "stability", "replicate"])
    VALID_ASPECTS = frozenset(["landscape", "square", "portrait"])

    # Default dimensions per aspect ratio
    ASPECT_SIZES = {
        "landscape": (1280, 720),
        "square": (1024, 1024),
        "portrait": (720, 1280),
    }

    def __init__(
        self,
        default_provider: str | None = None,
        default_aspect: str = "square",
        config: dict[str, Any] | None = None,
        output_dir: str | Path | None = None,
        enhance_prompts: bool = True,
        max_retries: int = 3,
    ) -> None:
        """Initialize ImageGenerator.

        Args:
            default_provider: Default generation provider. Auto-detected from config if None.
            default_aspect: Default aspect ratio (landscape, square, portrait).
            config: Configuration dict (from config.toml [image_gen] section).
            output_dir: Directory for saved images.
            enhance_prompts: Whether to enhance user prompts before generation.
            max_retries: Maximum retry attempts for failed generations.
        """
        self._config = config or {}
        self._default_provider = default_provider or self._detect_provider()
        self._default_aspect = default_aspect
        self._output_dir = Path(output_dir) if output_dir else Path.home() / ".noman" / "images"
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._enhance_prompts = config.get("enhance_prompts", enhance_prompts)
        self._max_retries = max_retries
        self._providers: dict[str, Any] = {}

    def _detect_provider(self) -> str:
        """Auto-detect default provider from config or environment."""
        provider = self._config.get("default_provider", "fal")
        if provider not in self.VALID_PROVIDERS:
            logger.warning(f"Unknown image_gen provider '{provider}', defaulting to fal")
            provider = "fal"
        return provider

    @property
    def provider(self) -> str:
        """Current default provider."""
        return self._default_provider

    @property
    def default_aspect(self) -> str:
        """Default aspect ratio."""
        return self._default_aspect

    def _get_api_key(self, provider: str) -> str:
        """Get API key for a provider."""
        section = self._config.get("providers", {}).get(provider, {})
        if not section:
            section = self._config.get(provider, {})
        key = section.get("api_key", "")
        if not key:
            env_map = {
                "fal": "FAL_KEY",
                "openai": "OPENAI_API_KEY",
                "stability": "STABILITY_API_KEY",
                "replicate": "REPLICATE_API_KEY",
            }
            env_key = env_map.get(provider, "")
            if env_key:
                key = os.environ.get(env_key, "")
        return key

    def _get_provider_instance(self, provider: str) -> Any:
        """Lazy-load a provider instance."""
        if provider not in self._providers:
            if provider == "fal":
                from core.image_gen.providers.fal import FALProvider
                self._providers[provider] = FALProvider()
            elif provider == "openai":
                from core.image_gen.providers.openai import OpenAIProvider
                self._providers[provider] = OpenAIProvider()
            elif provider == "stability":
                from core.image_gen.providers.stability import StabilityProvider
                self._providers[provider] = StabilityProvider()
            elif provider == "replicate":
                from core.image_gen.providers.replicate import ReplicateProvider
                self._providers[provider] = ReplicateProvider()
            else:
                raise ValueError(f"Unknown image generation provider: {provider}")
        return self._providers[provider]

    async def generate(
        self,
        prompt: str,
        provider: str | None = None,
        aspect: str = "square",
        model: str | None = None,
        negative_prompt: str | None = None,
        output_filename: str | None = None,
        **kwargs: Any,
    ) -> ImageGenerationResult:
        """Generate an image from a text prompt.

        Args:
            prompt: Text prompt describing the desired image.
            provider: Override provider for this call.
            aspect: Aspect ratio (landscape, square, portrait).
            model: Override model for this call.
            negative_prompt: What to exclude from the image.
            output_filename: Optional output filename (without extension).
            **kwargs: Additional provider-specific options.

        Returns:
            ImageGenerationResult with image URL and/or file path.

        Raises:
            ValueError: If prompt is empty or aspect ratio is invalid.
            RuntimeError: If generation fails after retries.
        """
        if not prompt or not prompt.strip():
            raise ValueError("Prompt cannot be empty")

        aspect = aspect.lower()
        if aspect not in self.VALID_ASPECTS:
            raise ValueError(f"Invalid aspect ratio: {aspect}. Valid: {', '.join(sorted(self.VALID_ASPECTS))}")

        active_provider = provider or self._default_provider
        provider_inst = self._get_provider_instance(active_provider)

        # Get dimensions for aspect ratio
        width, height = self.ASPECT_SIZES.get(aspect, self.ASPECT_SIZES["square"])

        # Enhance prompt if enabled
        enhanced_prompt = prompt
        if self._enhance_prompts:
            enhanced_prompt = await self._enhance_prompt(prompt)

        # Retry logic
        last_error = None
        for attempt in range(self._max_retries):
            try:
                result = await provider_inst.generate(
                    prompt=enhanced_prompt,
                    negative_prompt=negative_prompt,
                    width=width,
                    height=height,
                    model=model,
                    config=self._config.get("providers", {}).get(active_provider, {})
                    or self._config.get(active_provider, {}),
                    **kwargs,
                )

                # Save the image
                output_path = None
                if result.get("image_url"):
                    output_path = await self._save_image(result["image_url"], output_filename)
                elif result.get("image_path"):
                    output_path = result["image_path"]

                return ImageGenerationResult(
                    image_url=result.get("image_url"),
                    image_path=output_path,
                    provider=active_provider,
                    prompt=prompt,
                    aspect_ratio=aspect,
                    model=model or provider_inst.DEFAULT_MODEL,
                    seed=result.get("seed"),
                    width=width,
                    height=height,
                    raw_response=result.get("raw_response"),
                    nsfw_score=result.get("nsfw_score", 0.0),
                )
            except Exception as e:
                last_error = e
                logger.warning(f"Image generation attempt {attempt + 1}/{self._max_retries} failed: {e}")
                if attempt < self._max_retries - 1:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff

        raise RuntimeError(f"Image generation failed after {self._max_retries} attempts: {last_error}")

    async def generate_multiple(
        self,
        prompt: str,
        count: int = 4,
        provider: str | None = None,
        aspect: str = "square",
        **kwargs: Any,
    ) -> list[ImageGenerationResult]:
        """Generate multiple images from a single prompt.

        Args:
            prompt: Text prompt.
            count: Number of images to generate.
            provider: Override provider.
            aspect: Aspect ratio.
            **kwargs: Additional options.

        Returns:
            List of ImageGenerationResult.
        """
        results = []
        for i in range(count):
            result = await self.generate(
                prompt, provider=provider, aspect=aspect,
                output_filename=f"{self._sanitize_filename(prompt)}_{i+1}", **kwargs
            )
            results.append(result)
        return results

    async def _enhance_prompt(self, prompt: str) -> str:
        """Enhance a prompt for better image generation.

        Adds artistic style descriptors and quality keywords.
        In production, this could call an LLM for intelligent enhancement.
        """
        enhancements = [
            "high quality, detailed, professional",
            "masterpiece, best quality",
            "sharp focus, vivid colors",
        ]

        # Check if prompt already has enhancement keywords
        lower = prompt.lower()
        if any(kw in lower for kw in ["masterpiece", "best quality", "high quality"]):
            return prompt

        return f"{prompt}, {', '.join(enhancements)}"

    async def _save_image(self, image_url: str, filename: str | None = None) -> str | None:
        """Download and save an image from URL.

        Args:
            image_url: URL to the generated image.
            filename: Optional base filename.

        Returns:
            Local file path or None if download failed.
        """
        import httpx

        if not image_url:
            return None

        if filename:
            safe_name = self._sanitize_filename(filename)
        else:
            safe_name = f"image_{int(asyncio.get_event_loop().time() * 1000)}"

        output_path = self._output_dir / f"{safe_name}.png"

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.get(image_url)
                resp.raise_for_status()
                output_path.write_bytes(resp.content)
                logger.info(f"Image saved to {output_path}")
                return str(output_path)
        except Exception as e:
            logger.error(f"Failed to save image: {e}")
            return None

    def _sanitize_filename(self, name: str) -> str:
        """Sanitize a string for use as a filename."""
        import re
        # Remove invalid characters
        sanitized = re.sub(r'[^\w\s-]', '', name)
        # Replace spaces with underscores
        sanitized = sanitized.replace(' ', '_')
        # Truncate
        return sanitized[:60]

    async def list_providers(self) -> list[dict[str, Any]]:
        """List all available image generation providers."""
        providers = []
        for p in self.VALID_PROVIDERS:
            api_key = self._get_api_key(p)
            has_key = bool(api_key and len(api_key) > 5)
            providers.append({
                "name": p,
                "enabled": p == self._default_provider,
                "api_key_configured": has_key,
                "free": p in ("fal",),  # FAL has free tier
                "description": {
                    "fal": "FAL.ai (fast, various models, free tier)",
                    "openai": "OpenAI DALL-E 3 (paid)",
                    "stability": "Stability AI SDXL (paid)",
                    "replicate": "Replicate (various models, pay-per-use)",
                }.get(p, "Unknown provider"),
            })
        return providers
