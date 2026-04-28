"""Email module - IMAP/SMTP integration."""

from __future__ import annotations

from core.email.client import EmailClient
from core.email.search import EmailSearch
from core.email.send import EmailSender

__all__ = [
    "EmailClient",
    "EmailSearch",
    "EmailSender",
]
