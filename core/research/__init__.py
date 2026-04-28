"""Research module."""

from __future__ import annotations

from core.research.arxiv import ArxivClient
from core.research.polymarket import PolymarketClient
from core.research.rss import RSSMonitor
from core.research.blogwatcher import BlogWatcher
from core.research.paper import PaperUtils

__all__ = [
    "ArxivClient",
    "PolymarketClient",
    "RSSMonitor",
    "BlogWatcher",
    "PaperUtils",
]
