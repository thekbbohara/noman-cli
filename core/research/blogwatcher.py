"""Blog monitoring for tracking updates to blogs and websites.

Monitors blogs for new posts and content changes:
    - Blog feed discovery and monitoring
    - Content change detection
    - Keyword-based alerting
    - Historical tracking

Configuration (in ~/.noman/config.toml):
    [research.blogwatcher]
    check_interval = 7200  # seconds
    timeout = 30
    max_items = 20
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)


@dataclass
class BlogEntry:
    """A blog post entry."""
    title: str
    url: str
    summary: str = ""
    author: str = ""
    published: str = ""
    updated: str = ""
    feed_title: str = ""
    feed_url: str = ""
    content_hash: str = ""
    categories: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        date_str = self.published or "unknown date"
        return f"[{self.feed_title}] {self.title} ({date_str})"


@dataclass
class BlogMonitor:
    """Configuration for monitoring a single blog."""
    url: str
    title: str = ""
    feed_url: str = ""
    enabled: bool = True
    last_checked: str = ""
    check_interval: int = 7200  # seconds
    max_items: int = 20
    filter_keywords: list[str] = field(default_factory=list)
    excluded_keywords: list[str] = field(default_factory=list)
    known_hashes: set[str] = field(default_factory=set)

    def is_expired(self) -> bool:
        """Check if the blog needs to be re-checked."""
        if not self.last_checked:
            return True
        try:
            last = datetime.fromisoformat(self.last_checked.replace("Z", "+00:00"))
            return (datetime.now(timezone.utc) - last).total_seconds() > self.check_interval
        except (ValueError, AttributeError):
            return True


class BlogWatcher:
    """Blog monitoring for tracking updates.

    Usage:
        watcher = BlogWatcher()
        watcher.add_blog("https://blog.example.com")
        updates = await watcher.check_all()

        # Or with custom settings
        watcher.add_blog(
            "https://blog.example.com",
            check_interval=3600,
            filter_keywords=["python", "AI"],
        )
    """

    def __init__(
        self,
        timeout: float = 30.0,
        max_items: int = 20,
        config: dict[str, Any] | None = None,
    ) -> None:
        """Initialize blog watcher.

        Args:
            timeout: HTTP request timeout.
            max_items: Max items per blog.
            config: Configuration from config.toml [research.blogwatcher] section.
        """
        self._config = config or {}
        self._timeout = self._config.get("timeout", timeout)
        self._max_items = self._config.get("max_items", max_items)
        self._blogs: list[BlogMonitor] = []
        self._blog_cache: dict[str, BlogMonitor] = {}

    def add_blog(
        self,
        url: str,
        title: str = "",
        check_interval: int | None = None,
        filter_keywords: list[str] | None = None,
        excluded_keywords: list[str] | None = None,
        feed_url: str | None = None,
    ) -> BlogMonitor:
        """Add a blog to monitor.

        Args:
            url: Blog URL.
            title: Optional title.
            check_interval: Check interval in seconds.
            filter_keywords: Keywords to filter posts.
            excluded_keywords: Keywords to exclude.
            feed_url: RSS feed URL. If None, auto-discovered.

        Returns:
            The created BlogMonitor object.
        """
        monitor = BlogMonitor(
            url=url,
            title=title or url,
            feed_url=feed_url or "",
            check_interval=check_interval or 7200,
            max_items=self._max_items,
            filter_keywords=filter_keywords or [],
            excluded_keywords=excluded_keywords or [],
        )
        self._blogs.append(monitor)
        self._blog_cache[url] = monitor
        return monitor

    def add_blogs(
        self,
        urls: list[str],
        **kwargs: Any,
    ) -> list[BlogMonitor]:
        """Add multiple blogs."""
        return [self.add_blog(url, **kwargs) for url in urls]

    def remove_blog(self, url: str) -> bool:
        """Remove a blog from monitoring."""
        if url in self._blog_cache:
            del self._blog_cache[url]
            self._blogs = [b for b in self._blogs if b.url != url]
            return True
        return False

    def list_blogs(self) -> list[BlogMonitor]:
        """List all monitored blogs."""
        return list(self._blogs)

    async def check(
        self,
        blog_urls: list[str] | None = None,
    ) -> dict[str, list[BlogEntry]]:
        """Check blogs for new entries.

        Args:
            blog_urls: Specific blogs to check. If None, all blogs.

        Returns:
            Dict mapping blog URL to list of new BlogEntry objects.
        """
        urls = blog_urls if blog_urls else [b.url for b in self._blogs]
        results: dict[str, list[BlogEntry]] = {}

        for url in urls:
            blog = self._blog_cache.get(url)
            if not blog:
                continue

            entries = await self._fetch_blog(url, blog)
            if entries:
                results[url] = entries
                blog.last_checked = datetime.now(timezone.utc).isoformat()

        return results

    async def check_all(self) -> dict[str, list[BlogEntry]]:
        """Check all configured blogs."""
        return await self.check()

    async def check_expired(self) -> dict[str, list[BlogEntry]]:
        """Check only blogs that are due for a refresh."""
        urls = [b.url for b in self._blogs if b.is_expired()]
        return await self.check(urls) if urls else {}

    async def _fetch_blog(self, url: str, blog: BlogMonitor) -> list[BlogEntry]:
        """Fetch blog content and detect new entries."""
        headers = {
            "User-Agent": "noman-cli/1.0",
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/html, */*",
        }

        # Use feed URL if available
        fetch_url = blog.feed_url or url

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(fetch_url, headers=headers)

                if resp.status_code == 304:
                    return []

                if resp.status_code != 200:
                    logger.warning(f"Blog fetch failed {resp.status_code}: {url}")
                    return []

                content_type = resp.headers.get("content-type", "")
                if "xml" in content_type or "rss" in content_type or "atom" in content_type:
                    # It's a feed - parse it
                    return self._parse_feed(resp.text, blog)
                else:
                    # HTML page - try to find feed links
                    feed_entries = await self._discover_and_parse_feeds(resp.text, blog)
                    return feed_entries

        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch blog {url}: {e}")
            return []

    def _parse_feed(self, xml_text: str, blog: BlogMonitor) -> list[BlogEntry]:
        """Parse an RSS/Atom feed."""
        import xml.etree.ElementTree as ET

        entries: list[BlogEntry] = []
        try:
            root = ET.fromstring(xml_text)
            title_el = root.find(".//title")
            blog_title = title_el.text if title_el is not None else blog.title
            blog.title = blog_title

            if root.tag.endswith("}feed"):
                # Atom feed
                for entry in root.findall("{http://www.w3.org/2005/Atom}entry"):
                    title_el = entry.find("{http://www.w3.org/2005/Atom}title")
                    link_el = entry.find("{http://www.w3.org/2005/Atom}link")
                    summary_el = entry.find("{http://www.w3.org/2005/Atom}summary")
                    updated_el = entry.find("{http://www.w3.org/2005/Atom}updated")
                    author_el = entry.find("{http://www.w3.org/2005/Atom}author")

                    author = ""
                    if author_el is not None:
                        name_el = author_el.find("{http://www.w3.org/2005/Atom}name")
                        if name_el is not None:
                            author = name_el.text or ""

                    entry_hash = hashlib.sha256(
                        f"{blog.url}:{entry.find('{http://www.w3.org/2005/Atom}id').text}".encode()
                    ).hexdigest()[:16]

                    if entry_hash not in blog.known_hashes:
                        blog.known_hashes.add(entry_hash)
                        entries.append(BlogEntry(
                            title=title_el.text if title_el is not None else "",
                            url=link_el.get("href", "") if link_el is not None else "",
                            summary=summary_el.text if summary_el is not None else "",
                            author=author,
                            published=updated_el.text if updated_el is not None else "",
                            feed_title=blog_title,
                            feed_url=blog.url,
                            content_hash=entry_hash,
                        ))
            else:
                # RSS feed
                for item_el in root.findall("item"):
                    title_el = item_el.find("title")
                    link_el = item_el.find("link")
                    desc_el = item_el.find("description")
                    pubdate_el = item_el.find("pubDate")
                    guid_el = item_el.find("guid")

                    guid = guid_el.text if guid_el is not None else ""
                    entry_hash = hashlib.sha256(f"{blog.url}:{guid}".encode()).hexdigest()[:16]

                    if entry_hash not in blog.known_hashes:
                        blog.known_hashes.add(entry_hash)
                        entries.append(BlogEntry(
                            title=title_el.text if title_el is not None else "",
                            url=link_el.text if link_el is not None else "",
                            summary=desc_el.text if desc_el is not None else "",
                            published=pubdate_el.text if pubdate_el is not None else "",
                            feed_title=blog_title,
                            feed_url=blog.url,
                            content_hash=entry_hash,
                        ))
        except ET.ParseError as e:
            logger.error(f"Failed to parse feed: {e}")

        return entries[:blog.max_items]

    async def _discover_and_parse_feeds(
        self,
        html_content: str,
        blog: BlogMonitor,
    ) -> list[BlogEntry]:
        """Discover RSS feeds from an HTML page."""
        import re

        feed_urls = re.findall(
            r'<link[^>]+type=["\']application/(rss|atom)\+xml["\'][^>]+href=["\']([^"\']+)["\'][^>]*>',
            html_content,
        )
        feed_urls += re.findall(
            r'<link[^>]+rel=["\']alternate["\'][^>]+type=["\']application/(rss|atom)\+xml["\'][^>]+href=["\']([^"\']+)["\'][^>]*>',
            html_content,
        )

        entries: list[BlogEntry] = []
        for _, feed_url in feed_urls:
            if feed_url.startswith("//"):
                feed_url = "https:" + feed_url
            elif not urlparse(feed_url).scheme:
                base = urlparse(blog.url)
                feed_url = f"{base.scheme}://{base.netloc}{feed_url}"

            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.get(feed_url)
                    if resp.status_code == 200:
                        entries.extend(self._parse_feed(resp.text, blog))
            except httpx.HTTPError:
                pass

        return entries
