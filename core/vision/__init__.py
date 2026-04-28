"""Vision module for noman-cli.

Image analysis, OCR, and object detection with multi-provider support.

Providers:
    - openai: GPT-4 Vision (GPT-4V)
    - gemini: Google Gemini Vision (Gemini Flash/Vision)
    - anthropic: Anthropic Claude Vision (Claude 3)
    - ollama: Ollama vision models (local)

Configuration (in ~/.noman/config.toml):
    [vision]
    default_provider = "openai"

    [vision.providers.openai]
    api_key = "sk-..."
    model = "gpt-4o"

    [vision.providers.gemini]
    api_key = "ai-..."
    model = "gemini-2.0-flash"

    [vision.providers.anthropic]
    api_key = "sk-ant-..."
    model = "claude-3-5-sonnet-20241022"

    [vision.providers.ollama]
    base_url = "http://localhost:11434/v1"
    model = "llava"
"""

from __future__ import annotations

import base64
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class VisionTask(str, Enum):
    """Vision analysis task types."""
    DESCRIBE = "describe"
    OCR = "ocr"
    OBJECT_DETECTION = "object_detection"
    ANALYSIS = "analysis"
    QUESTION_ANSWER = "question_answer"


@dataclass
class VisionResult:
    """Structured result from vision analysis."""
    provider: str
    task: str
    text: str
    confidence: float = 0.0
    objects: list[dict[str, Any]] = field(default_factory=list)
    ocr_text: str = ""
    raw_response: dict[str, Any] | None = None
    image_hash: str = ""

    def __str__(self) -> str:
        preview = self.text[:200] + ("..." if len(self.text) > 200 else "")
        return f"VisionResult(provider={self.provider}, task={self.task}, text='{preview}')"


class VisionAnalyzer:
    """Multi-provider vision analysis engine.

    Accepts image URLs or base64-encoded images and runs analysis through
    configured providers (OpenAI GPT-4V, Gemini, Claude, Ollama).
    Supports describe, OCR, object detection, and custom analysis tasks.
    """

    VALID_PROVIDERS = frozenset(["openai", "gemini", "anthropic", "ollama"])

    def __init__(
        self,
        default_provider: str | None = None,
        config: dict[str, Any] | None = None,
        cache_dir: str | Path | None = None,
    ) -> None:
        """Initialize VisionAnalyzer.

        Args:
            default_provider: Default vision provider. Auto-detected from config if None.
            config: Configuration dict (from config.toml [vision] section).
            cache_dir: Directory for cached analysis results.
        """
        self._config = config or {}
        self._cache_dir = Path(cache_dir) if cache_dir else Path.home() / ".noman" / "vision_cache"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._default_provider = default_provider or self._detect_provider()
        self._providers: dict[str, Any] = {}

    def _detect_provider(self) -> str:
        """Auto-detect default provider from config or environment."""
        provider = self._config.get("default_provider", "openai")
        if provider not in self.VALID_PROVIDERS:
            logger.warning(f"Unknown vision provider '{provider}', defaulting to openai")
            provider = "openai"
        return provider

    @property
    def provider(self) -> str:
        """Current default provider."""
        return self._default_provider

    def _get_api_key(self, provider: str) -> str:
        """Get API key for a provider."""
        section = self._config.get(provider, {})
        key = section.get("api_key", "")
        if not key:
            env_map = {
                "openai": "OPENAI_API_KEY",
                "gemini": "GEMINI_API_KEY",
                "anthropic": "ANTHROPIC_API_KEY",
            }
            env_key = env_map.get(provider, "")
            if env_key:
                key = os.environ.get(env_key, "")
        return key

    def _get_provider_instance(self, provider: str) -> Any:
        """Lazy-load a provider instance."""
        if provider not in self._providers:
            if provider == "openai":
                from core.vision.providers.openai import OpenAIProvider
                self._providers[provider] = OpenAIProvider()
            elif provider == "gemini":
                from core.vision.providers.gemini import GeminiProvider
                self._providers[provider] = GeminiProvider()
            elif provider == "anthropic":
                from core.vision.providers.anthropic import AnthropicProvider
                self._providers[provider] = AnthropicProvider()
            elif provider == "ollama":
                from core.vision.providers.ollama import OllamaProvider
                self._providers[provider] = OllamaProvider()
            else:
                raise ValueError(f"Unknown vision provider: {provider}")
        return self._providers[provider]

    async def analyze(
        self,
        image: str | Path | bytes,
        task: VisionTask | str = VisionTask.DESCRIBE,
        prompt: str | None = None,
        provider: str | None = None,
        **kwargs: Any,
    ) -> VisionResult:
        """Analyze an image with the configured vision provider.

        Args:
            image: Image as URL string, file path, or base64 bytes.
            task: Analysis task type (describe, ocr, object_detection, analysis).
            prompt: Optional custom prompt for analysis.
            provider: Override provider for this call.
            **kwargs: Additional provider-specific options.

        Returns:
            VisionResult with analysis text and metadata.
        """
        active_provider = provider or self._default_provider
        provider_inst = self._get_provider_instance(active_provider)

        # Prepare image data
        image_data = self._prepare_image(image)
        image_hash = self._get_image_hash(image_data)

        # Check cache
        cached = self._get_cached_result(image_hash, active_provider, str(task))
        if cached:
            logger.debug(f"Vision: using cached result for image hash {image_hash[:8]}...")
            return cached

        # Run analysis
        result = await provider_inst.analyze(
            image=image_data,
            task=task,
            prompt=prompt,
            config=self._config.get(active_provider, {}),
            **kwargs,
        )
        result.provider = active_provider
        result.task = str(task)
        result.image_hash = image_hash

        # Cache result
        self._cache_result(image_hash, active_provider, str(task), result)

        return result

    async def describe(
        self,
        image: str | Path | bytes,
        provider: str | None = None,
        **kwargs: Any,
    ) -> VisionResult:
        """Describe an image in detail.

        Args:
            image: Image as URL, file path, or bytes.
            provider: Override provider for this call.
            **kwargs: Additional options.

        Returns:
            VisionResult with description text.
        """
        return await self.analyze(image, task=VisionTask.DESCRIBE, provider=provider, **kwargs)

    async def ocr(
        self,
        image: str | Path | bytes,
        provider: str | None = None,
        **kwargs: Any,
    ) -> VisionResult:
        """Perform OCR on an image to extract text.

        Args:
            image: Image as URL, file path, or bytes.
            provider: Override provider for this call.
            **kwargs: Additional options.

        Returns:
            VisionResult with extracted text.
        """
        return await self.analyze(image, task=VisionTask.OCR, provider=provider, **kwargs)

    async def detect_objects(
        self,
        image: str | Path | bytes,
        provider: str | None = None,
        **kwargs: Any,
    ) -> VisionResult:
        """Detect objects in an image.

        Args:
            image: Image as URL, file path, or bytes.
            provider: Override provider for this call.
            **kwargs: Additional options.

        Returns:
            VisionResult with object detection results.
        """
        return await self.analyze(image, task=VisionTask.OBJECT_DETECTION, provider=provider, **kwargs)

    async def ask(
        self,
        image: str | Path | bytes,
        question: str,
        provider: str | None = None,
        **kwargs: Any,
    ) -> VisionResult:
        """Ask a question about an image.

        Args:
            image: Image as URL, file path, or bytes.
            question: Question to ask about the image.
            provider: Override provider for this call.
            **kwargs: Additional options.

        Returns:
            VisionResult with the answer.
        """
        return await self.analyze(
            image, task=VisionTask.QUESTION_ANSWER, prompt=question, provider=provider, **kwargs
        )

    def _prepare_image(self, image: str | Path | bytes) -> dict[str, str]:
        """Prepare image data for vision API. Returns dict with url or base64 data."""
        if isinstance(image, bytes):
            b64 = base64.b64encode(image).decode("utf-8")
            return {"type": "base64", "data": b64, "mime": "image/png"}
        elif isinstance(image, Path):
            if image.exists():
                data = image.read_bytes()
                b64 = base64.b64encode(data).decode("utf-8")
                mime = f"image/{image.suffix.lstrip('.')}"
                return {"type": "base64", "data": b64, "mime": mime}
            raise FileNotFoundError(f"Image file not found: {image}")
        elif isinstance(image, str):
            # Try as URL first
            if image.startswith(("http://", "https://")):
                return {"type": "url", "data": image}
            # Try as file path
            path = Path(image)
            if path.exists():
                data = path.read_bytes()
                b64 = base64.b64encode(data).decode("utf-8")
                mime = f"image/{path.suffix.lstrip('.')}"
                return {"type": "base64", "data": b64, "mime": mime}
            raise FileNotFoundError(f"Image not found (URL or path): {image}")
        raise ValueError(f"Unsupported image type: {type(image)}")

    def _get_image_hash(self, image_data: dict[str, str]) -> str:
        """Get hash of image data for caching."""
        import hashlib
        content = image_data["data"]
        return hashlib.sha256(content.encode() if isinstance(content, str) else content).hexdigest()[:16]

    def _get_cached_result(
        self, image_hash: str, provider: str, task: str
    ) -> VisionResult | None:
        """Check if result is cached."""
        cache_file = self._cache_dir / f"{image_hash}_{provider}_{task}.json"
        if cache_file.exists():
            import json
            data = json.loads(cache_file.read_text())
            return VisionResult(
                provider=data["provider"],
                task=data["task"],
                text=data["text"],
                confidence=data.get("confidence", 0.0),
                objects=data.get("objects", []),
                ocr_text=data.get("ocr_text", ""),
                raw_response=data.get("raw_response"),
                image_hash=data.get("image_hash", ""),
            )
        return None

    def _cache_result(self, image_hash: str, provider: str, task: str, result: VisionResult) -> None:
        """Cache analysis result."""
        import json
        cache_file = self._cache_dir / f"{image_hash}_{provider}_{task}.json"
        cache_data = {
            "provider": result.provider,
            "task": result.task,
            "text": result.text,
            "confidence": result.confidence,
            "objects": result.objects,
            "ocr_text": result.ocr_text,
            "raw_response": result.raw_response,
            "image_hash": result.image_hash,
        }
        cache_file.write_text(json.dumps(cache_data, indent=2))

    async def list_providers(self) -> list[dict[str, Any]]:
        """List all available vision providers and their status."""
        providers = []
        for p in self.VALID_PROVIDERS:
            api_key = self._get_api_key(p)
            has_key = bool(api_key and len(api_key) > 5)
            providers.append({
                "name": p,
                "enabled": p == self._default_provider,
                "api_key_configured": has_key,
                "description": {
                    "openai": "GPT-4 Vision (GPT-4V) via OpenAI API",
                    "gemini": "Gemini Flash/Vision via Google API",
                    "anthropic": "Claude 3 Vision via Anthropic API",
                    "ollama": "Local vision models via Ollama API",
                }.get(p, "Unknown provider"),
            })
        return providers
