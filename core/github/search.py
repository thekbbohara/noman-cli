"""GitHub code and search API.

Provides repository search, code search, and user/org search
via the GitHub Search API.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """Single search result item."""

    name: str
    path: str
    sha: str
    html_url: str = ""
    repository: str = ""
    score: float = 0.0
    matches: list[dict[str, Any]] = field(default_factory=list)

    @property
    def file_url(self) -> str:
        return f"{self.html_url}/blob/{self.sha}/{self.path}"


@dataclass
class SearchResponse:
    """Aggregated search response."""

    total_count: int
    items: list[SearchResult]
    incomplete: bool = False
    query: str = ""


class SearchClient:
    """GitHub Search API client.

    Provides code search, repository search, and user/org search.
    All methods are async. Requires a GitHubClient instance.
    """

    def __init__(self, github_client: "GitHubClient") -> None:
        self.client = github_client

    # ── Code search ──

    async def search_code(
        self,
        query: str,
        sort: str = "relevance",
        order: str = "desc",
        per_page: int = 30,
        page: int = 1,
    ) -> SearchResponse:
        """Search code across all public repositories.

        Uses the GitHub code search API with advanced query syntax.

        Query syntax:
            - keyword: search for text
            - repo:owner/repo: limit to repository
            - user:username: limit to user's repos
            - path:file.ext: search in file path
            - ext:py: search by file extension
            - language:Python: filter by language
            - filename:README: search in filenames
            - path:src/: search in paths
            - :ignore: case-insensitive
            - "quoted text": exact phrase

        Args:
            query: Search query (GitHub search syntax).
            sort: Sort field ('relevance', 'indexed').
            order: Sort order ('asc', 'desc').
            per_page: Results per page (max 100).
            page: Page number.

        Returns:
            SearchResponse with results.
        """
        params: dict[str, Any] = {
            "q": query,
            "sort": sort,
            "order": order,
            "per_page": min(per_page, 100),
            "page": page,
        }

        resp = await self.client.request("GET", "/search/code", params=params)
        if not resp.ok:
            return SearchResponse(total_count=0, items=[])

        data = resp.json
        items = data.get("items", [])
        return SearchResponse(
            total_count=data.get("total_count", 0),
            items=[
                SearchResult(
                    name=item.get("name", ""),
                    path=item.get("path", ""),
                    sha=item.get("sha", ""),
                    html_url=item.get("html_url", ""),
                    repository=item.get("repository", {}).get("full_name", ""),
                    score=item.get("score", 0.0),
                    matches=[
                        {
                            "text": m.get("text", ""),
                            "matches": m.get("matches", []),
                        }
                        for m in item.get("text_matches", [])
                    ],
                )
                for item in items
            ],
            incomplete=data.get("incomplete", False),
            query=query,
        )

    # ── Repository search ──

    async def search_repos(
        self,
        query: str,
        sort: str = "stars",
        order: str = "desc",
        per_page: int = 30,
        page: int = 1,
    ) -> SearchResponse:
        """Search repositories.

        Query syntax:
            - keyword: search in name/description
            - user:owner: search within a user/org
            - >1000 stars: minimum stars
            - <100 size: maximum repo size (KB)
            - created:>2024-01-01: min creation date
            - pushed:>2024-01-01: min push date
            - language:Python: filter by language
            - topic:python: filter by topic
            - fork:true: only forked repos
            - archived:false: only active repos

        Args:
            query: Search query (GitHub search syntax).
            sort: Sort field ('stars', 'forks', 'help-wanted-issues', 'updated').
            order: Sort order ('asc', 'desc').
            per_page: Results per page (max 100).
            page: Page number.

        Returns:
            SearchResponse with repository results.
        """
        params: dict[str, Any] = {
            "q": query,
            "sort": sort,
            "order": order,
            "per_page": min(per_page, 100),
            "page": page,
        }

        resp = await self.client.request("GET", "/search/repositories", params=params)
        if not resp.ok:
            return SearchResponse(total_count=0, items=[])

        data = resp.json
        items = data.get("items", [])
        return SearchResponse(
            total_count=data.get("total_count", 0),
            items=[
                SearchResult(
                    name=item.get("name", ""),
                    path=item.get("full_name", ""),
                    sha=item.get("default_branch", "main"),
                    html_url=item.get("html_url", ""),
                    repository=item.get("full_name", ""),
                    score=item.get("score", 0.0),
                    matches=[],
                )
                for item in items
            ],
            incomplete=data.get("incomplete", False),
            query=query,
        )

    # ── Issues search ──

    async def search_issues(
        self,
        query: str,
        sort: str = "comments",
        order: str = "desc",
        per_page: int = 30,
        page: int = 1,
    ) -> SearchResponse:
        """Search issues and pull requests across all repositories.

        Query syntax:
            - keyword: search in title/body/comments
            - repo:owner/repo: limit to repository
            - user:username: limit to user's repos
            - label:bug: filter by label
            - milestone:123: filter by milestone number
            - author:user: filter by author
            - assignee:user: filter by assignee
            - is:issue or is:pr: filter by type
            - is:open or is:closed: filter by state
            - created:>2024-01-01: min creation date
            - comments:>10: minimum comment count

        Args:
            query: Search query (GitHub search syntax).
            sort: Sort field ('comments', 'reactions', 'created', 'updated').
            order: Sort order ('asc', 'desc').
            per_page: Results per page (max 100).
            page: Page number.

        Returns:
            SearchResponse with issue/PR results.
        """
        params: dict[str, Any] = {
            "q": query,
            "sort": sort,
            "order": order,
            "per_page": min(per_page, 100),
            "page": page,
        }

        resp = await self.client.request("GET", "/search/issues", params=params)
        if not resp.ok:
            return SearchResponse(total_count=0, items=[])

        data = resp.json
        items = data.get("items", [])
        return SearchResponse(
            total_count=data.get("total_count", 0),
            items=[
                SearchResult(
                    name=item.get("title", ""),
                    path=item.get("html_url", ""),
                    sha=item.get("head", {}).get("sha", "")
                    if isinstance(item.get("head"), dict)
                    else "",
                    html_url=item.get("html_url", ""),
                    repository=item.get("repository", {}).get("full_name", ""),
                    score=item.get("score", 0.0),
                    matches=[
                        {
                            "text": m.get("text", ""),
                            "matches": m.get("matches", []),
                        }
                        for m in item.get("text_matches", [])
                    ],
                )
                for item in items
            ],
            incomplete=data.get("incomplete", False),
            query=query,
        )

    # ── Users search ──

    async def search_users(
        self,
        query: str,
        sort: str = "followers",
        order: str = "desc",
        per_page: int = 30,
        page: int = 1,
    ) -> SearchResponse:
        """Search users and organizations.

        Query syntax:
            - keyword: search in name/bio/login
            - location:Berlin: filter by location
            - followers:>100: minimum followers
            - company:Google: filter by company
            - type:user or type:org: filter by type
            - created:>2024-01-01: min account creation date

        Args:
            query: Search query (GitHub search syntax).
            sort: Sort field ('followers', 'repositories', 'joined').
            order: Sort order ('asc', 'desc').
            per_page: Results per page (max 100).
            page: Page number.

        Returns:
            SearchResponse with user/org results.
        """
        params: dict[str, Any] = {
            "q": query,
            "sort": sort,
            "order": order,
            "per_page": min(per_page, 100),
            "page": page,
        }

        resp = await self.client.request("GET", "/search/users", params=params)
        if not resp.ok:
            return SearchResponse(total_count=0, items=[])

        data = resp.json
        items = data.get("items", [])
        return SearchResponse(
            total_count=data.get("total_count", 0),
            items=[
                SearchResult(
                    name=item.get("login", ""),
                    path=item.get("html_url", ""),
                    sha="",
                    html_url=item.get("html_url", ""),
                    repository=item.get("html_url", ""),
                    score=item.get("score", 0.0),
                    matches=[],
                )
                for item in items
            ],
            incomplete=data.get("incomplete", False),
            query=query,
        )

    # ── Advanced search helpers ──

    @staticmethod
    def build_code_query(
        keyword: str = "",
        repo: str = "",
        path: str = "",
        filename: str = "",
        ext: str = "",
        language: str = "",
        min_star_count: int = 0,
        max_star_count: int = 0,
        user: str = "",
    ) -> str:
        """Build a code search query string.

        Args:
            keyword: Text to search for.
            repo: 'owner/repo' to limit search.
            path: Path pattern to limit search.
            filename: Filename pattern.
            ext: File extension (without dot).
            language: Programming language.
            min_star_count: Minimum repository stars.
            max_star_count: Maximum repository stars.
            user: GitHub username.

        Returns:
            GitHub search query string.
        """
        parts: list[str] = []
        if keyword:
            parts.append(keyword)
        if repo:
            parts.append(f"repo:{repo}")
        if path:
            parts.append(f"path:{path}")
        if filename:
            parts.append(f"filename:{filename}")
        if ext:
            parts.append(f"ext:{ext}")
        if language:
            parts.append(f"language:{language}")
        if min_star_count > 0:
            parts.append(f">={min_star_count} stars")
        if max_star_count > 0:
            parts.append(f"<={max_star_count} stars")
        if user:
            parts.append(f"user:{user}")
        return " ".join(parts)

    @staticmethod
    def build_issue_query(
        repo: str = "",
        state: str = "",
        label: str = "",
        author: str = "",
        assignee: str = "",
        milestone: str = "",
        created: str = "",
        keyword: str = "",
    ) -> str:
        """Build an issues/PRs search query string."""
        parts: list[str] = []
        if repo:
            parts.append(f"repo:{repo}")
        if state:
            parts.append(f"is:{state}")
        if label:
            parts.append(f"label:{label}")
        if author:
            parts.append(f"author:{author}")
        if assignee:
            parts.append(f"assignee:{assignee}")
        if milestone:
            parts.append(f"milestone:{milestone}")
        if created:
            parts.append(f"created:{created}")
        if keyword:
            parts.append(keyword)
        return " ".join(parts)
