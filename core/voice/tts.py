"""Text-to-Speech (TTS) engine with multi-provider support.

Supported providers:
    - edge: Edge TTS (free, default)
    - elevenlabs: ElevenLabs (free tier available)
    - openai: OpenAI TTS
    - minimax: MiniMax TTS
    - mistral: Mistral Voxtral TTS
    - neutts: NeuTTS (local, free)

Configuration (in ~/.noman/config.toml):
    [tts]
    enabled = true
    provider = "edge"
    default_voice = "en-US-AvaMultilingualNeural"

    [tts.edge]
    voice = "en-US-AvaMultilingualNeural"
    speed = 1.0
    pitch = 0

    [tts.elevenlabs]
    api_key = "sk-..."
    voice_id = "..."

    [tts.openai]
    api_key = "sk-..."
    model = "tts-1"
    voice = "nova"

    [tts.minimax]
    api_key = "sk-..."
    voice_id = "..."

    [tts.mistral]
    api_key = "sk-..."

    [tts.neutts]
    base_url = "http://localhost:8080"
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TTSResult:
    """Result from text-to-speech synthesis."""
    audio_path: str
    provider: str
    duration_seconds: float = 0.0
    format: str = "mp3"
    sample_rate: int = 24000
    text: str = ""
    raw_response: dict[str, Any] | None = None

    def __str__(self) -> str:
        return f"TTSResult(provider={self.provider}, path={self.audio_path}, duration={self.duration_seconds:.1f}s)"


class TTSEngine:
    """Multi-provider Text-to-Speech engine.

    Supports Edge TTS (free), ElevenLabs, OpenAI TTS, MiniMax, Mistral Voxtral, and NeuTTS.
    Auto-detects provider from config and handles audio output formatting.
    """

    VALID_PROVIDERS = frozenset(["edge", "elevenlabs", "openai", "minimax", "mistral", "neutts"])

    def __init__(
        self,
        provider: str | None = None,
        config: dict[str, Any] | None = None,
        output_dir: str | Path | None = None,
    ) -> None:
        """Initialize TTS engine.

        Args:
            provider: TTS provider name. Auto-detected from config if None.
            config: Configuration dict (from config.toml [tts] section).
            output_dir: Directory for output audio files.
        """
        self._config = config or {}
        self._provider = provider or self._detect_provider()
        self._output_dir = Path(output_dir) if output_dir else Path.home() / ".noman" / "tts_output"
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._initialized = False

    def _detect_provider(self) -> str:
        """Auto-detect provider from config or environment."""
        provider = self._config.get("provider", "edge")
        if provider not in self.VALID_PROVIDERS:
            logger.warning(f"Unknown TTS provider '{provider}', defaulting to edge")
            provider = "edge"
        # If the chosen provider needs an API key, check it's available
        if provider != "edge":
            api_key = self._get_api_key(provider)
            if not api_key:
                logger.warning(f"TTS provider '{provider}' has no API key configured, falling back")
                fallback = self._find_fallback_provider(provider)
                if fallback:
                    logger.info(f"TTS fallback to '{fallback}'")
                    provider = fallback
                else:
                    provider = "edge"
        return provider

    def _find_fallback_provider(self, exclude: str) -> str | None:
        """Find a fallback TTS provider with configured credentials."""
        for p in self.VALID_PROVIDERS:
            if p != exclude and p != "edge":
                if self._get_api_key(p):
                    return p
        return None

    def _get_api_key(self, provider: str) -> str:
        """Get API key for the given provider."""
        section = self._config.get(provider, {})
        key = section.get("api_key", "")
        if not key:
            env_map = {
                "elevenlabs": "ELEVENLABS_API_KEY",
                "openai": "OPENAI_TTS_API_KEY",
                "minimax": "MINIMAX_TTS_API_KEY",
                "mistral": "MISTRAL_TTS_API_KEY",
            }
            env_key = env_map.get(provider, "")
            if env_key:
                key = os.environ.get(env_key, "")
        return key

    @property
    def provider(self) -> str:
        """Current active provider."""
        return self._provider

    @property
    def is_enabled(self) -> bool:
        """Check if TTS is enabled in config."""
        return self._config.get("enabled", False)

    async def synthesize(
        self,
        text: str,
        provider: str | None = None,
        output_dir: str | Path | None = None,
        speed: float = 1.0,
        pitch: float = 0,
        **kwargs: Any,
    ) -> TTSResult:
        """Synthesize speech from text.

        Args:
            text: Text to synthesize.
            provider: Override provider for this call.
            output_dir: Override output directory.
            speed: Speech speed multiplier (0.5 = half speed, 2.0 = double speed).
            pitch: Pitch shift in semitones (-12 to +12).
            **kwargs: Additional provider-specific options.

        Returns:
            TTSResult with path to generated audio file.

        Raises:
            RuntimeError: If no API key is available for the provider.
            ValueError: If text is empty.
        """
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")

        active_provider = provider or self._provider
        out_dir = Path(output_dir) if output_dir else self._output_dir
        out_dir.mkdir(parents=True, exist_ok=True)

        if active_provider == "edge":
            return await self._synthesize_edge(text, output_dir=out_dir, speed=speed, pitch=pitch, **kwargs)
        elif active_provider == "elevenlabs":
            return await self._synthesize_elevenlabs(text, output_dir=out_dir, speed=speed, **kwargs)
        elif active_provider == "openai":
            return await self._synthesize_openai(text, output_dir=out_dir, speed=speed, **kwargs)
        elif active_provider == "minimax":
            return await self._synthesize_minimax(text, output_dir=out_dir, speed=speed, **kwargs)
        elif active_provider == "mistral":
            return await self._synthesize_mistral(text, output_dir=out_dir, speed=speed, **kwargs)
        elif active_provider == "neutts":
            return await self._synthesize_neutts(text, output_dir=out_dir, speed=speed, **kwargs)
        else:
            raise ValueError(f"Unknown TTS provider: {active_provider}")

    async def synthesize_to_file(
        self,
        text: str,
        output_path: str | Path,
        provider: str | None = None,
        speed: float = 1.0,
        pitch: float = 0,
        **kwargs: Any,
    ) -> TTSResult:
        """Synthesize speech and save to a specific file path.

        Args:
            text: Text to synthesize.
            output_path: Output file path (will create .mp3).
            provider: Override provider for this call.
            speed: Speech speed multiplier.
            pitch: Pitch shift in semitones.
            **kwargs: Additional options.

        Returns:
            TTSResult with path to output file.
        """
        out_path = Path(output_path)
        if not out_path.suffix:
            out_path = out_path.with_suffix(".mp3")
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # For providers that need a directory, use parent dir
        if provider or self._provider in ("edge",):
            return await self.synthesize(
                text, provider=provider, output_dir=str(out_path.parent),
                speed=speed, pitch=pitch, **kwargs
            )
        else:
            return await self.synthesize(
                text, provider=provider, output_dir=str(out_path.parent),
                speed=speed, pitch=pitch, **kwargs
            )

    async def list_providers(self) -> list[dict[str, Any]]:
        """List all available TTS providers and their status."""
        providers = []
        for p in self.VALID_PROVIDERS:
            api_key = self._get_api_key(p) if p != "edge" else "built-in"
            has_key = bool(api_key and api_key != "built-in" and len(api_key) > 5)
            providers.append({
                "name": p,
                "enabled": p == self._provider,
                "api_key_configured": has_key,
                "free": p == "edge" or p == "neutts",
                "description": {
                    "edge": "Microsoft Edge TTS (free, built-in)",
                    "elevenlabs": "ElevenLabs (free tier available)",
                    "openai": "OpenAI TTS (paid)",
                    "minimax": "MiniMax TTS",
                    "mistral": "Mistral Voxtral TTS",
                    "neutts": "NeuTTS local (free, offline)",
                }.get(p, "Unknown provider"),
            })
        return providers

    # --- Provider implementations ---

    async def _synthesize_edge(
        self,
        text: str,
        output_dir: Path,
        speed: float = 1.0,
        pitch: float = 0,
        **kwargs: Any,
    ) -> TTSResult:
        """Synthesize using Edge TTS (free, built-in)."""
        try:
            import edge_tts  # type: ignore[import-untyped]
        except ImportError:
            logger.error("edge-tts not installed. Run: pip install edge-tts")
            raise

        voice = self._config.get("edge", {}).get("voice", "en-US-AvaMultilingualNeural")
        rate = f"+{int(speed * 100)}%" if speed >= 1.0 else f"{int(speed * 100)}%"

        # Generate to temp file
        output_file = output_dir / f"tts_{int(asyncio.get_event_loop().time() * 1000)}.mp3"

        communicate = edge_tts.Communicate(text, voice, rate=rate)
        await communicate.save(str(output_file))

        return TTSResult(
            audio_path=str(output_file),
            provider="edge",
            format="mp3",
            text=text,
        )

    async def _synthesize_elevenlabs(
        self,
        text: str,
        output_dir: Path,
        speed: float = 1.0,
        **kwargs: Any,
    ) -> TTSResult:
        """Synthesize using ElevenLabs API."""
        api_key = self._get_api_key("elevenlabs")
        if not api_key:
            raise RuntimeError(
                "ELEVENLABS_API_KEY not set. Set via env var or config.toml [tts.elevenlabs] section."
            )

        voice_id = self._config.get("elevenlabs", {}).get("voice_id", "pNInz6obpgDQGcFmaJgB")
        model = self._config.get("elevenlabs", {}).get("model", "eleven_multilingual_v2")
        output_file = output_dir / f"tts_{int(asyncio.get_event_loop().time() * 1000)}.mp3"

        import httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream",
                json={
                    "text": text,
                    "model_id": model,
                    "voice_settings": {
                        "stability": self._config.get("elevenlabs", {}).get("stability", 0.5),
                        "similarity_boost": self._config.get("elevenlabs", {}).get("similarity_boost", 0.75),
                    },
                },
                headers={
                    "xi-api-key": api_key,
                    "Content-Type": "application/json",
                },
                follow_redirects=True,
            )
            resp.raise_for_status()
            output_file.write_bytes(await resp.aread())

        return TTSResult(
            audio_path=str(output_file),
            provider="elevenlabs",
            format="mp3",
            text=text,
        )

    async def _synthesize_openai(
        self,
        text: str,
        output_dir: Path,
        speed: float = 1.0,
        **kwargs: Any,
    ) -> TTSResult:
        """Synthesize using OpenAI TTS API."""
        api_key = self._get_api_key("openai")
        if not api_key:
            raise RuntimeError(
                "OPENAI_TTS_API_KEY not set. Set via env var or config.toml [tts.openai] section."
            )

        model = self._config.get("openai", {}).get("model", "tts-1")
        voice = self._config.get("openai", {}).get("voice", "nova")
        response_format = self._config.get("openai", {}).get("response_format", "mp3")
        output_file = output_dir / f"tts_{int(asyncio.get_loop().time() * 1000)}.{response_format}"

        import httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/audio/speech",
                json={
                    "model": model,
                    "input": text,
                    "voice": voice,
                    "speed": speed,
                    "response_format": response_format,
                },
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            output_file.write_bytes(await resp.aread())

        return TTSResult(
            audio_path=str(output_file),
            provider="openai",
            format=response_format,
            text=text,
        )

    async def _synthesize_minimax(
        self,
        text: str,
        output_dir: Path,
        speed: float = 1.0,
        **kwargs: Any,
    ) -> TTSResult:
        """Synthesize using MiniMax TTS API."""
        api_key = self._get_api_key("minimax")
        if not api_key:
            raise RuntimeError(
                "MINIMAX_TTS_API_KEY not set. Set via env var or config.toml [tts.minimax] section."
            )

        voice_id = self._config.get("minimax", {}).get("voice_id", "female-1")
        output_file = output_dir / f"tts_{int(asyncio.get_event_loop().time() * 1000)}.mp3"

        import httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.minimaxi.com/v1/t2x-vocals",
                json={
                    "model": "speech-01-hd",
                    "voice_id": voice_id,
                    "text": text,
                    "speed_ratio": speed,
                },
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            result = resp.json()
            # MiniMax may return audio as base64 or URL
            audio_data = result.get("audio", result.get("audio_url", ""))
            if isinstance(audio_data, str) and audio_data.startswith("http"):
                audio_resp = await client.get(audio_data)
                audio_resp.raise_for_status()
                output_file.write_bytes(await audio_resp.aread())
            else:
                import base64
                output_file.write_bytes(base64.b64decode(audio_data))

        return TTSResult(
            audio_path=str(output_file),
            provider="minimax",
            format="mp3",
            text=text,
        )

    async def _synthesize_mistral(
        self,
        text: str,
        output_dir: Path,
        speed: float = 1.0,
        **kwargs: Any,
    ) -> TTSResult:
        """Synthesize using Mistral Voxtral TTS API."""
        api_key = self._get_api_key("mistral")
        if not api_key:
            raise RuntimeError(
                "MISTRAL_TTS_API_KEY not set. Set via env var or config.toml [tts.mistral] section."
            )

        model = self._config.get("mistral", {}).get("model", "voxtral-32b")
        output_file = output_dir / f"tts_{int(asyncio.get_event_loop().time() * 1000)}.mp3"

        import httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.mistral.ai/v1/audio/speech",
                json={
                    "model": model,
                    "input": text,
                    "voice": self._config.get("mistral", {}).get("voice", "alba"),
                    "speed": speed,
                },
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            output_file.write_bytes(await resp.aread())

        return TTSResult(
            audio_path=str(output_file),
            provider="mistral",
            format="mp3",
            text=text,
        )

    async def _synthesize_neutts(
        self,
        text: str,
        output_dir: Path,
        speed: float = 1.0,
        **kwargs: Any,
    ) -> TTSResult:
        """Synthesize using NeuTTS local server."""
        base_url = self._config.get("neutts", {}).get("base_url", "http://localhost:8080")
        output_file = output_dir / f"tts_{int(asyncio.get_event_loop().time() * 1000)}.mp3"

        import httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{base_url}/tts",
                json={
                    "text": text,
                    "speed": speed,
                },
            )
            resp.raise_for_status()
            output_file.write_bytes(await resp.aread())

        return TTSResult(
            audio_path=str(output_file),
            provider="neutts",
            format="mp3",
            text=text,
        )
