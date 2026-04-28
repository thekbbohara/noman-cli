"""TUI extensions for noman-cli.

TUI (Textual UI) extensions providing slash commands, status bar,
command palette, command history, and plugin system.

Modules:
    commands: Slash command registry and handlers
    statusbar: Enhanced status bar widget
    palette: Enhanced command palette
    history: Command history manager
    plugins: Plugin system for TUI extensions

Usage (programmatic):
    from core.tui_extensions import (
        SlashCommandRegistry,
        EnhancedStatusBar,
        EnhancedCommandPalette,
        CommandHistory,
        PluginManager,
    )

    # Register commands
    registry = SlashCommandRegistry()
    registry.register("/model", handler_fn, "Switch model")

    # Use command history
    history = CommandHistory()
    history.add("my command")
    results = history.search("my")

    # Use plugins
    manager = PluginManager()
    manager.load_plugin("my_plugin")
"""

from __future__ import annotations

from core.tui_extensions.commands import SlashCommand, SlashCommandRegistry
from core.tui_extensions.history import CommandHistory
from core.tui_extensions.palette import EnhancedCommandPalette
from core.tui_extensions.plugins import Plugin, PluginManager, PluginState
from core.tui_extensions.statusbar import EnhancedStatusBar

__all__ = [
    "CommandHistory",
    "EnhancedCommandPalette",
    "EnhancedStatusBar",
    "Plugin",
    "PluginManager",
    "PluginState",
    "SlashCommand",
    "SlashCommandRegistry",
]
