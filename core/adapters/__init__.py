"""Model adapters."""

from core.adapters.anthropic import AnthropicAdapter
from core.adapters.base import (
    BaseAdapter,
    ChatResponse,
    Message,
    ModelCapabilities,
    ToolDefinition,
)
from core.adapters.custom import CustomAdapter
from core.adapters.dashscope import DashScopeAdapter
from core.adapters.deepseek import DeepSeekAdapter
from core.adapters.factory import (
    ADAPTER_CLASSES,
    AdapterRegistry,
    create_adapter,
    get_default_adapter_name,
    get_registry,
    get_supported_providers,
)
from core.adapters.gemini import GeminiAdapter
from core.adapters.glm import GLMAdapter
from core.adapters.huggingface import HuggingFaceAdapter
from core.adapters.kimi import KimiAdapter
from core.adapters.minimax import MiniMaxAdapter
from core.adapters.minimax_cn import MiniMaxCNAdapter
from core.adapters.mistral import MistralAdapter
from core.adapters.negotiator import CapabilityNegotiator
from core.adapters.nvidia import NvidiaAdapter
from core.adapters.openai import OpenAIAdapter
from core.adapters.perplexity import PerplexityAdapter
from core.adapters.router import RoleConfig, RoleRouter, create_router
from core.adapters.sambanova import SambaNovaAdapter
from core.adapters.together import TogetherAdapter
from core.adapters.voyage import VoyageAdapter
from core.adapters.xai import XAIAdapter

__all__ = [
    # Base types
    "BaseAdapter",
    "ChatResponse",
    "Message",
    "ModelCapabilities",
    "ToolDefinition",
    # Adapter classes
    "OpenAIAdapter",
    "AnthropicAdapter",
    "GeminiAdapter",
    "DeepSeekAdapter",
    "XAIAdapter",
    "HuggingFaceAdapter",
    "KimiAdapter",
    "MiniMaxAdapter",
    "MiniMaxCNAdapter",
    "DashScopeAdapter",
    "GLMAdapter",
    "MistralAdapter",
    "TogetherAdapter",
    "SambaNovaAdapter",
    "NvidiaAdapter",
    "VoyageAdapter",
    "PerplexityAdapter",
    "CustomAdapter",
    # Factory
    "create_adapter",
    "get_default_adapter_name",
    "get_registry",
    "AdapterRegistry",
    "get_supported_providers",
    "ADAPTER_CLASSES",
    # Router
    "CapabilityNegotiator",
    "RoleRouter",
    "RoleConfig",
    "create_router",
]
