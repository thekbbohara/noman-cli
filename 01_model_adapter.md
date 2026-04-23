## 1. Model Adapter

### 1.1 Purpose

The Model Adapter provides a unified interface to multiple LLM providers while supporting role-based routing (planner/executor/critic). It normalizes different provider APIs into a single OpenAI-compatible dialect.

### 1.2 Key Responsibilities

| Responsibility | Description | Implementation Notes |
|----------------|-------------|---------------------|
| **Provider Abstraction** | Normalize OpenAI, Anthropic, Ollama, Groq, etc. | Single `chat()` interface |
| **Role Routing** | Route planner/executor/critic to different models | Configurable per-role |
| **Capability Negotiation** | Probe provider capabilities at startup | Cache results with TTL |
| **Streaming Support** | Handle streaming responses uniformly | Async generator interface |
| **Tool Calling** | Normalize tool-calling dialects | Detect and adapt per-provider |
| **Fallback Logic** | Graceful degradation when providers fail | Retry + fallback chain |
| **Cost Tracking** | Track token usage and costs per provider | Log to traces |

### 1.3 Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Model Adapter                            │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────┐    ┌─────────────────┐                │
│  │   Provider      │    │   Capability    │                │
│  │   Registry      │    │   Negotiator    │                │
│  └────────┬────────┘    └────────┬────────┘                │
│           │                      │                          │
│           ▼                      ▼                          │
│  ┌─────────────────┐    ┌─────────────────┐                │
│  │   Role          │    │   Provider      │                │
│  │   Router        │    │   Adapters      │                │
│  │                 │    │  - OpenAI       │                │
│  │ (planner/       │    │  - Anthropic    │                │
│  │  executor/      │    │  - Ollama       │                │
│  │  critic)        │    │  - Groq         │                │
│  └────────┬────────┘    └────────┬────────┘                │
│           │                      │                          │
│           └──────────┬───────────┘                          │
│                      │                                      │
│              ┌───────▼────────┐                             │
│              │   Unified      │                             │
│              │   Interface    │                             │
│              │   chat()       │                             │
│              └───────┬────────┘                             │
│                      │                                      │
│  ┌───────────────────▼───────────────────┐                 │
│  │         Streaming Response Handler    │                 │
│  │         + Tool Call Parser            │                 │
│  └───────────────────────────────────────┘                 │
│                                                             │
│  ┌─────────────────────────────────────────┐               │
│  │          Cost Tracker + Logger          │               │
│  └─────────────────────────────────────────┘               │
└─────────────────────────────────────────────────────────────┘
```

### 1.4 Configuration Schema

```toml
# user/config.toml

[model]
# Default provider (used for all roles if not overridden)
default = "local_ollama"

# Per-role overrides (optional)
planner = "claude_cloud"     # Complex reasoning → stronger model
executor = "local_ollama"    # Tool calling → local is fine
critic = "groq_fast"         # Fast feedback → low-latency model

# Provider definitions
[[providers]]
id = "local_ollama"
type = "openai_compat"
base_url = "http://localhost:11434/v1"
model = "codellama:34b"
api_key = ""  # Not needed for local
timeout_sec = 120
max_retries = 3
stream = true

[[providers]]
id = "claude_cloud"
type = "anthropic"
api_key = "${ANTHROPIC_API_KEY}"
model = "claude-sonnet-4-20250514"
timeout_sec = 60
max_retries = 2
stream = true
# Anthropic-specific quirks
max_tokens_per_request = 4096
system_prompt_in_messages = true

[[providers]]
id = "groq_fast"
type = "openai_compat"
base_url = "https://api.groq.com/openai/v1"
api_key = "${GROQ_API_KEY}"
model = "mixtral-8x7b-32768"
timeout_sec = 30
max_retries = 3
stream = true
```

### 1.5 Provider Adapter Interface

```python
# core/adapters/base.py

from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional
from dataclasses import dataclass

@dataclass
class Message:
    role: str  # "system", "user", "assistant"
    content: str
    tool_calls: Optional[list] = None
    tool_call_id: Optional[str] = None

@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict  # JSON Schema

@dataclass
class Response:
    content: str
    tool_calls: list
    usage: dict  # {prompt_tokens, completion_tokens, total_tokens}
    model: str
    finish_reason: str

class BaseAdapter(ABC):
    """Base class for all model providers."""
    
    def __init__(self, config: dict):
        self.config = config
        self.capabilities = {}
    
    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        tools: Optional[list[ToolDefinition]] = None,
        stream: bool = False
    ) -> Response | AsyncIterator[str]:
        """Send chat request and return response."""
        pass
    
    @abstractmethod
    async def probe_capabilities(self) -> dict:
        """Probe provider for capabilities and quirks."""
        pass
    
    async def validate_connection(self) -> bool:
        """Check if provider is reachable and authenticated."""
        try:
            await self.probe_capabilities()
            return True
        except Exception:
            return False
```

### 1.6 Capability Negotiation Flow

```
1. Startup probe (per provider)
   ├─► GET /models endpoint (if available)
   ├─► Send test chat with tool call
   ├─► Detect tool-calling dialect:
   │   ├─ OpenAI: {"name": "...", "arguments": {...}}
   │   ├─ Anthropic: <tool_use> XML tags
   │   └─ Custom: regex patterns
   ├─► Measure latency (p50, p95)
   ├─► Check max context window
   ├─► Store in .noman/cache/capabilities.json
   └─► Set TTL (re-probe every 24h or on failure)

2. Runtime selection
   ├─► Orchestrator requests chat for role X
   ├─► Router selects provider for role X
   ├─► Check capability cache
   ├─► Adapt request to provider dialect
   ├─► Send request
   └─► Normalize response to unified format
```

### 1.7 Implementation Tasks

| Task | File(s) | Priority | Dependencies |
|------|---------|----------|--------------|
| Base adapter interface | `core/adapters/base.py` | P0 | None |
| OpenAI-compatible adapter | `core/adapters/openai.py` | P0 | Base adapter |
| Anthropic adapter | `core/adapters/anthropic.py` | P1 | Base adapter |
| Ollama adapter | `core/adapters/ollama.py` | P0 | OpenAI adapter |
| Capability negotiator | `core/adapters/negotiator.py` | P0 | Base adapter |
| Role router | `core/adapters/router.py` | P0 | Capability negotiator |
| Cost tracker | `core/adapters/cost_tracker.py` | P1 | Base adapter |
| Fallback chain | `core/adapters/fallback.py` | P1 | Role router |
| Unit tests | `tests/test_adapters.py` | P1 | All adapters |

---

