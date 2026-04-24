"""Model adapters."""

from core.adapters.anthropic import AnthropicAdapter
from core.adapters.base import (
    BaseAdapter,
    ChatResponse,
    Message,
    ModelCapabilities,
    ToolDefinition,
)
from core.adapters.factory import (
    AdapterRegistry,
    create_adapter,
    get_default_adapter_name,
    get_registry,
)
from core.adapters.negotiator import CapabilityNegotiator
from core.adapters.openai import OpenAIAdapter
from core.adapters.router import RoleConfig, RoleRouter, create_router

__all__ = [
    "BaseAdapter",
    "ChatResponse",
    "Message",
    "ModelCapabilities",
    "ToolDefinition",
    "OpenAIAdapter",
    "AnthropicAdapter",
    "create_adapter",
    "get_default_adapter_name",
    "AdapterRegistry",
    "get_registry",
    "CapabilityNegotiator",
    "RoleRouter",
    "RoleConfig",
    "create_router",
]
