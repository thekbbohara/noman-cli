"""Image generation providers for noman-cli.

Multi-provider image generation with support for:
    - FAL.ai (fast, various models)
    - OpenAI DALL-E 3
    - Stability AI (SDXL)
    - Replicate (various models)
"""

from __future__ import annotations

from core.image_gen.providers.fal import FALProvider
from core.image_gen.providers.openai import OpenAIProvider
from core.image_gen.providers.replicate import ReplicateProvider
from core.image_gen.providers.stability import StabilityProvider

__all__ = [
    "FALProvider",
    "OpenAIProvider",
    "ReplicateProvider",
    "StabilityProvider",
]
