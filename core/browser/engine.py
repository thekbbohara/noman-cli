"""BrowserEngine: Playwright-based browser automation engine.

Manages browser lifecycle (start/stop), context creation, and provides
a high-level interface for browser automation including headless/headed
modes, persistent contexts, screenshot capture, and rate limiting.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright
    from playwright.async_api import Page as PlaywrightPage

    from core.browser.session import BrowserSession

logger = logging.getLogger(__name__)


@dataclass
class BrowserConfig:
    """Configuration for the BrowserEngine."""

    # Browser mode: headless or headed
    headless: bool = True

    # Browser type: chromium, firefox, webkit
    browser_type: Literal["chromium", "firefox", "webkit"] = "chromium"

    # Persistent context storage (for cookies, localStorage persistence)
    storage_state_path: Path | None = None

    # User agent string
    user_agent: str | None = None

    # Viewport dimensions
    viewport_width: int = 1280
    viewport_height: int = 720

    # Network throttling (optional)
    offline: bool = False

    # Proxy settings
    proxy: dict[str, str] | None = None

    # Slowdown factor between operations
    slow_mo: int = 0

    # Maximum time for navigation (ms)
    timeout: int = 30_000

    # Maximum time for network requests (ms)
    api_timeout: int = 30_000

    # Rate limiting settings
    rate_limit: float = 0.0  # seconds between operations; 0 = no limit
    rate_limit_window: int = 60  # sliding window in seconds

    # Sandbox configuration
    sandbox_enabled: bool = False

    # Cache directory for persistent contexts
    cache_dir: Path = field(default_factory=lambda: Path.home() / ".noman" / "browser_cache")


class BrowserEngine:
    """Playwright-based browser automation engine.

    Manages the full browser lifecycle:
    - Initialize Playwright and browser instance
    - Create and manage browser contexts (incognito or persistent)
    - Handle automatic reconnection on disconnect
    - Enforce rate limiting to avoid detection

    Example:
        engine = BrowserEngine()
        await engine.start(headless=True)
        # ... use browser ...
        await engine.stop()
    """

    def __init__(self, config: BrowserConfig | None = None) -> None:
        self._config = config or BrowserConfig()
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._contexts: list[BrowserContext] = []
        self._sessions: list[BrowserSession] = []
        self._started = False
        self._rate_timestamps: list[float] = []

    @property
    def config(self) -> BrowserConfig:
        """Get the current configuration."""
        return self._config

    @property
    def is_started(self) -> bool:
        """Check if the engine has been started."""
        return self._started

    @property
    def contexts(self) -> list[BrowserContext]:
        """Get all active browser contexts."""
        return list(self._contexts)

    @property
    def sessions(self) -> list[BrowserSession]:
        """Get all active sessions."""
        return list(self._sessions)

    @property
    def rate_limit(self) -> float:
        """Get the current rate limit."""
        return self._config.rate_limit

    @rate_limit.setter
    def rate_limit(self, value: float) -> None:
        """Set the rate limit in seconds between operations."""
        self._config.rate_limit = value

    async def start(self, headless: bool | None = None) -> "BrowserEngine":
        """Start the browser engine.

        Initializes Playwright, launches the browser, and creates a default
        persistent browser context.

        Args:
            headless: Override headless mode. If None, uses config value.

        Returns:
            Self for chaining.

        Raises:
            RuntimeError: If already started.
        """
        if self._started:
            raise RuntimeError("BrowserEngine already started. Call stop() first.")

        # Apply headless override if provided
        if headless is not None:
            self._config.headless = headless

        logger.info(
            f"Starting BrowserEngine: type={self._config.browser_type}, "
            f"headless={self._config.headless}"
        )

        # Ensure cache directory exists
        self._config.cache_dir.mkdir(parents=True, exist_ok=True)

        # Initialize Playwright
        pw = await async_playwright().start()
        self._playwright = pw

        # Launch browser
        launch_kwargs: dict = {
            "headless": self._config.headless,
            "timeout": self._config.timeout,
        }

        if self._config.browser_type == "chromium":
            self._browser = await pw.chromium.launch(**launch_kwargs)
        elif self._config.browser_type == "firefox":
            self._browser = await pw.firefox.launch(**launch_kwargs)
        elif self._config.browser_type == "webkit":
            self._browser = await pw.webkit.launch(**launch_kwargs)
        else:
            raise ValueError(f"Unknown browser type: {self._config.browser_type}")

        self._started = True
        logger.info("BrowserEngine started successfully")
        return self

    async def stop(self) -> None:
        """Stop the browser engine and clean up resources.

        Closes all browser contexts and shuts down Playwright gracefully.
        """
        if not self._started:
            return

        logger.info("Stopping BrowserEngine...")
        self._started = False

        # Close all contexts
        for ctx in self._contexts:
            try:
                await ctx.close()
            except Exception as e:
                logger.warning(f"Error closing context: {e}")
        self._contexts.clear()

        # Close all sessions
        for session in self._sessions:
            try:
                await session.close()
            except Exception as e:
                logger.warning(f"Error closing session: {e}")
        self._sessions.clear()

        # Close browser
        if self._browser:
            try:
                await self._browser.close()
            except Exception as e:
                logger.warning(f"Error closing browser: {e}")
            self._browser = None

        # Stop Playwright
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception as e:
                logger.warning(f"Error stopping Playwright: {e}")
            self._playwright = None

        logger.info("BrowserEngine stopped")

    async def new_context(
        self,
        storage_state: Path | dict | None = None,
        user_agent: str | None = None,
        viewport: tuple[int, int] | None = None,
        proxy: dict[str, str] | None = None,
        offline: bool | None = None,
        **kwargs,
    ) -> BrowserContext:
        """Create a new browser context.

        Args:
            storage_state: Persistent storage for cookies and localStorage.
            user_agent: Override user agent string.
            viewport: Override viewport dimensions (width, height).
            proxy: Proxy settings.
            offline: Enable offline mode.
            **kwargs: Additional context options passed to Playwright.

        Returns:
            The new BrowserContext.

        Raises:
            RuntimeError: If engine is not started.
        """
        if not self._started or not self._browser:
            raise RuntimeError("BrowserEngine not started. Call start() first.")

        context_kwargs: dict = {
            "viewport": {"width": self._config.viewport_width, "height": self._config.viewport_height},
            "timeout": self._config.timeout,
            "api_timeout": self._config.api_timeout,
            **kwargs,
        }

        # Apply storage state for persistent context
        if storage_state:
            context_kwargs["storage_state"] = storage_state

        # Apply user agent
        ua = user_agent or self._config.user_agent
        if ua:
            context_kwargs["user_agent"] = ua

        # Apply proxy
        if proxy:
            context_kwargs["proxy"] = proxy
        elif self._config.proxy:
            context_kwargs["proxy"] = self._config.proxy

        # Apply offline mode
        if offline is not None:
            context_kwargs["offline"] = offline
        elif self._config.offline:
            context_kwargs["offline"] = True

        # Create context
        context = await self._browser.new_context(**context_kwargs)
        self._contexts.append(context)
        logger.info("New browser context created")
        return context

    async def create_session(
        self,
        context: BrowserContext | None = None,
        headless: bool | None = None,
        **kwargs,
    ) -> BrowserSession:
        """Create a new BrowserSession.

        Args:
            context: Existing browser context. Creates new if None.
            headless: Override headless mode for this session.
            **kwargs: Additional options forwarded to BrowserSession.

        Returns:
            A new BrowserSession instance.

        Raises:
            RuntimeError: If engine is not started.
        """
        if not self._started or not self._browser:
            raise RuntimeError("BrowserEngine not started. Call start() first.")

        session = BrowserSession(
            browser=self._browser,
            config=self._config,
            headless=headless,
            **kwargs,
        )
        await session.init(context=context)
        self._sessions.append(session)
        logger.info("New BrowserSession created")
        return session

    async def _enforce_rate_limit(self) -> None:
        """Enforce the configured rate limit between operations."""
        if self._config.rate_limit <= 0:
            return

        now = time.monotonic()
        window_start = now - self._config.rate_window

        # Clean old timestamps outside the window
        self._rate_timestamps = [t for t in self._rate_timestamps if t > window_start]

        if self._rate_timestamps:
            last_ts = self._rate_timestamps[-1]
            elapsed = now - last_ts
            if elapsed < self._config.rate_limit:
                wait_time = self._config.rate_limit - elapsed
                logger.debug(f"Rate limiting: waiting {wait_time:.3f}s")
                await asyncio.sleep(wait_time)

        self._rate_timestamps.append(time.monotonic())

    async def screenshot_page(
        self,
        page: "PlaywrightPage",
        path: Path | str | None = None,
        full_page: bool = False,
        clip: dict | None = None,
    ) -> bytes:
        """Take a screenshot of a page.

        Args:
            page: The Playwright page to screenshot.
            path: File path to save the screenshot. If None, returns bytes.
            full_page: Whether to capture the full scrollable page.
            clip: Region to capture {x, y, width, height}.

        Returns:
            Screenshot bytes (PNG format).
        """
        await self._enforce_rate_limit()
        screenshot_kwargs: dict = {"full_page": full_page}
        if clip:
            screenshot_kwargs["clip"] = clip
        if path:
            await page.screenshot(path=str(path), **screenshot_kwargs)
        screenshot = await page.screenshot(**screenshot_kwargs)
        if path:
            return b""
        return screenshot

    async def __aenter__(self) -> "BrowserEngine":
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.stop()
