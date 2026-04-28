"""Speech-to-Text (STT) engine with multi-provider support.

Supported providers:
    - faster_whisper: Local Whisper via faster-whisper (default, free)
    - groq: Whisper via Groq API (free tier available)
    - openai: Whisper via OpenAI API (paid)
    - mistral: Voxtral via Mistral API

Configuration (in ~/.noman/config.toml):
    [stt]
    enabled = true
    provider = "faster_whisper"
    local_model = "base"  # tiny, base, small, medium, large-v3

    [stt.groq]
    api_key = "sk-..."

    [stt.openai]
    api_key = "sk-..."

    [stt.mistral]
    api_key = "tr-..."
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any, BinaryIO

logger = logging.getLogger(__name__)


@dataclass
class STTResult:
    """Result from speech-to-text transcription."""
    text: str
    confidence: float
    provider: str
    duration_seconds: float = 0.0
    language: str | None = None
    segments: list[dict[str, Any]] = field(default_factory=list)
    raw_response: dict[str, Any] | None = None

    def __str__(self) -> str:
        return f"STTResult(provider={self.provider}, confidence={self.confidence:.2f}, text='{self.text[:100]}{'...' if len(self.text) > 100 else ''}')"


class STTEngine:
    """Multi-provider Speech-to-Text engine.

    Supports faster-whisper (local), Groq Whisper, OpenAI Whisper, and Mistral Voxtral.
    Auto-detects provider from config and handles audio normalization via AudioProcessor.
    """

    VALID_PROVIDERS = frozenset(["faster_whisper", "groq", "openai", "mistral"])
    VALID_MODELS = frozenset(["tiny", "base", "small", "medium", "large-v3"])

    def __init__(
        self,
        provider: str | None = None,
        config: dict[str, Any] | None = None,
        cache_dir: str | Path | None = None,
    ) -> None:
        """Initialize STT engine.

        Args:
            provider: STT provider name. Auto-detected from config if None.
            config: Configuration dict (from config.toml [stt] section).
            cache_dir: Directory for cached processed audio files.
        """
        self._config = config or {}
        self._provider = provider or self._detect_provider()
        self._local_model = self._config.get("local_model", "base")
        self._cache_dir = Path(cache_dir) if cache_dir else Path.home() / ".noman" / "stt_cache"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._faster_whisper_model: Any = None
        self._initialized = False

    def _detect_provider(self) -> str:
        """Auto-detect provider from config or environment."""
        provider = self._config.get("provider", "faster_whisper")
        # Validate
        if provider not in self.VALID_PROVIDERS:
            logger.warning(f"Unknown STT provider '{provider}', defaulting to faster_whisper")
            provider = "faster_whisper"
        # Check if the chosen provider has API key configured
        if provider != "faster_whisper":
            api_key = self._get_api_key(provider)
            if not api_key:
                logger.warning(f"STT provider '{provider}' has no API key configured, trying fallback")
                fallback = self._find_available_provider(provider)
                if fallback:
                    logger.info(f"STT fallback to '{fallback}'")
                    provider = fallback
                else:
                    logger.warning("No STT providers available with configured keys, defaulting to faster_whisper")
                    provider = "faster_whisper"
        return provider

    def _find_available_provider(self, exclude: str) -> str | None:
        """Find another available provider excluding the given one."""
        for p in self.VALID_PROVIDERS:
            if p != exclude and p != "faster_whisper":
                if self._get_api_key(p):
                    return p
        return None

    def _get_api_key(self, provider: str) -> str:
        """Get API key for the given provider."""
        section = self._config.get(provider, {})
        key = section.get("api_key", "")
        if not key:
            # Try environment variable
            env_key = {
                "groq": "GROQ_API_KEY",
                "openai": "OPENAI_STT_API_KEY",
                "mistral": "MISTRAL_STT_API_KEY",
            }.get(provider, "")
            if env_key:
                key = os.environ.get(env_key, "")
        return key

    @property
    def provider(self) -> str:
        """Current active provider."""
        return self._provider

    @property
    def is_enabled(self) -> bool:
        """Check if STT is enabled in config."""
        return self._config.get("enabled", False)

    def _ensure_model(self) -> None:
        """Lazy-load the faster-whisper model."""
        if self._faster_whisper_model is not None:
            return
        try:
            from faster_whisper import WhisperModel  # type: ignore[import-untyped]
            model_path = os.environ.get("NOMAN_WHISPER_MODEL_PATH", "")
            compute_type = os.environ.get("NOMAN_WHISPER_COMPUTE_TYPE", "auto")
            self._faster_whisper_model = WhisperModel(
                self._local_model,
                device="auto",
                compute_type=compute_type,
                download_root=model_path or None,
            )
            self._initialized = True
            logger.info(f"STT: loaded faster-whisper model '{self._local_model}'")
        except ImportError:
            logger.error("faster-whisper not installed. Run: pip install faster-whisper")
            raise
        except Exception as e:
            logger.error(f"Failed to load faster-whisper model: {e}")
            raise

    def _get_cache_path(self, audio_data: bytes) -> Path:
        """Get cached audio path based on content hash."""
        content_hash = hashlib.sha256(audio_data).hexdigest()[:16]
        return self._cache_dir / f"{content_hash}.normalized.wav"

    async def transcribe(
        self,
        source: str | Path | bytes | BinaryIO,
        provider: str | None = None,
        **kwargs: Any,
    ) -> STTResult:
        """Transcribe audio from various sources.

        Args:
            source: Audio file path, bytes, or file-like object.
            provider: Override provider for this call.
            **kwargs: Additional provider-specific options.

        Returns:
            STTResult with transcribed text and metadata.

        Raises:
            RuntimeError: If no API key is available for the provider.
            ValueError: If source is not a valid audio format.
        """
        active_provider = provider or self._provider

        # Read audio data
        audio_bytes = await self._read_audio_source(source)

        # Route to provider
        if active_provider == "faster_whisper":
            return await self._transcribe_faster_whisper(audio_bytes, **kwargs)
        elif active_provider == "groq":
            return await self._transcribe_groq(audio_bytes, **kwargs)
        elif active_provider == "openai":
            return await self._transcribe_openai(audio_bytes, **kwargs)
        elif active_provider == "mistral":
            return await self._transcribe_mistral(audio_bytes, **kwargs)
        else:
            raise ValueError(f"Unknown STT provider: {active_provider}")

    async def transcribe_file(
        self,
        file_path: str | Path,
        provider: str | None = None,
        **kwargs: Any,
    ) -> STTResult:
        """Transcribe an audio file.

        Args:
            file_path: Path to audio file (wav, mp3, ogg, flac, m4a).
            provider: Override provider for this call.
            **kwargs: Additional options.

        Returns:
            STTResult with transcribed text.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Audio file not found: {file_path}")
        return await self.transcribe(path, provider=provider, **kwargs)

    async def transcribe_bytes(
        self,
        audio_data: bytes,
        provider: str | None = None,
        **kwargs: Any,
    ) -> STTResult:
        """Transcribe raw audio bytes.

        Args:
            audio_data: Raw audio bytes.
            provider: Override provider for this call.
            **kwargs: Additional options.

        Returns:
            STTResult with transcribed text.
        """
        return await self.transcribe(audio_data, provider=provider, **kwargs)

    async def transcribe_stream(
        self,
        stream: BinaryIO,
        provider: str | None = None,
        **kwargs: Any,
    ) -> STTResult:
        """Transcribe from a file-like stream.

        Args:
            stream: Binary file-like object.
            provider: Override provider for this call.
            **kwargs: Additional options.

        Returns:
            STTResult with transcribed text.
        """
        audio_data = stream.read()
        return await self.transcribe(audio_data, provider=provider, **kwargs)

    async def _read_audio_source(self, source: str | Path | bytes | BinaryIO) -> bytes:
        """Read audio from various source types and return normalized bytes."""
        from core.voice.processor import AudioProcessor

        processor = AudioProcessor(cache_dir=str(self._cache_dir))

        if isinstance(source, (str, Path)):
            if not Path(source).exists():
                raise FileNotFoundError(f"Audio file not found: {source}")
            return await processor.normalize_for_stt(str(source))
        elif isinstance(source, bytes):
            # Write to temp file, normalize, return bytes
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(source)
                tmp.flush()
                result = await processor.normalize_for_stt(tmp.name)
                Path(tmp.name).unlink(missing_ok=True)
                return result
        elif hasattr(source, "read"):
            data = source.read()
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(data)
                tmp.flush()
                result = await processor.normalize_for_stt(tmp.name)
                Path(tmp.name).unlink(missing_ok=True)
                return result
        else:
            raise ValueError(f"Unsupported audio source type: {type(source)}")

    async def _transcribe_faster_whisper(self, audio_bytes: bytes, **kwargs: Any) -> STTResult:
        """Transcribe using faster-whisper (local model)."""
        self._ensure_model()
        from faster_whisper import WhisperModel  # type: ignore[import-untyped]

        # Write to temp file for faster-whisper
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        try:
            segments = []
            text_parts = []
            duration = 0.0

            # Use the loaded model
            model = self._faster_whisper_model
            if model:
                # Transcribe
                result = model.transcribe(
                    tmp_path,
                    beam_size=kwargs.get("beam_size", 5),
                    language=kwargs.get("language"),
                    task=kwargs.get("task", "transcribe"),
                    vad_filter=kwargs.get("vad_filter", True),
                    vad_parameters=dict(
                        kwargs.get("vad_parameters", {
                            "min_silence_duration_ms": 500,
                        })
                    ),
                    temperature=kwargs.get("temperature", 0.0),
                )

                for seg in result:
                    segments.append({
                        "start": seg.start,
                        "end": seg.end,
                        "text": seg.text.strip(),
                    })
                    text_parts.append(seg.text.strip())
                    duration = seg.end

            full_text = " ".join(text_parts)
            return STTResult(
                text=full_text,
                confidence=0.95,  # faster-whisper doesn't expose per-segment confidence easily
                provider="faster_whisper",
                duration_seconds=duration,
                segments=segments,
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    async def _transcribe_groq(self, audio_bytes: bytes, **kwargs: Any) -> STTResult:
        """Transcribe using Groq Whisper API."""
        api_key = self._get_api_key("groq")
        if not api_key:
            raise RuntimeError(
                "GROQ_API_KEY not set. Set it via environment variable or config.toml [stt.groq] section."
            )

        # Write to temp file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        try:
            import httpx
            async with httpx.AsyncClient(timeout=60.0) as client:
                with open(tmp_path, "rb") as f:
                    files = {"file": ("audio.wav", f, "audio/wav")}
                    data = {
                        "model": kwargs.get("model", "whisper-large-v3-turbo"),
                        "language": kwargs.get("language"),
                        "temperature": kwargs.get("temperature", 0.0),
                    }
                    resp = await client.post(
                        "https://api.groq.com/openai/v1/audio/transcriptions",
                        files=files,
                        data=data,
                        headers={"Authorization": f"Bearer {api_key}"},
                    )
                    resp.raise_for_status()
                    result = resp.json()

            return STTResult(
                text=result["text"],
                confidence=result.get("confidence", 0.0),
                provider="groq",
                duration_seconds=result.get("duration", 0.0),
                language=result.get("language"),
                raw_response=result,
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    async def _transcribe_openai(self, audio_bytes: bytes, **kwargs: Any) -> STTResult:
        """Transcribe using OpenAI Whisper API."""
        api_key = self._get_api_key("openai")
        if not api_key:
            raise RuntimeError(
                "OPENAI_STT_API_KEY not set. Set it via environment variable or config.toml [stt.openai] section."
            )

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        try:
            import httpx
            async with httpx.AsyncClient(timeout=60.0) as client:
                with open(tmp_path, "rb") as f:
                    files = {"file": ("audio.wav", f, "audio/wav")}
                    data = {
                        "model": kwargs.get("model", "whisper-1"),
                        "language": kwargs.get("language"),
                        "temperature": kwargs.get("temperature", 0.0),
                        "response_format": "verbose_json",
                    }
                    resp = await client.post(
                        "https://api.openai.com/v1/audio/transcriptions",
                        files=files,
                        data=data,
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "OpenAI-Beta": "whisper=v1",
                        },
                    )
                    resp.raise_for_status()
                    result = resp.json()

            return STTResult(
                text=result["text"],
                confidence=result.get("confidence", 0.0),
                provider="openai",
                duration_seconds=result.get("duration", 0.0),
                language=result.get("language"),
                segments=result.get("segments", []),
                raw_response=result,
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    async def _transcribe_mistral(self, audio_bytes: bytes, **kwargs: Any) -> STTResult:
        """Transcribe using Mistral Voxtral API."""
        api_key = self._get_api_key("mistral")
        if not api_key:
            raise RuntimeError(
                "MISTRAL_STT_API_KEY not set. Set it via environment variable or config.toml [stt.mistral] section."
            )

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        try:
            import httpx
            async with httpx.AsyncClient(timeout=60.0) as client:
                with open(tmp_path, "rb") as f:
                    files = {"file": ("audio.wav", f, "audio/wav")}
                    data = {
                        "model": kwargs.get("model", "voxtral-32b"),
                        "language": kwargs.get("language"),
                    }
                    resp = await client.post(
                        "https://api.mistral.ai/v1/audio/transcriptions",
                        files=files,
                        data=data,
                        headers={"Authorization": f"Bearer {api_key}"},
                    )
                    resp.raise_for_status()
                    result = resp.json()

            return STTResult(
                text=result["text"],
                confidence=result.get("confidence", 0.0),
                provider="mistral",
                duration_seconds=result.get("duration", 0.0),
                language=result.get("language"),
                raw_response=result,
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    async def list_providers(self) -> list[dict[str, Any]]:
        """List all available STT providers and their status."""
        providers = []
        for p in self.VALID_PROVIDERS:
            api_key = self._get_api_key(p) if p != "faster_whisper" else "local"
            has_key = bool(api_key and api_key != "local" and len(api_key) > 5)
            providers.append({
                "name": p,
                "enabled": p == self._provider,
                "api_key_configured": has_key,
                "free": p == "faster_whisper" or p == "groq",
                "description": {
                    "faster_whisper": "Local Whisper via faster-whisper (free, offline)",
                    "groq": "Whisper via Groq API (free tier available)",
                    "openai": "Whisper via OpenAI API (paid)",
                    "mistral": "Voxtral via Mistral API",
                }.get(p, "Unknown provider"),
            })
        return providers
