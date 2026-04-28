"""Integration tests for voice system."""

import pytest


async def test_stt():
    """Test STT engine."""
    from core.voice.stt import STTConfig, STTEngine
    config = STTConfig(provider="edge")
    engine = STTEngine(config)
    assert engine is not None


async def test_tts():
    """Test TTS engine."""
    from core.voice.tts import TTSConfig, TTS
    config = TTSConfig(provider="edge")
    tts = TTS(config)
    assert tts is not None


async def test_audio_processor():
    """Test audio processor."""
    from core.voice.processor import AudioProcessor
    processor = AudioProcessor()
    assert processor is not None
