"""Browser automation module for noman-cli.

Provides Playwright-based browser automation with persistent contexts,
network interception, DOM snapshotting, and sandboxing.

Usage:
    from core.browser import BrowserEngine, BrowserSession

    engine = BrowserEngine()
    session = await engine.start(headless=True)
    await session.navigate("https://example.com")
    snapshot = await session.snapshot()
    screenshot = await session.screenshot()
    await engine.stop()
"""

from __future__ import annotations

from core.browser.engine import BrowserEngine, BrowserConfig
from core.browser.session import BrowserSession
from core.browser.snapshot import Snapshot, SnapshotNode, SnapshotOptions
from core.browser.interceptor import NetworkInterceptor, NetworkRequest, NetworkResponse
from core.browser.sandbox import BrowserSandbox, SandboxConfig

__all__ = [
    "BrowserEngine",
    "BrowserConfig",
    "BrowserSession",
    "Snapshot",
    "SnapshotNode",
    "SnapshotOptions",
    "NetworkInterceptor",
    "NetworkRequest",
    "NetworkResponse",
    "BrowserSandbox",
    "SandboxConfig",
]
