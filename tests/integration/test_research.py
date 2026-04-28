"""Integration tests for research tools."""

import pytest


async def test_arxiv():
    """Test arXiv client."""
    from core.research.arxiv import ArxivClient
    client = ArxivClient()
    assert client is not None


async def test_polymarket():
    """Test Polymarket client."""
    from core.research.polymarket import PolymarketClient
    client = PolymarketClient()
    assert client is not None


async def test_rss():
    """Test RSS monitor."""
    from core.research.rss import RSSMonitor
    monitor = RSSMonitor()
    assert monitor is not None


async def test_blogwatcher():
    """Test blog watcher."""
    from core.research.blogwatcher import BlogWatcher
    watcher = BlogWatcher()
    assert watcher is not None
