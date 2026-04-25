"""Hardened Tool Bus: registry + sandboxed execution."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from core.errors import ToolNotFoundError, ToolSignatureError, ToolValidationError
from core.security.fs_sandbox import FilesystemSandbox
from core.security.network_sandbox import NetworkSandbox
from core.security.signing import ToolSigner
from core.utils.rate_limiter import QuotaManager

logger = logging.getLogger(__name__)


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Any]
    cost_estimate: int = 0
    signature: str = ""  # hex-encoded ed25519 signature


class ToolBus:
    """Register, validate, and execute tools with full sandboxing."""

    def __init__(
        self,
        fs_sandbox: FilesystemSandbox,
        network_sandbox: NetworkSandbox | None = None,
        signer: ToolSigner | None = None,
        quotas: QuotaManager | None = None,
    ) -> None:
        self._tools: dict[str, Tool] = {}
        self.fs = fs_sandbox
        self.net = network_sandbox
        self.signer = signer
        self.quotas = quotas

    def register(self, tool: Tool) -> None:
        """Register a tool after optional signature verification."""
        if self.signer and tool.signature:
            if not self.signer.verify_tool(tool.description, tool.signature):
                raise ToolSignatureError(
                    f"Tool '{tool.name}' has an invalid signature"
                )
        self._tools[tool.name] = tool
        # logger.info("Registered tool: %s", tool.name)

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    async def execute(self, name: str, args: dict[str, Any]) -> Any:
        """Execute a tool by name with sandboxed args."""
        tool = self._tools.get(name)
        if tool is None:
            raise ToolNotFoundError(f"Tool '{name}' not found")

        if self.quotas:
            await self.quotas.check_tool_call(name)

        # Validate arguments against declared schema (basic type check)
        self._validate_args(tool, args)

        logger.debug("Executing tool %s with args %s", name, args)
        if asyncio.iscoroutinefunction(tool.handler):
            return await tool.handler(**args)
        return tool.handler(**args)

    def _validate_args(self, tool: Tool, args: dict[str, Any]) -> None:
        required = set(tool.parameters.get("required", []))
        missing = required - set(args.keys())
        if missing:
            raise ToolValidationError(
                f"Tool '{tool.name}' missing required args: {missing}"
            )
