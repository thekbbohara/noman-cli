"""Workspace integration module."""

from core.workspace.gmail import GmailClient
from core.workspace.calendar import CalendarClient
from core.workspace.drive import DriveClient
from core.workspace.notion import NotionClient
from core.workspace.sheets import SheetsClient
from core.workspace.obsidian import ObsidianClient

__all__ = [
    "GmailClient",
    "CalendarClient",
    "DriveClient",
    "NotionClient",
    "SheetsClient",
    "ObsidianClient",
]
