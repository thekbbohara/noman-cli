"""Role-based adapter routing (planner/executor/critic/embedder)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from core.adapters.base import BaseAdapter, ChatResponse, Message, ModelCapabilities, ToolDefinition
from core.adapters.negotiator import CapabilityNegotiator

logger = logging.getLogger(__name__)


@dataclass
class RoleConfig:
    """Configuration for a single role."""

    adapter: BaseAdapter
    model: str = "executor"
    priority: int = 1


class RoleRouter:
    """Route requests to different adapters based on role."""

    ROLES = ("planner", "executor", "critic", "embedder")

    def __init__(self, default_adapter: BaseAdapter) -> None:
        self._default = default_adapter
        self._roles: dict[str, RoleConfig] = {}
        self._negotiator = CapabilityNegotiator()

    def configure_role(
        self,
        role: str,
        adapter: BaseAdapter,
        priority: int = 1,
    ) -> None:
        """Configure an adapter for a specific role."""
        if role not in self.ROLES:
            raise ValueError(f"Invalid role: {role}. Must be one of {self.ROLES}")
        self._roles[role] = RoleConfig(
            adapter=adapter,
            model=role,
            priority=priority,
        )
        logger.info(f"Configured {role} role with {adapter.config.get('model')}")

    def get_adapter(self, role: str | None = None) -> BaseAdapter:
        """Get adapter for role, fall back to default."""
        if role and role in self._roles:
            return self._roles[role].adapter
        return self._default

    async def chat(
        self,
        messages: list[Message],
        role: str | None = None,
        tools: list[ToolDefinition] | None = None,
        stream: bool = False,
    ) -> ChatResponse | Any:
        """Send chat to the appropriate adapter for role."""
        adapter = self.get_adapter(role)
        return await adapter.chat(messages, tools, stream)

    async def capabilities(self, role: str | None = None) -> ModelCapabilities:
        """Get capabilities for role's adapter."""
        adapter = self.get_adapter(role)
        return await self._negotiator.negotiate(adapter)

    def list_roles(self) -> list[str]:
        """List configured roles."""
        return list(self._roles.keys())

    def has_role(self, role: str) -> bool:
        """Check if role is configured."""
        return role in self._roles


@dataclass
class RouterConfig:
    """Configuration for role-based routing."""

    default_adapter: BaseAdapter
    roles: dict[str, RoleConfig] = field(default_factory=dict)


def create_router(
    adapters: list[BaseAdapter], role_mapping: dict[str, str] | None = None
) -> RoleRouter:
    """Create a RoleRouter from adapter list with optional role mapping."""
    if not adapters:
        raise ValueError("At least one adapter required")

    router = RoleRouter(adapters[0])

    if role_mapping:
        for role, model in role_mapping.items():
            for adapter in adapters:
                if adapter.config.get("model") == model:
                    router.configure_role(role, adapter)
                    break

    return router
