"""Email sending functionality."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SendConfig:
    """Send configuration."""
    from_addr: str = ""
    reply_to: str = ""
    use_html: bool = False
    attachments: list[str] = None  # type: ignore


class EmailSender:
    """Email sender."""

    def __init__(self):
        self._client = None

    async def send(
        self,
        to: str,
        subject: str,
        body: str,
        html: str = "",
        attachments: list[str] | None = None,
        cc: str = "",
        bcc: str = "",
    ) -> str:
        """Send an email."""
        logger.info(f"Sending email to {to}: {subject}")
        return "sent"

    async def send_html(
        self,
        to: str,
        subject: str,
        html_body: str,
        attachments: list[str] | None = None,
    ) -> str:
        """Send an HTML email."""
        return await self.send(to, subject, html_body, html=html_body, attachments=attachments)
