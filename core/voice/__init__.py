"""Voice module for noman-cli.

Speech-to-Text (STT) and Text-to-Speech (TTS) engines with multi-provider support.

STT providers: faster-whisper (local), Groq Whisper, OpenAI Whisper, Mistral Voxtral
TTS providers: Edge TTS (free), ElevenLabs, OpenAI TTS, MiniMax, Mistral Voxtral, NeuTTS

Usage (programmatic):
    from core.voice.stt import STTEngine
    stt = STTEngine()
    result = await stt.transcribe("audio.mp3")

    from core.voice.tts import TTSEngine
    tts = TTSEngine()
    path = await tts.synthesize("Hello world")

CLI:
    noman voice stt --file audio.mp3   - Transcribe audio
    noman voice tts --text "hello"     - Generate speech
    noman voice list                   - List available providers
"""

from __future__ import annotations

from core.voice.processor import AudioProcessor
from core.voice.stt import STTResult, STTEngine
from core.voice.tts import TTSEngine

__all__ = [
    "AudioProcessor",
    "STTEngine",
    "STTResult",
    "TTSEngine",
]
