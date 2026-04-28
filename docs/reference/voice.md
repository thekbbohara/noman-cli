# Voice Reference

## Overview

NoMan supports voice input (STT) and output (TTS) for hands-free operation.

## STT (Speech-to-Text) Providers

| Provider | Free? | Config Key |
|----------|-------|------------|
| faster-whisper | ✅ (local) | `stt.provider = "faster_whisper"` |
| Groq Whisper | ✅ (free tier) | `stt.provider = "groq"` |
| OpenAI Whisper | Paid | `stt.provider = "openai"` |
| Mistral Voxtral | Paid | `stt.provider = "mistral"` |

## TTS (Text-to-Speech) Providers

| Provider | Free? | Config Key |
|----------|-------|------------|
| Edge TTS | ✅ (default) | `tts.provider = "edge"` |
| ElevenLabs | ✅ (free tier) | `tts.provider = "elevenlabs"` |
| OpenAI TTS | Paid | `tts.provider = "openai"` |
| MiniMax TTS | Paid | `tts.provider = "minimax"` |
| NeuTTS | ✅ (local) | `tts.provider = "neutts"` |

## Configuration

```toml
[stt]
enabled = true
provider = "faster_whisper"

[tts]
enabled = true
provider = "edge"
```

## CLI Commands

```bash
noman voice stt --file audio.mp3    # Transcribe audio
noman voice tts --text "hello"       # Generate speech
noman voice list                     # List available providers
```
