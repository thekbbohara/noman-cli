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
| **Token Budget Validation** | **NEW** Validate context window assumptions | Reject configs exceeding actual limits (8K-32K realistic) |

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
| **Token budget validator** | `core/adapters/token_validator.py` | **P0** | Capability negotiator |
| Unit tests | `tests/test_adapters.py` | P1 | All adapters |
| **Token budget tests** | `tests/test_token_limits.py` | **P0** | Token budget validator |

### 1.8 Token Budget Reality Check (NEW SECTION)

**Problem:** Original plans assumed 128K context windows, but reality is 8K-32K for most models.

**Solution:** Conservative limits with automatic validation:

```python
# core/adapters/token_validator.py

from dataclasses import dataclass
from typing import Optional

@dataclass
class ModelLimits:
    model_name: str
    max_context_tokens: int
    safe_margin: float = 0.8  # Use only 80% of max
    
    @property
    def usable_tokens(self) -> int:
        return int(self.max_context_tokens * self.safe_margin)

# Known model limits (conservative estimates)
MODEL_LIMITS = {
    "claude-sonnet-4-20250514": ModelLimits("claude-sonnet-4-20250514", 100000),
    "claude-3-opus-20240229": ModelLimits("claude-3-opus-20240229", 100000),
    "gpt-4-turbo-preview": ModelLimits("gpt-4-turbo-preview", 128000),
    "gpt-4-0125-preview": ModelLimits("gpt-4-0125-preview", 128000),
    "codellama:34b": ModelLimits("codellama:34b", 16000),
    "codellama:13b": ModelLimits("codellama:13b", 16000),
    "mixtral-8x7b-32768": ModelLimits("mixtral-8x7b-32768", 32000),
    "llama-2-70b": ModelLimits("llama-2-70b", 8000),
    "default": ModelLimits("default", 8000),  # Conservative fallback
}

class TokenBudgetValidator:
    """Validate token budgets against realistic model limits."""
    
    def __init__(self):
        self.limits = MODEL_LIMITS
    
    def validate_config(self, config: dict) -> tuple[bool, str]:
        """
        Validate configuration doesn't exceed token limits.
        
        Returns:
            (is_valid, error_message)
        """
        model = config.get("model", "default")
        requested_tokens = config.get("max_context_tokens", 0)
        
        # Get model limits
        limit = self.limits.get(model, self.limits["default"])
        max_allowed = limit.usable_tokens
        
        if requested_tokens > max_allowed:
            return False, (
                f"Requested {requested_tokens} tokens exceeds safe limit of {max_allowed} "
                f"for model '{model}' (max={limit.max_context_tokens}, margin={limit.safe_margin}). "
                f"Reduce context size or choose a model with larger context window."
            )
        
        # Warn if using more than 50% of limit
        if requested_tokens > max_allowed * 0.5:
            return True, (
                f"Warning: Using {requested_tokens}/{max_allowed} tokens ({requested_tokens/max_allowed:.0%}). "
                f"Consider keeping headroom for tool outputs and long responses."
            )
        
        return True, f"OK: {requested_tokens}/{max_allowed} tokens"
    
    def get_safe_limit(self, model: str) -> int:
        """Get safe token limit for a model."""
        limit = self.limits.get(model, self.limits["default"])
        return limit.usable_tokens
```

**Configuration Example:**

```toml
# user/config.toml

[[providers]]
id = "local_ollama"
type = "openai_compat"
base_url = "http://localhost:11434/v1"
model = "codellama:34b"
# Token budget validated automatically at startup
# codellama:34b has 16K limit → safe limit = 12.8K (80%)
max_context_tokens = 12000  # ✅ Valid
# max_context_tokens = 20000  # ❌ Rejected at config load
```

**Startup Validation:**

```python
# core/adapters/negotiator.py

async def probe_capabilities(self) -> dict:
    """Probe provider for capabilities and quirks."""
    # ... existing capability detection ...
    
    # NEW: Validate token budget
    validator = TokenBudgetValidator()
    is_valid, message = validator.validate_config(self.config)
    
    if not is_valid:
        raise ConfigurationError(f"Invalid token budget: {message}")
    
    self.capabilities["token_budget"] = {
        "requested": self.config.get("max_context_tokens"),
        "safe_limit": validator.get_safe_limit(self.config["model"]),
        "status": message
    }
    
    return self.capabilities
```

---

