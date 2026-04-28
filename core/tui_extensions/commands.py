"""Slash command registry and handler system.

Provides a registry for slash commands with:
    - Command registration with descriptions
    - Argument parsing
    - Async/sync handler support
    - Command completion
    - Help generation

CLI commands supported:
    /model       — Switch LLM provider
    /reset       — Reset current session
    /help        — Show help
    /status      — Show status
    /skill       — Manage skills
    /cron        — Manage cron jobs
    /gateway     — Manage gateways
    /profile     — Manage profiles
    /browser     — Browser controls
    /voice       — Voice controls
    /vision      — Vision controls
    /image       — Image generation
    /github      — GitHub operations
    /hass        — Home Assistant controls
    /spotify     — Spotify controls
    /gmail       — Gmail operations
    /pdf         — PDF operations
    /arxiv       — arXiv operations
    /rss         — RSS operations
    /config      — Configuration
    /insights    — Code insights
    /save        — Save output
    /history     — Command history
    /compress    — Compress session
    /rollback    — Rollback changes
    /background  — Background jobs
    /queue       — Task queue
    /branch      — Git branch
    /btw         — Bit-width comparison
    /fast        — Fast mode
    /tools       — Tool listing
    /plugins     — Plugin management
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

HandlerFn = Callable[..., Any]
AsyncHandlerFn = Callable[..., Any]


@dataclass
class SlashCommand:
    """A registered slash command."""
    name: str
    handler: HandlerFn | AsyncHandlerFn
    description: str
    params: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    category: str = "general"
    enabled: bool = True

    @property
    def trigger(self) -> str:
        """Get the command trigger string."""
        return f"/{self.name}"

    def __str__(self) -> str:
        return f"{self.trigger} — {self.description}"


class SlashCommandRegistry:
    """Registry for slash commands.

    Manages command registration, lookup, execution, and help generation.

    Usage:
        registry = SlashCommandRegistry()

        # Register commands
        registry.register("/model", switch_model, "Switch LLM provider")
        registry.register("/reset", reset_session, "Reset session")

        # Execute commands
        result = await registry.execute("/model claude-3-opus")

        # List commands
        commands = registry.list(category="general")

        # Get help
        help_text = registry.help()
    """

    def __init__(self) -> None:
        """Initialize the command registry."""
        self._commands: dict[str, SlashCommand] = {}
        self._aliases: dict[str, str] = {}  # alias -> command name
        self._categories: dict[str, list[str]] = {}  # category -> [command names]

    def register(
        self,
        name: str,
        handler: HandlerFn | AsyncHandlerFn,
        description: str,
        params: list[str] | None = None,
        aliases: list[str] | None = None,
        category: str = "general",
        enabled: bool = True,
    ) -> SlashCommand:
        """Register a slash command.

        Args:
            name: Command name (without leading slash).
            handler: Handler function (sync or async).
            description: Command description.
            params: Parameter names for help display.
            aliases: Alternative command names.
            category: Command category.
            enabled: Whether the command is enabled.

        Returns:
            The registered SlashCommand.
        """
        cmd = SlashCommand(
            name=name,
            handler=handler,
            description=description,
            params=params or [],
            aliases=aliases or [],
            category=category,
            enabled=enabled,
        )
        self._commands[f"/{name}"] = cmd

        # Register aliases
        for alias in (aliases or []):
            self._aliases[f"/{alias}"] = f"/{name}"

        # Track categories
        if category not in self._categories:
            self._categories[category] = []
        if f"/{name}" not in self._categories[category]:
            self._categories[category].append(f"/{name}")

        logger.debug(f"Registered command: /{name} -> {description}")
        return cmd

    def unregister(self, name: str) -> bool:
        """Unregister a command.

        Args:
            name: Command name (with or without leading slash).

        Returns:
            True if the command was unregistered.
        """
        key = f"/{name}" if not name.startswith("/") else name
        if key in self._commands:
            del self._commands[key]
            # Remove aliases
            aliases_to_remove = [
                k for k, v in self._aliases.items() if v == key
            ]
            for alias in aliases_to_remove:
                del self._aliases[alias]
            return True
        return False

    async def execute(self, command: str, *args: Any, **kwargs: Any) -> Any:
        """Execute a slash command.

        Args:
            command: Command string (e.g., "/model claude-3-opus").
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.

        Returns:
            Handler return value.

        Raises:
            KeyError: If the command is not registered.
        """
        # Parse command
        parts = command.strip().split()
        if not parts:
            raise ValueError("Empty command")

        cmd_name = parts[0]
        params = parts[1:]

        # Resolve alias
        if cmd_name in self._aliases:
            cmd_name = self._aliases[cmd_name]

        if cmd_name not in self._commands:
            raise KeyError(f"Unknown command: {cmd_name}")

        cmd = self._commands[cmd_name]
        if not cmd.enabled:
            raise ValueError(f"Command disabled: {cmd_name}")

        # Call handler
        if asyncio.iscoroutinefunction(cmd.handler):
            return await cmd.handler(*params, **kwargs)
        else:
            return cmd.handler(*params, **kwargs)

    def get(self, name: str) -> SlashCommand | None:
        """Get a command by name.

        Args:
            name: Command name (with or without leading slash).

        Returns:
            SlashCommand or None.
        """
        key = f"/{name}" if not name.startswith("/") else name
        if key in self._commands:
            return self._commands[key]
        # Check aliases
        if key in self._aliases:
            return self._commands[self._aliases[key]]
        return None

    def list(self, category: str | None = None) -> list[SlashCommand]:
        """List registered commands.

        Args:
            category: Filter by category. If None, lists all.

        Returns:
            List of SlashCommand objects.
        """
        if category:
            names = self._categories.get(category, [])
            return [self._commands[n] for n in names if n in self._commands]
        return list(self._commands.values())

    def search(self, query: str) -> list[SlashCommand]:
        """Search commands by query.

        Args:
            query: Search text (matches name, description, aliases).

        Returns:
            List of matching SlashCommand objects.
        """
        query_lower = query.lower()
        results = []
        for cmd in self._commands.values():
            if (
                query_lower in cmd.name.lower()
                or query_lower in cmd.description.lower()
                or any(query_lower in a.lower() for a in cmd.aliases)
            ):
                results.append(cmd)
        return results

    def help(self, command: str | None = None) -> str:
        """Generate help text.

        Args:
            command: Specific command for detailed help. If None, shows overview.

        Returns:
            Help text string.
        """
        if command:
            cmd = self.get(command)
            if not cmd:
                return f"Unknown command: {command}"
            params_str = " ".join(f"<{p}>" for p in cmd.params)
            aliases_str = (
                f"  Aliases: {', '.join(f'/{a}' for a in cmd.aliases)}\n"
                if cmd.aliases else ""
            )
            return (
                f"Command: /{cmd.name}\n"
                f"  Description: {cmd.description}\n"
                f"  Parameters: {params_str}\n"
                f"  Category: {cmd.category}\n"
                f"  Enabled: {cmd.enabled}\n"
                f"{aliases_str}"
            )

        # Overview
        lines = ["Available slash commands:\n"]
        categories = {}
        for cmd in self._commands.values():
            if cmd.category not in categories:
                categories[cmd.category] = []
            categories[cmd.category].append(cmd)

        for category in sorted(categories.keys()):
            lines.append(f"\n  [{category}]")
            for cmd in categories[category]:
                params_str = " ".join(f"<{p}>" for p in cmd.params)
                lines.append(f"    {cmd.trigger:15s} — {cmd.description} {params_str}")

        lines.append("\n  Type /help <command> for details on a specific command.")
        return "\n".join(lines)

    def get_categories(self) -> list[str]:
        """List all command categories."""
        return sorted(self._categories.keys())
