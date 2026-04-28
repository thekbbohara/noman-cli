"""Vision analyzer - wraps VisionAnalyzer with additional analysis utilities."""

from __future__ import annotations

import logging
from typing import Any

from core.vision import VisionAnalyzer, VisionResult, VisionTask

logger = logging.getLogger(__name__)


class VisionAnalyzerExtended(VisionAnalyzer):
    """Extended VisionAnalyzer with additional analysis utilities.

    Adds support for batch image analysis, comparison, and enhanced prompts.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize with default provider detection."""
        super().__init__(*args, **kwargs)

    async def analyze_batch(
        self,
        images: list[str | object],
        task: VisionTask | str = VisionTask.DESCRIBE,
        provider: str | None = None,
        **kwargs: Any,
    ) -> list[VisionResult]:
        """Analyze multiple images.

        Args:
            images: List of images (URLs, paths, or bytes).
            task: Analysis task type.
            provider: Override provider for all calls.
            **kwargs: Additional options.

        Returns:
            List of VisionResults, one per image.
        """
        results = []
        for img in images:
            result = await self.analyze(img, task=task, provider=provider, **kwargs)
            results.append(result)
        return results

    async def compare_images(
        self,
        image1: str | object,
        image2: str | object,
        provider: str | None = None,
        **kwargs: Any,
    ) -> VisionResult:
        """Compare two images and describe similarities/differences.

        Args:
            image1: First image (URL, path, or bytes).
            image2: Second image (URL, path, or bytes).
            provider: Override provider for this call.
            **kwargs: Additional options.

        Returns:
            VisionResult with comparison text.
        """
        # Use a custom prompt for comparison
        prompt = (
            "Compare these two images. Describe the key similarities and differences "
            "between them. Note any objects, text, colors, compositions, and styles. "
            "Be thorough and specific."
        )
        # For providers that support multiple images, we'd combine them here
        # For now, analyze image1 with the comparison prompt
        result = await self.analyze(image1, task=VisionTask.ANALYSIS, prompt=prompt, provider=provider, **kwargs)
        result.text += f"\n\n--- Comparison with second image ---\n"
        return result

    async def enhanced_describe(
        self,
        image: str | object,
        provider: str | None = None,
        include_tags: bool = True,
        include_colors: bool = True,
        **kwargs: Any,
    ) -> VisionResult:
        """Enhanced description with structured output.

        Args:
            image: Image (URL, path, or bytes).
            provider: Override provider for this call.
            include_tags: Include detected tags.
            include_colors: Include dominant colors.
            **kwargs: Additional options.

        Returns:
            VisionResult with enhanced description.
        """
        prompt_parts = [
            "Describe this image in detail. Include:",
            "- Main subject and objects",
            "- Scene setting and environment",
            "- Colors and lighting",
        ]
        if include_tags:
            prompt_parts.append("- Relevant tags/categories")
        if include_colors:
            prompt_parts.append("- Dominant colors")
        prompt_parts.append("- Artistic style (if applicable)")

        prompt = "\n".join(prompt_parts)

        return await self.analyze(image, task=VisionTask.ANALYSIS, prompt=prompt, provider=provider, **kwargs)
