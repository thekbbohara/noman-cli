"""Integration tests for browser automation."""

import pytest


async def test_browser_engine():
    """Test BrowserEngine."""
    from core.browser.engine import BrowserEngine
    engine = BrowserEngine()
    assert engine is not None


async def test_browser_session():
    """Test BrowserSession."""
    from core.browser.session import BrowserSession
    session = BrowserSession()
    assert session is not None


async def test_browser_snapshot():
    """Test snapshot utilities."""
    from core.browser.snapshot import extract_text_content
    assert extract_text_content is not None
