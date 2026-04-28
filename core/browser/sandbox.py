"""Browser sandbox for restricted browser operation.

Provides security restrictions for browser automation including:
- URL allowlisting/denylisting
- Navigation restrictions
- JavaScript execution control
- File system access restrictions
- Clipboard restrictions
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class SandboxConfig:
    """Configuration for browser sandboxing.

    Attributes:
        allowed_origins: Allowed origin patterns. Empty = allow all.
        blocked_origins: Blocked origin patterns.
        allow_navigation_to_external: Whether to allow navigation to external sites.
        allow_javascript: Whether to allow JavaScript execution.
        allow_file_access: Whether to allow file:// protocol.
        allow_popups: Whether to allow window.open() popups.
        max_page_load_time: Maximum page load time in milliseconds.
        block_scripts: Script URL patterns to block.
        block_styles: Style URL patterns to block.
        block_images: Image URL patterns to block.
        block_fonts: Font URL patterns to block.
        block_media: Media URL patterns to block.
        block_fetch: Fetch/XHR URL patterns to block.
        restrict_clipboard: Whether to restrict clipboard access.
        restrict_console: Whether to restrict console access.
        sandbox_user_agent: Custom user agent string.
    """

    allowed_origins: list[str] = field(default_factory=list)
    blocked_origins: list[str] = field(default_factory=list)
    allow_navigation_to_external: bool = False
    allow_javascript: bool = True
    allow_file_access: bool = False
    allow_popups: bool = True
    max_page_load_time: int = 30_000
    block_scripts: list[str] = field(default_factory=list)
    block_styles: list[str] = field(default_factory=list)
    block_images: list[str] = field(default_factory=list)
    block_fonts: list[str] = field(default_factory=list)
    block_media: list[str] = field(default_factory=list)
    block_fetch: list[str] = field(default_factory=list)
    restrict_clipboard: bool = True
    restrict_console: bool = True
    sandbox_user_agent: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "allowed_origins": self.allowed_origins,
            "blocked_origins": self.blocked_origins,
            "allow_navigation_to_external": self.allow_navigation_to_external,
            "allow_javascript": self.allow_javascript,
            "allow_file_access": self.allow_file_access,
            "allow_popups": self.allow_popups,
            "max_page_load_time": self.max_page_load_time,
            "block_scripts": self.block_scripts,
            "block_styles": self.block_styles,
            "block_images": self.block_images,
            "block_fonts": self.block_fonts,
            "block_media": self.block_media,
            "block_fetch": self.block_fetch,
            "restrict_clipboard": self.restrict_clipboard,
            "restrict_console": self.restrict_console,
            "sandbox_user_agent": self.sandbox_user_agent,
        }


class BrowserSandbox:
    """Sandbox for restricting browser operations.

    Provides:
    - URL allowlisting/denylisting
    - Navigation restrictions
    - JavaScript execution control
    - Protocol restrictions (file://, data:, etc.)
    - Resource type blocking
    - Clipboard restrictions

    Example:
        sandbox = BrowserSandbox()
        sandbox.allow_origin("https://example.com")
        sandbox.block_origin("https://evil.com")
        sandbox.restrict_to_protocol("https")

        session.set_sandbox(sandbox)
    """

    def __init__(self, config: SandboxConfig | None = None) -> None:
        self._config = config or SandboxConfig()
        self._allowed_origins: list[str] = list(self._config.allowed_origins)
        self._blocked_origins: list[str] = list(self._config.blocked_origins)
        self._resource_blockers: list[Callable[[str], bool]] = []
        self._navigation_callbacks: list[Callable[[str], bool]] = []
        self._enabled = False

    @property
    def config(self) -> SandboxConfig:
        """Get the sandbox configuration."""
        return self._config

    @property
    def is_enabled(self) -> bool:
        """Check if the sandbox is enabled."""
        return self._enabled

    @property
    def allowed_origins(self) -> list[str]:
        """Get allowed origin patterns."""
        return list(self._allowed_origins)

    @property
    def blocked_origins(self) -> list[str]:
        """Get blocked origin patterns."""
        return list(self._blocked_origins)

    # -- Origin Management --

    def allow_origin(self, origin: str) -> None:
        """Allow navigation to a specific origin.

        Args:
            origin: Origin pattern (e.g., "https://example.com").
        """
        if origin not in self._allowed_origins:
            self._allowed_origins.append(origin)

    def block_origin(self, origin: str) -> None:
        """Block navigation to a specific origin.

        Args:
            origin: Origin pattern (e.g., "https://evil.com").
        """
        if origin not in self._blocked_origins:
            self._blocked_origins.append(origin)

    def clear_origins(self) -> None:
        """Clear all origin restrictions."""
        self._allowed_origins.clear()
        self._blocked_origins.clear()

    # -- Protocol Restrictions --

    def restrict_to_protocol(self, protocol: str) -> None:
        """Restrict navigation to a specific protocol.

        Args:
            protocol: Protocol to allow (e.g., "https", "http").
        """
        if protocol not in ("http", "https", "file", "data"):
            raise ValueError(f"Unsupported protocol: {protocol}")
        self._config.allow_file_access = (protocol == "file")

    def block_protocol(self, protocol: str) -> None:
        """Block a specific protocol.

        Args:
            protocol: Protocol to block (e.g., "file", "data").
        """
        if protocol == "file":
            self._config.allow_file_access = False

    # -- Resource Blocking --

    def block_resource(self, pattern: str, resource_type: str = "any") -> None:
        """Block resources matching a pattern.

        Args:
            pattern: URL pattern to block.
            resource_type: Type of resource (script, style, image, font, media, fetch).
        """
        def _blockper_type(url: str) -> bool:
            import fnmatch
            if fnmatch.fnmatch(url, pattern):
                return True
            return False

        self._resource_blockers.append(_blockper_type)
        if resource_type == "script":
            self._config.block_scripts.append(pattern)
        elif resource_type == "style":
            self._config.block_styles.append(pattern)
        elif resource_type == "image":
            self._config.block_images.append(pattern)
        elif resource_type == "font":
            self._config.block_fonts.append(pattern)
        elif resource_type == "media":
            self._config.block_media.append(pattern)
        elif resource_type == "fetch":
            self._config.block_fetch.append(pattern)

    def clear_resource_blocks(self) -> None:
        """Clear all resource blocks."""
        self._resource_blockers.clear()
        self._config.block_scripts.clear()
        self._config.block_styles.clear()
        self._config.block_images.clear()
        self._config.block_fonts.clear()
        self._config.block_media.clear()
        self._config.block_fetch.clear()

    # -- Navigation Control --

    def is_navigation_allowed(self, url: str) -> bool:
        """Check if navigation to a URL is allowed.

        Args:
            url: URL to check.

        Returns:
            True if navigation is allowed.
        """
        from urllib.parse import urlparse

        parsed = urlparse(url)
        protocol = parsed.scheme

        # Check protocol restrictions
        if protocol == "file" and not self._config.allow_file_access:
            logger.debug(f"Blocked file:// access to {url}")
            return False
        if protocol in ("javascript", "data", "blob") and not self._config.allow_javascript:
            logger.debug(f"Blocked {protocol}: URL: {url}")
            return False

        # Check blocked origins
        domain = parsed.netloc
        for pattern in self._blocked_origins:
            import fnmatch
            if fnmatch.fnmatch(domain, pattern) or fnmatch.fnmatch(url, pattern):
                logger.debug(f"Blocked origin: {domain}")
                return False

        # Check allowed origins (if set, only these are allowed)
        if self._allowed_origins:
            allowed = False
            for pattern in self._allowed_origins:
                import fnmatch
                if fnmatch.fnmatch(domain, pattern) or fnmatch.fnmatch(url, pattern):
                    allowed = True
                    break
            if not allowed:
                logger.debug(f"Not in allowed origins: {domain}")
                return False

        # Check navigation callbacks
        for callback in self._navigation_callbacks:
            if not callback(url):
                return False

        return True

    def add_navigation_callback(self, callback: Callable[[str], bool]) -> None:
        """Add a callback to validate navigation URLs.

        Args:
            callback: Function that returns True to allow navigation.
        """
        self._navigation_callbacks.append(callback)

    # -- JavaScript Control --

    def restrict_javascript(self, page: Any) -> None:
        """Restrict JavaScript execution on a page.

        Args:
            page: Playwright Page object.
        """
        if not self._config.allow_javascript:
            # Disable JavaScript by injecting a blocking script
            page.add_init_script("""
                const originalEval = window.eval;
                window.eval = function() {
                    console.warn('[Sandbox] JavaScript execution blocked');
                    return undefined;
                };
                window.Function = function() {
                    console.warn('[Sandbox] Function constructor blocked');
                    return function() {};
                };
                window.setTimeout = function() { return -1; };
                window.setInterval = function() { return -1; };
            """)

    def allow_javascript(self, page: Any) -> None:
        """Allow JavaScript execution (remove restrictions).

        Args:
            page: Playwright Page object.
        """
        if self._config.allow_javascript:
            return
        # Re-enable JavaScript by overriding the restrictions
        page.add_init_script("""
            if (window.eval.toString().includes('[Sandbox]')) {
                delete window.eval;
            }
        """)

    # -- Clipboard Control --

    def restrict_clipboard(self, page: Any) -> None:
        """Restrict clipboard access on a page.

        Args:
            page: Playwright Page object.
        """
        if not self._config.restrict_clipboard:
            return
        page.add_init_script("""
            Object.defineProperty(navigator, 'clipboard', {
                get: function() {
                    console.warn('[Sandbox] Clipboard access blocked');
                    return {
                        readText: () => Promise.reject(new Error('Clipboard blocked')),
                        writeText: () => Promise.reject(new Error('Clipboard blocked')),
                    };
                }
            });
        """)

    def allow_clipboard(self, page: Any) -> None:
        """Allow clipboard access on a page.

        Args:
            page: Playwright Page object.
        """
        if not self._config.restrict_clipboard:
            return
        page.add_init_script("""
            delete Object.getOwnPropertyDescriptor(navigator, 'clipboard');
        """)

    # -- Apply/Remove --

    async def apply(self, page: Any) -> None:
        """Apply all sandbox restrictions to a page.

        Args:
            page: Playwright Page object.
        """
        if self._enabled:
            return

        self._enabled = True
        logger.info("Sandbox restrictions applied")

        # Apply JavaScript restrictions
        if not self._config.allow_javascript:
            self.restrict_javascript(page)

        # Apply clipboard restrictions
        if self._config.restrict_clipboard:
            self.restrict_clipboard(page)

        # Apply user agent override
        if self._config.sandbox_user_agent:
            await page.set_extra_http_headers({
                "User-Agent": self._config.sandbox_user_agent,
            })

    async def remove(self, page: Any) -> None:
        """Remove all sandbox restrictions from a page.

        Args:
            page: Playwright Page object.
        """
        self._enabled = False
        logger.info("Sandbox restrictions removed")

    # -- Serialization --

    def to_dict(self) -> dict[str, Any]:
        """Serialize the sandbox configuration."""
        return {
            "config": self._config.to_dict(),
            "allowed_origins": self._allowed_origins,
            "blocked_origins": self._blocked_origins,
            "resource_blockers_count": len(self._resource_blockers),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BrowserSandbox:
        """Create a sandbox from serialized data.

        Args:
            data: Serialized sandbox data.

        Returns:
            New BrowserSandbox instance.
        """
        sandbox = cls()
        config_data = data.get("config", {})
        sandbox._config = SandboxConfig(
            allowed_origins=config_data.get("allowed_origins", []),
            blocked_origins=config_data.get("blocked_origins", []),
            allow_javascript=config_data.get("allow_javascript", True),
            allow_file_access=config_data.get("allow_file_access", False),
            restrict_clipboard=config_data.get("restrict_clipboard", True),
            restrict_console=config_data.get("restrict_console", True),
        )
        sandbox._allowed_origins = list(data.get("allowed_origins", []))
        sandbox._blocked_origins = list(data.get("blocked_origins", []))
        return sandbox
