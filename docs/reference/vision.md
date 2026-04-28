# Vision Reference

## Overview

NoMan supports image analysis through multiple vision providers.

## Providers

| Provider | Models | Config Key |
|----------|--------|------------|
| OpenAI | GPT-4V | `vision.default_provider = "openai"` |
| Google Gemini | Gemini Vision | `vision.default_provider = "gemini"` |
| Anthropic | Claude Vision | `vision.default_provider = "anthropic"` |
| Ollama | LLaVA, etc. | `vision.default_provider = "ollama"` |

## CLI Commands

```bash
noman vision --image image.png                    # Analyze image
noman vision --image image.png --prompt "describe" # Analyze with prompt
noman vision list                                  # List providers
```
