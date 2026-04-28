"""RSS/Atom feed monitoring for content updates.

Monitors RSS and Atom feeds for new items:
    - Feed discovery and parsing
    - New item detection
    - Feed filtering by keywords/categories
    - Feed aggregation across multiple sources
    - Change detection and caching

Configuration (in ~/.noman/config.toml):
    [research.rss]
    check_interval = 3600  # seconds
    max_items = 50
    timeout = 30
    filter_keywords = []
    user_agent = "noman-cli/1.0"
"""

from __future__ import annotations

import logging
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)


@dataclass
class RSSItem:
    """An item from an RSS/Atom feed."""
    title: str
    link: str
    summary: str = ""
    content: str = ""
    author: str = ""
    published: str = ""
    updated: str = ""
    categories: list[str] = field(default_factory=list)
    guid: str = ""
    enclosure: dict[str, str] = field(default_factory=dict)
    feed_title: str = ""
    feed_url: str = ""

    @property
    def pub_date(self) -> datetime | None:
        """Parse the publication date."""
        if not self.published:
            return None
        try:
            return datetime.fromisoformat(self.published.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            # Try parsing common date formats
            for fmt in [
                "%a, %d %b %Y %H:%M:%S %z",
                "%a, %d %b %Y %H:%M:%S %Z",
                "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%d %H:%M:%S",
            ]:
                try:
                    return datetime.strptime(self.published, fmt).replace(
                        tzinfo=timezone.utc
                    )
                except ValueError:
                    continue
            return None

    def is_new(self, since: datetime | None = None) -> bool:
        """Check if this item is newer than the given datetime."""
        if not since:
            return True
        pub = self.pub_date
        if not pub:
            return False
        return pub > since

    def __str__(self) -> str:
        date_str = self.published or "unknown date"
        return f"[{self.feed_title}] {self.title} ({date_str})"


@dataclass
class RSSFeed:
    """RSS/Atom feed configuration."""
    url: str
    title: str = ""
    enabled: bool = True
    last_checked: str = ""
    last_etag: str = ""
    last_modified: str = ""
    filter_keywords: list[str] = field(default_factory=list)
    excluded_keywords: list[str] = field(default_factory=list)
    max_items: int = 50
    check_interval: int = 3600  # seconds
    feed_type: str = ""  # 'rss' or 'atom'

    def is_expired(self) -> bool:
        """Check if the feed needs to be re-checked."""
        if not self.last_checked:
            return True
        try:
            last = datetime.fromisoformat(self.last_checked.replace("Z", "+00:00"))
            return (datetime.now(timezone.utc) - last).total_seconds() > self.check_interval
        except (ValueError, AttributeError):
            return True

    def passes_filter(self, item: RSSItem) -> bool:
        """Check if an item passes the feed's filter."""
        # Check excluded keywords
        text_to_check = f"{item.title} {item.summary}".lower()
        for kw in self.excluded_keywords:
            if kw.lower() in text_to_check:
                return False

        # If filter keywords are set, check if item matches
        if self.filter_keywords:
            for kw in self.filter_keywords:
                if kw.lower() in text_to_check:
                    return True
            return False

        return True

    def __str__(self) -> str:
        return f"RSSFeed(url={self.url}, title={self.title}, enabled={self.enabled})"


class RSSMonitor:
    """RSS/Atom feed monitor for detecting new content.

    Usage:
        monitor = RSSMonitor()
        monitor.add_feed("https://example.com/feed.xml")
        updates = await monitor.check(["https://example.com/feed.xml"])

        # Or use the default feeds
        monitor.add_feeds([
            "https://hnrss.org/newest",
            "https://feeds.arxiv.org/rss/cs.AI",
        ])
        updates = await monitor.check_all()
    """

    VALID_FEED_TYPES = frozenset(["rss", "atom", "unknown"])

    def __init__(
        self,
        timeout: float = 30.0,
        user_agent: str = "noman-cli/1.0",
        max_items: int = 50,
        config: dict[str, Any] | None = None,
    ) -> None:
        """Initialize RSS monitor.

        Args:
            timeout: HTTP request timeout.
            user_agent: User-Agent header.
            max_items: Max items per feed.
            config: Configuration from config.toml [research.rss] section.
        """
        self._config = config or {}
        self._timeout = self._config.get("timeout", timeout)
        self._user_agent = self._config.get("user_agent", user_agent)
        self._max_items = self._config.get("max_items", max_items)
        self._feeds: list[RSSFeed] = []
        self._feed_cache: dict[str, RSSFeed] = {}
        self._new_items_cache: dict[str, set[str]] = {}  # feed_url -> set of GUIDs
        self._cache_dir = Path.home() / ".noman" / "rss_cache"
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def add_feed(
        self,
        url: str,
        title: str = "",
        filter_keywords: list[str] | None = None,
        excluded_keywords: list[str] | None = None,
        max_items: int | None = None,
        check_interval: int | None = None,
    ) -> RSSFeed:
        """Add a feed to monitor.

        Args:
            url: Feed URL.
            title: Optional title.
            filter_keywords: Keywords to filter items.
            excluded_keywords: Keywords to exclude.
            max_items: Max items to cache.
            check_interval: Check interval in seconds.

        Returns:
            The created RSSFeed object.
        """
        feed = RSSFeed(
            url=url,
            title=title or url,
            filter_keywords=filter_keywords or [],
            excluded_keywords=excluded_keywords or [],
            max_items=max_items or self._max_items,
            check_interval=check_interval or 3600,
        )
        self._feeds.append(feed)
        self._feed_cache[url] = feed
        return feed

    def add_feeds(
        self,
        urls: list[str],
        **kwargs: Any,
    ) -> list[RSSFeed]:
        """Add multiple feeds."""
        return [self.add_feed(url, **kwargs) for url in urls]

    def remove_feed(self, url: str) -> bool:
        """Remove a feed from monitoring.

        Args:
            url: Feed URL to remove.

        Returns:
            True if the feed was removed.
        """
        if url in self._feed_cache:
            del self._feed_cache[url]
            self._feeds = [f for f in self._feeds if f.url != url]
            return True
        return False

    def list_feeds(self) -> list[RSSFeed]:
        """List all monitored feeds."""
        return list(self._feeds)

    async def check(
        self,
        feed_urls: list[str] | None = None,
    ) -> dict[str, list[RSSItem]]:
        """Check feeds for new items.

        Args:
            feed_urls: Specific feeds to check. If None, checks all.

        Returns:
            Dict mapping feed URL to list of new RSSItem objects.
        """
        urls = feed_urls if feed_urls else [f.url for f in self._feeds]
        results: dict[str, list[RSSItem]] = {}

        for url in urls:
            feed = self._feed_cache.get(url)
            if not feed:
                # Create a temp feed entry
                feed = RSSFeed(url=url)

            new_items = await self._fetch_feed(url, feed)
            if new_items:
                results[url] = new_items

                # Update feed info
                feed.last_checked = datetime.now(timezone.utc).isoformat()
                if url not in [f.url for f in self._feeds]:
                    self._feeds.append(feed)
                    self._feed_cache[url] = feed

        return results

    async def check_all(self) -> dict[str, list[RSSItem]]:
        """Check all configured feeds."""
        return await self.check()

    async def check_expired(
        self,
    ) -> dict[str, list[RSSItem]]:
        """Check only feeds that are due for a refresh."""
        urls = [f.url for f in self._feeds if f.is_expired()]
        return await self.check(urls) if urls else {}

    async def _fetch_feed(
        self,
        url: str,
        feed: RSSFeed,
    ) -> list[RSSItem]:
        """Fetch and parse a feed."""
        headers = {"User-Agent": self._user_agent}

        # Add cache headers
        if feed.last_etag:
            headers["If-None-Match"] = feed.last_etag
        if feed.last_modified:
            headers["If-Modified-Since"] = feed.last_modified

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(url, headers=headers)

                if resp.status_code == 304:
                    logger.debug(f"Feed unchanged: {url}")
                    return []

                if resp.status_code == 403:
                    logger.warning(f"Feed blocked: {url}")
                    return []

                if resp.status_code != 200:
                    logger.warning(f"Feed error {resp.status_code}: {url}")
                    return []

                feed.last_etag = resp.headers.get("etag", "")
                feed.last_modified = resp.headers.get("last-modified", "")

                return self._parse_feed(resp.text, feed)

        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch feed {url}: {e}")
            return []

    def _parse_feed(self, xml_text: str, feed: RSSFeed) -> list[RSSItem]:
        """Parse RSS or Atom feed XML."""
        import xml.etree.ElementTree as ET

        items: list[RSSItem] = []
        root = ET.fromstring(xml_text)

        # Detect feed type
        if root.tag.endswith("}feed"):
            feed.feed_type = "atom"
            channel = root
            # Parse Atom feed
            feed_title_el = channel.find("{http://www.w3.org/2005/Atom}title")
            if feed_title_el is not None:
                feed.title = feed_title_el.text or feed.title

            for entry in channel.findall("{http://www.w3.org/2005/Atom}entry"):
                title_el = entry.find("{http://www.w3.org/2005/Atom}title")
                link_el = entry.find("{http://www.w3.org/2005/Atom}link")
                summary_el = entry.find("{http://www.w3.org/2005/Atom}summary")
                content_el = entry.find("{http://www.w3.org/2005/Atom}content")
                author_el = entry.find("{http://www.w3.org/2005/Atom}author")
                published_el = entry.find("{http://www.w3.org/2005/Atom}published")
                updated_el = entry.find("{http://www.w3.org/2005/Atom}updated")
                id_el = entry.find("{http://www.w3.org/2005/Atom}id")

                author_name = ""
                if author_el is not None:
                    name_el = author_el.find("{http://www.w3.org/2005/Atom}name")
                    if name_el is not None:
                        author_name = name_el.text or ""

                item = RSSItem(
                    title=title_el.text if title_el is not None else "",
                    link=link_el.get("href", "") if link_el is not None else "",
                    summary=summary_el.text if summary_el is not None else "",
                    content=content_el.text if content_el is not None else "",
                    author=author_name,
                    published=published_el.text if published_el is not None else "",
                    updated=updated_el.text if updated_el is not None else "",
                    guid=id_el.text if id_el is not None else "",
                    feed_title=feed.title,
                    feed_url=feed.url,
                )
                if feed.passes_filter(item):
                    items.append(item)
        else:
            feed.feed_type = "rss"
            channel = root

            # Parse RSS feed
            channel_title = channel.find("title")
            if channel_title is not None:
                feed.title = channel_title.text or feed.title

            for item_el in channel.findall("item"):
                title_el = item_el.find("title")
                link_el = item_el.find("link")
                summary_el = item_el.find("description")
                content_el = item_el.find("{http://purl.org/rss/1.0/modules/content/}encoded")
                author_el = item_el.find("{http://purl.org/dc/elements/1.1/}author")
                pubdate_el = item_el.find("pubDate")
                guid_el = item_el.find("guid")

                categories = [
                    cat.text or ""
                    for cat in item_el.findall("category")
                ]

                enclosure_el = item_el.find("enclosure")
                enclosure = {}
                if enclosure_el is not None:
                    enclosure = {
                        "url": enclosure_el.get("url", ""),
                        "type": enclosure_el.get("type", ""),
                        "length": enclosure_el.get("length", ""),
                    }

                item = RSSItem(
                    title=title_el.text if title_el is not None else "",
                    link=link_el.text if link_el is not None else "",
                    summary=summary_el.text if summary_el is not None else "",
                    content=content_el.text if content_el is not None else "",
                    author=author_el.text if author_el is not None else "",
                    published=pubdate_el.text if pubdate_el is not None else "",
                    guid=guid_el.text if guid_el is not None else "",
                    categories=categories,
                    enclosure=enclosure,
                    feed_title=feed.title,
                    feed_url=feed.url,
                )
                if feed.passes_filter(item):
                    items.append(item)

        # Limit items
        return items[:feed.max_items]

    async def aggregate(
        self,
        feed_urls: list[str] | None = None,
        since: datetime | None = None,
    ) -> list[RSSItem]:
        """Aggregate new items from multiple feeds.

        Args:
            feed_urls: Feeds to include. If None, all feeds.
            since: Only include items newer than this datetime.

        Returns:
            Aggregated list of new RSSItem objects, sorted by date.
        """
        results = await self.check(feed_urls)
        all_items: list[RSSItem] = []

        for url, items in results.items():
            for item in items:
                if item.is_new(since):
                    all_items.append(item)

        # Sort by publication date
        all_items.sort(
            key=lambda x: x.pub_date or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        return all_items
