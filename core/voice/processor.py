"""AudioProcessor: format conversion, normalization, and caching for audio files.

Handles:
    - Format conversion (wav, mp3, ogg, flac, m4a)
    - Audio normalization for STT (sample rate, channels, volume)
    - Cache to avoid re-processing the same audio
"""

from __future__ import annotations

import hashlib
import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Supported audio formats
SUPPORTED_FORMATS = frozenset(["wav", "mp3", "ogg", "flac", "m4a", "aac", "webm"])

# STT normalization settings
DEFAULT_SAMPLE_RATE = 16000
DEFAULT_CHANNELS = 1  # mono for STT
DEFAULT_BITRATE = "128k"


class AudioProcessorError(Exception):
    """Base exception for audio processing errors."""


class AudioFormatError(AudioProcessorError):
    """Raised when the audio format is not supported."""


class AudioNormalizationError(AudioProcessorError):
    """Raised when audio normalization fails."""


class AudioProcessor:
    """Process and normalize audio files for STT/TTS workflows.

    Handles format conversion between wav, mp3, ogg, flac, m4a, etc.
    Normalizes audio for optimal STT recognition (16kHz mono WAV).
    Caches processed files to avoid redundant work.
    """

    def __init__(
        self,
        cache_dir: str | Path | None = None,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        channels: int = DEFAULT_CHANNELS,
    ) -> None:
        """Initialize AudioProcessor.

        Args:
            cache_dir: Directory for cached processed files.
            sample_rate: Target sample rate for normalization (default 16000 Hz).
            channels: Target channels for normalization (default 1 = mono).
        """
        self._cache_dir = Path(cache_dir) if cache_dir else Path.home() / ".noman" / "audio_cache"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._sample_rate = sample_rate
        self._channels = channels

    @property
    def cache_dir(self) -> Path:
        """Cache directory path."""
        return self._cache_dir

    def _get_cache_key(self, file_path: str | Path, target_format: str, target_sr: int) -> str:
        """Generate cache key from file content and processing parameters."""
        content_hash = hashlib.sha256(Path(file_path).read_bytes()).hexdigest()[:16]
        return f"{content_hash}_{target_format}_{target_sr}"

    def _get_cached_path(self, file_path: str | Path, target_format: str, target_sr: int) -> Path | None:
        """Get cached file path if it exists. Returns None if not cached."""
        key = self._get_cache_key(file_path, target_format, target_sr)
        cached = self._cache_dir / f"{key}.{target_format}"
        if cached.exists():
            return cached
        return None

    async def normalize_for_stt(
        self,
        file_path: str | Path,
        target_format: str = "wav",
        target_sample_rate: int = DEFAULT_SAMPLE_RATE,
        target_channels: int = DEFAULT_CHANNELS,
    ) -> bytes:
        """Normalize audio file for STT processing.

        Converts to mono 16kHz WAV (optimal for whisper models).
        Uses cache to avoid re-processing.

        Args:
            file_path: Path to input audio file.
            target_format: Output format (default: wav).
            target_sample_rate: Target sample rate (default: 16000 Hz).
            target_channels: Target channels (default: 1 = mono).

        Returns:
            Normalized audio data as bytes.

        Raises:
            AudioFormatError: If the input format is not supported.
            AudioNormalizationError: If normalization fails.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Audio file not found: {file_path}")

        input_ext = path.suffix.lstrip(".").lower()
        if input_ext not in SUPPORTED_FORMATS:
            raise AudioFormatError(
                f"Unsupported audio format: {input_ext}. "
                f"Supported: {', '.join(sorted(SUPPORTED_FORMATS))}"
            )

        # Check cache
        cache_key = f"{target_format}_{target_sample_rate}"
        cached = self._cache_dir / f"{hashlib.sha256(path.read_bytes()).hexdigest()[:16]}_{cache_key}.{target_format}"

        if cached.exists():
            logger.debug(f"Audio: using cached file {cached}")
            return cached.read_bytes()

        # Check if already in correct format
        if (
            input_ext == target_format
            and target_channels == 1
            and target_sample_rate == DEFAULT_SAMPLE_RATE
        ):
            return path.read_bytes()

        # Normalize using ffmpeg
        try:
            result = await self._run_ffmpeg(
                input_path=str(path),
                output_format=target_format,
                sample_rate=target_sample_rate,
                channels=target_channels,
            )
            return result
        except subprocess.CalledProcessError as e:
            raise AudioNormalizationError(f"ffmpeg failed: {e}") from e
        except FileNotFoundError:
            raise AudioNormalizationError(
                "ffmpeg not found. Install it: apt install ffmpeg (Linux), "
                "brew install ffmpeg (macOS), or choco install ffmpeg (Windows)"
            ) from None

    async def convert_format(
        self,
        file_path: str | Path,
        output_format: str,
        output_path: str | Path | None = None,
    ) -> Path:
        """Convert audio file to a different format.

        Args:
            file_path: Input audio file path.
            output_format: Target format (wav, mp3, ogg, flac).
            output_path: Optional output path. Auto-generated if None.

        Returns:
            Path to the converted file.

        Raises:
            AudioFormatError: If formats are not supported.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Audio file not found: {file_path}")

        input_ext = path.suffix.lstrip(".").lower()
        output_ext = output_format.lower().lstrip(".")

        if input_ext not in SUPPORTED_FORMATS:
            raise AudioFormatError(f"Unsupported input format: {input_ext}")
        if output_ext not in SUPPORTED_FORMATS:
            raise AudioFormatError(f"Unsupported output format: {output_ext}")

        if output_path:
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
        else:
            out = path.with_suffix(f".{output_ext}")

        await self._run_ffmpeg(
            input_path=str(path),
            output_format=output_ext,
            output_path=str(out),
        )
        return out

    async def extract_audio(
        self,
        video_path: str | Path,
        output_format: str = "wav",
        output_path: str | Path | None = None,
    ) -> Path:
        """Extract audio from a video file.

        Args:
            video_path: Path to video file (mp4, webm, mkv, etc.).
            output_format: Target audio format.
            output_path: Optional output path.

        Returns:
            Path to the extracted audio file.
        """
        path = Path(video_path)
        if not path.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")

        if output_path:
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
        else:
            out = path.with_suffix(f".{output_format}")

        await self._run_ffmpeg(
            input_path=str(path),
            output_format=output_format,
            output_path=str(out),
            video_input=True,
        )
        return out

    async def get_audio_info(self, file_path: str | Path) -> dict[str, Any]:
        """Get audio file metadata using ffprobe.

        Args:
            file_path: Path to audio file.

        Returns:
            Dict with duration, sample_rate, channels, codec, bitrate info.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        try:
            import json
            result = subprocess.run(
                [
                    "ffprobe", "-v", "quiet",
                    "-print_format", "json",
                    "-show_format", "-show_streams",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return {"error": result.stderr.strip()}

            data = json.loads(result.stdout)
            fmt = data.get("format", {})
            streams = data.get("streams", [])

            audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

            return {
                "duration": float(fmt.get("duration", 0)),
                "sample_rate": int(audio_stream.get("sample_rate", 0)) if audio_stream else 0,
                "channels": int(audio_stream.get("channels", 0)) if audio_stream else 0,
                "codec": audio_stream.get("codec_name", "unknown") if audio_stream else "unknown",
                "bitrate": int(fmt.get("bit_rate", 0)) if fmt.get("bit_rate") else 0,
                "format": fmt.get("format_name", "unknown"),
                "filename": str(path),
            }
        except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError) as e:
            return {"error": str(e)}

    async def _run_ffmpeg(
        self,
        input_path: str,
        output_format: str,
        sample_rate: int | None = None,
        channels: int | None = None,
        output_path: str | None = None,
        video_input: bool = False,
    ) -> bytes:
        """Run ffmpeg command and return output as bytes.

        Args:
            input_path: Path to input file.
            output_format: Target output format.
            sample_rate: Target sample rate (for normalization).
            channels: Target channel count (for normalization).
            output_path: Optional output file path.
            video_input: If True, extract audio from video.

        Returns:
            Output audio as bytes.
        """
        cmd = ["ffmpeg", "-y"]  # -y: overwrite output files

        if video_input:
            cmd.extend(["-i", input_path])
        else:
            cmd.extend(["-i", input_path])

        if sample_rate:
            cmd.extend(["-ar", str(sample_rate)])
        if channels:
            cmd.extend(["-ac", str(channels)])

        # Add output format options
        if output_format == "wav":
            cmd.extend(["-f", "wav", "-acodec", "pcm_s16le"])
        elif output_format == "mp3":
            cmd.extend(["-f", "mp3", "-ab", DEFAULT_BITRATE])
        elif output_format == "ogg":
            cmd.extend(["-f", "ogg", "-acodec", "libvorbis"])
        elif output_format == "flac":
            cmd.extend(["-f", "flac"])
        elif output_format == "m4a":
            cmd.extend(["-f", "mp4", "-acodec", "aac"])

        if output_path:
            cmd.append(output_path)
        else:
            # Output to stdout
            cmd.append("-")

        logger.debug(f"ffmpeg command: {' '.join(cmd)}")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.error(f"ffmpeg error: {stderr.decode()[:500]}")
            raise subprocess.CalledProcessError(proc.returncode, cmd)

        # If no output_path was specified, stdout has the data
        if not output_path:
            return stdout

        return Path(output_path).read_bytes()


# Keep reference to asyncio in module scope
import asyncio  # noqa: E402
