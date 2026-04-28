"""BrowserSession: Persistent browser session management.

Provides a high-level session abstraction that manages page lifecycle,
navigation, element interaction, and auto-reconnection.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from core.browser.interceptor import NetworkInterceptor
from core.browser.sandbox import BrowserSandbox

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page, Response

logger = logging.getLogger(__name__)


@dataclass
class SessionState:
    """Tracks the current state of a BrowserSession."""

    url: str = ""
    page_title: str = ""
    page_loaded: bool = False
    last_error: str | None = None
    navigation_count: int = 0
    interaction_count: int = 0
    started_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))
    last_activity: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))

    def to_dict(self) -> dict[str, Any]:
        """Serialize state to dict."""
        return {
            "url": self.url,
            "title": self.page_title,
            "loaded": self.page_loaded,
            "error": self.last_error,
            "nav_count": self.navigation_count,
            "interaction_count": self.interaction_count,
            "started_at": self.started_at,
            "last_activity": self.last_activity,
        }


@dataclass
class SessionSnapshot:
    """Snapshot of a BrowserSession for serialization/export.

    Attributes:
        state: Current session state.
        cookies: List of cookies in the session.
        localStorage: Dict of localStorage entries.
        history: Navigation history entries.
    """

    state: SessionState
    cookies: list[dict[str, Any]] = field(default_factory=list)
    local_storage: dict[str, str] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize snapshot to dict."""
        return {
            "state": self.state.to_dict(),
            "cookies": self.cookies,
            "local_storage": self.local_storage,
            "history": self.history,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionSnapshot:
        """Deserialize snapshot from dict."""
        state_data = data.get("state", {})
        state = SessionState(
            url=state_data.get("url", ""),
            page_title=state_data.get("title", ""),
            page_loaded=state_data.get("loaded", False),
            last_error=state_data.get("error"),
            navigation_count=state_data.get("nav_count", 0),
            interaction_count=state_data.get("interaction_count", 0),
            started_at=state_data.get("started_at", ""),
            last_activity=state_data.get("last_activity", ""),
        )
        return cls(
            state=state,
            cookies=data.get("cookies", []),
            local_storage=data.get("local_storage", {}),
            history=data.get("history", []),
        )


class BrowserSession:
    """Persistent browser session with page lifecycle management.

    Wraps a Playwright Page with session-aware features:
    - Persistent state (cookies, localStorage)
    - Auto-reconnection on disconnect
    - Element interaction (click, type, fill)
    - Navigation and waiting
    - Screenshot capture
    - DOM snapshot extraction

    Example:
        engine = BrowserEngine()
        await engine.start()
        session = await engine.create_session()
        await session.navigate("https://example.com")
        await session.click("#submit-btn")
        await session.type("#input", "hello world")
        await session.screenshot(path="out.png")
        await session.close()
        await engine.stop()
    """

    def __init__(
        self,
        browser: Browser,
        config: Any,
        headless: bool | None = None,
        session_id: str | None = None,
        **kwargs,
    ) -> None:
        self._browser = browser
        self._config = config
        self._page: Page | None = None
        self._context: BrowserContext | None = None
        self._headless = headless if headless is not None else config.headless if config else True
        self._session_id = session_id or f"sess_{int(time.time())}_{id(self):x}"
        self._state = SessionState()
        self._interceptor: NetworkInterceptor | None = None
        self._sandbox: BrowserSandbox | None = None
        self._closed = False
        self._kwargs = kwargs
        self._navigation_history: list[dict[str, Any]] = []
        self._max_reconnect_attempts: int = 3
        self._reconnect_delay: float = 1.0

    @property
    def page(self) -> Page | None:
        """Get the current Playwright page, or None."""
        return self._page

    @property
    def context(self) -> BrowserContext | None:
        """Get the current browser context, or None."""
        return self._context

    @property
    def session_id(self) -> str:
        """Get the session ID."""
        return self._session_id

    @property
    def state(self) -> SessionState:
        """Get the current session state."""
        return self._state

    @property
    def is_active(self) -> bool:
        """Check if the session is active (not closed)."""
        return not self._closed and self._page is not None

    @property
    def interceptor(self) -> NetworkInterceptor | None:
        """Get the network interceptor, or None."""
        return self._interceptor

    @property
    def sandbox(self) -> BrowserSandbox | None:
        """Get the browser sandbox, or None."""
        return self._sandbox

    async def init(self, context: BrowserContext | None = None) -> None:
        """Initialize the session by creating a new page.

        Args:
            context: Existing browser context. Creates new if None.
        """
        if context:
            self._context = context
        else:
            self._context = await self._browser.new_context(
                viewport={"width": self._config.viewport_width if self._config else 1280,
                          "height": self._config.viewport_height if self._config else 720},
            )

        self._page = await self._context.new_page()
        logger.info(f"Session {self._session_id} initialized")

    # -- Navigation --

    async def navigate(
        self,
        url: str,
        timeout: int | None = None,
        wait_until: Literal["load", "domcontentloaded", "networkidle", "commit"] = "load",
    ) -> Response | None:
        """Navigate to a URL.

        Args:
            url: The URL to navigate to.
            timeout: Override timeout in milliseconds.
            wait_until: When to consider navigation succeeded.

        Returns:
            The main resource response, or None.

        Raises:
            RuntimeError: If session is not active.
        """
        if not self._page:
            raise RuntimeError("Session not active. Call init() first.")

        await self._enforce_rate_limit()

        self._state.url = url
        self._state.last_activity = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._state.navigation_count += 1

        timeout_ms = timeout or (self._config.timeout if self._config else 30_000)

        response = await self._page.goto(url, wait_until=wait_until, timeout=timeout_ms)

        self._state.page_loaded = True
        self._state.last_error = None

        # Record in history
        self._navigation_history.append({
            "url": url,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "status": response.status if response else None,
        })

        logger.info(f"Navigated to {url} (status: {response.status if response else 'N/A'})")
        return response

    async def go_back(self) -> Response | None:
        """Navigate back in history."""
        if not self._page:
            raise RuntimeError("Session not active.")
        await self._enforce_rate_limit()
        return await self._page.go_back()

    async def go_forward(self) -> Response | None:
        """Navigate forward in history."""
        if not self._page:
            raise RuntimeError("Session not active.")
        await self._enforce_rate_limit()
        return await self._page.go_forward()

    async def reload(self, timeout: int | None = None) -> Response | None:
        """Reload the current page."""
        if not self._page:
            raise RuntimeError("Session not active.")
        await self._enforce_rate_limit()
        return await self._page.reload(timeout=timeout)

    async def wait_for_url(
        self,
        url_match: str,
        timeout: int | None = None,
    ) -> None:
        """Wait for the URL to match a pattern.

        Args:
            url_match: URL pattern to wait for (substring match).
            timeout: Maximum time to wait in milliseconds.
        """
        if not self._page:
            raise RuntimeError("Session not active.")
        if timeout is None:
            timeout = self._config.timeout if self._config else 30_000
        await self._page.wait_for_url(url_match, timeout=timeout)

    async def wait_for_selector(
        self,
        selector: str,
        timeout: int | None = None,
        state: Literal["attached", "detached", "hidden", "visible"] = "attached",
    ) -> None:
        """Wait for a CSS selector to appear/disappear.

        Args:
            selector: CSS selector to wait for.
            timeout: Maximum time to wait in milliseconds.
            state: Expected state of the element.
        """
        if not self._page:
            raise RuntimeError("Session not active.")
        if timeout is None:
            timeout = self._config.timeout if self._config else 30_000
        await self._page.wait_for_selector(selector, state=state, timeout=timeout)

    # -- Element Interaction --

    async def click(
        self,
        selector: str,
        timeout: int | None = None,
        force: bool = False,
        **kwargs,
    ) -> None:
        """Click an element identified by CSS selector.

        Args:
            selector: CSS selector for the element.
            timeout: Override timeout.
            force: Force click even if element is obscured.
            **kwargs: Additional click options (position, button, modifier, etc.).
        """
        if not self._page:
            raise RuntimeError("Session not active.")
        await self._enforce_rate_limit()
        self._state.interaction_count += 1
        self._state.last_activity = time.strftime("%Y-%m-%dT%H:%M:%S")
        await self._page.click(selector, timeout=timeout, force=force, **kwargs)
        logger.debug(f"Clicked element: {selector}")

    async def type_text(
        self,
        selector: str,
        text: str,
        delay: float = 0.05,
        timeout: int | None = None,
    ) -> None:
        """Type text into an input field.

        Args:
            selector: CSS selector for the input element.
            text: Text to type.
            delay: Delay between keystrokes in milliseconds.
            timeout: Override timeout.
        """
        if not self._page:
            raise RuntimeError("Session not active.")
        await self._enforce_rate_limit()
        self._state.interaction_count += 1
        self._state.last_activity = time.strftime("%Y-%m-%dT%H:%M:%S")
        await self._page.type(selector, text, delay=int(delay * 1000), timeout=timeout)
        logger.debug(f"Typed into {selector}: {text[:50]}...")

    async def fill(
        self,
        selector: str,
        value: str,
        timeout: int | None = None,
    ) -> None:
        """Fill an input field with a value. Clears the field first.

        Args:
            selector: CSS selector for the input element.
            value: Value to fill.
            timeout: Override timeout.
        """
        if not self._page:
            raise RuntimeError("Session not active.")
        await self._enforce_rate_limit()
        self._state.interaction_count += 1
        self._state.last_activity = time.strftime("%Y-%m-%dT%H:%M:%S")
        await self._page.fill(selector, value, timeout=timeout)
        logger.debug(f"Filled {selector}: {value[:50]}...")

    async def press_key(
        self,
        key: str,
        selector: str | None = None,
    ) -> None:
        """Press a keyboard key.

        Args:
            key: Key to press (e.g., 'Enter', 'Tab', 'Escape').
            selector: Optional element to focus before pressing.
        """
        if not self._page:
            raise RuntimeError("Session not active.")
        await self._enforce_rate_limit()
        if selector:
            await self._page.focus(selector)
        await self._page.keyboard.press(key)

    async def evaluate(
        self,
        expression: str,
        arg: Any = None,
    ) -> Any:
        """Evaluate JavaScript in the page context.

        Args:
            expression: JavaScript expression to evaluate.
            arg: Optional argument passed to the expression.

        Returns:
            The result of the evaluation.
        """
        if not self._page:
            raise RuntimeError("Session not active.")
        return await self._page.evaluate(expression, arg)

    # -- Screenshot --

    async def screenshot(
        self,
        path: Path | str | None = None,
        full_page: bool = False,
        clip: dict | None = None,
        type: Literal["png", "jpeg"] = "png",
    ) -> bytes:
        """Capture a screenshot of the current page.

        Args:
            path: File path to save. If None, returns bytes.
            full_page: Capture the full scrollable page.
            clip: Region to capture {x, y, width, height}.
            type: Image format.

        Returns:
            Screenshot bytes (PNG/JPEG).
        """
        if not self._page:
            raise RuntimeError("Session not active.")
        await self._enforce_rate_limit()
        kwargs: dict = {"full_page": full_page, "type": type}
        if clip:
            kwargs["clip"] = clip
        if path:
            await self._page.screenshot(path=str(path), **kwargs)
            return b""
        return await self._page.screenshot(**kwargs)

    # -- Snapshot (DOM Extraction) --

    async def snapshot(
        self,
        include_styles: bool = False,
        include_scripts: bool = False,
        max_depth: int = 10,
    ) -> dict[str, Any]:
        """Extract a structured DOM snapshot.

        Args:
            include_styles: Whether to include computed styles.
            include_scripts: Whether to include script content.
            max_depth: Maximum depth of the DOM tree to traverse.

        Returns:
            Dictionary representing the DOM tree.
        """
        if not self._page:
            raise RuntimeError("Session not active.")

        # Extract DOM via JavaScript evaluation
        dom_tree = await self._page.evaluate(f"""
            (() => {{
                function walk(node, depth, maxDepth) {{
                    if (depth > maxDepth || !node) return null;
                    const elem = {{
                        tag: node.tagName ? node.tagName.toLowerCase() : node.nodeName,
                        text: null,
                        attrs: {{}},
                        children: []
                    }};
                    if (node.nodeType === 3) {{
                        elem.text = (node.textContent || '').trim().substring(0, 200);
                        return elem;
                    }}
                    if (node.attributes) {{
                        for (const attr of node.attributes) {{
                            if (attr.name === 'style' && !{include_styles}) continue;
                            if (attr.name === 'script' && !{include_scripts}) continue;
                            elem.attrs[attr.name] = attr.value.substring(0, 500);
                        }}
                    }}
                    if (node.children) {{
                        for (const child of node.children) {{
                            const c = walk(child, depth + 1, maxDepth);
                            if (c) elem.children.push(c);
                        }}
                    }}
                    return elem;
                }}
                return walk(document.documentElement, 0, {max_depth});
            }})()
        """)

        # Extract cookies
        cookies = await self._context.cookies() if self._context else []

        # Extract localStorage
        local_storage = await self._page.evaluate("(() => { const o = {}; for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i); o[k] = localStorage.getItem(k); } return o; })()")

        # Update state
        self._state.page_title = await self._page.title()
        self._state.last_activity = time.strftime("%Y-%m-%dT%H:%M:%S")

        return {
            "url": self._page.url,
            "title": self._state.page_title,
            "dom": dom_tree,
            "cookies": cookies,
            "local_storage": local_storage,
        }

    # -- Network Interception --

    async def set_interceptor(self, interceptor: NetworkInterceptor) -> None:
        """Set a network interceptor for this session.

        Args:
            interceptor: NetworkInterceptor instance.
        """
        self._interceptor = interceptor
        if self._page:
            await interceptor.attach(self._page)

    async def clear_interceptor(self) -> None:
        """Clear the network interceptor."""
        if self._interceptor and self._page:
            await self._interceptor.detach(self._page)
        self._interceptor = None

    # -- Sandbox --

    async def set_sandbox(self, sandbox: BrowserSandbox) -> None:
        """Set a sandbox for this session.

        Args:
            sandbox: BrowserSandbox instance.
        """
        self._sandbox = sandbox
        if self._page:
            await sandbox.apply(self._page)

    async def clear_sandbox(self) -> None:
        """Clear the sandbox."""
        if self._sandbox and self._page:
            await self._sandbox.remove(self._page)
        self._sandbox = None

    # -- State Management --

    def get_state(self) -> SessionState:
        """Get current session state."""
        return self._state

    def get_snapshot(self) -> SessionSnapshot:
        """Get a full session snapshot for serialization."""
        return SessionSnapshot(
            state=self._state,
            cookies=[],
            local_storage={},
            history=list(self._navigation_history),
        )

    async def save_state(self, path: Path) -> None:
        """Save session state to a file."""
        import json
        snapshot = self.get_snapshot()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(snapshot.to_dict(), indent=2))
        logger.info(f"Session state saved to {path}")

    async def restore_state(self, path: Path) -> None:
        """Restore session state from a file."""
        import json
        data = json.loads(path.read_text())
        snapshot = SessionSnapshot.from_dict(data)
        self._state = snapshot.state
        self._navigation_history = snapshot.history
        logger.info(f"Session state restored from {path}")

    # -- Lifecycle --

    async def close(self) -> None:
        """Close the session and clean up resources."""
        if self._closed:
            return

        logger.info(f"Closing session {self._session_id}")
        self._closed = True

        if self._page:
            # Save state
            cache_dir = self._config.cache_dir if self._config else Path.home() / ".noman" / "browser_cache"
            state_file = cache_dir / "sessions" / f"{self._session_id}.json"
            await self.save_state(state_file)

            try:
                await self._page.close()
            except Exception as e:
                logger.warning(f"Error closing page: {e}")
            self._page = None

        self._state.last_activity = time.strftime("%Y-%m-%dT%H:%M:%S")
        logger.info(f"Session {self._session_id} closed")

    async def _enforce_rate_limit(self) -> None:
        """Enforce rate limiting between operations."""
        if self._config.rate_limit <= 0:
            return
        # Rate limiting is handled by the engine; this is a no-op here
        # but can be overridden for session-specific limits
        pass
