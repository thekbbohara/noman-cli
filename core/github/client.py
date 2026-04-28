"""GitHub API client with authentication, rate-limiting, and retry logic.

Uses the GitHub CLI (gh) for authentication when available, falling back
to environment variables (GITHUB_TOKEN) or explicit token configuration.
All public methods support both synchronous and asynchronous usage patterns.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RateLimit:
    """GitHub API rate limit information."""

    limit: int
    remaining: int
    reset_at: float
    used: int
    resource: str = "core"

    @property
    def is_exhausted(self) -> bool:
        return self.remaining <= 0

    @property
    def wait_seconds(self) -> float:
        """Seconds until rate limit resets."""
        return max(0.0, self.reset_at - time.time())


@dataclass
class APIResponse:
    """Normalized API response wrapper."""

    status_code: int
    data: Any
    headers: dict[str, str] = field(default_factory=dict)
    rate_limit: RateLimit | None = None
    is_paginated: bool = False
    next_page_url: str | None = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    @property
    def json(self) -> Any:
        if isinstance(self.data, str):
            return json.loads(self.data)
        return self.data


class GitHubError(Exception):
    """Base error for GitHub operations."""


class GitHubRateLimitError(GitHubError):
    """Rate limit exceeded."""


class GitHubAuthError(GitHubError):
    """Authentication failed."""


class GitHubClient:
    """Authenticated GitHub API client.

    Authentication sources (in priority order):
    1. Explicit ``token`` passed to constructor
    2. ``GITHUB_TOKEN`` environment variable
    3. ``gh auth token`` output (GitHub CLI)

    Supports OAuth PATs, GitHub Apps tokens, and fine-grained PATs.

    Usage::

        client = GitHubClient()
        await client.authenticate()
        issues = client.issues  # IssuesClient instance
        prs = client.prs         # PRsClient instance
        repos = client.repos     # ReposClient instance
    """

    def __init__(
        self,
        token: str | None = None,
        base_url: str = "https://api.github.com",
        per_page: int = 30,
        max_retries: int = 3,
        retry_base_delay: float = 1.0,
        user_agent: str = "noman-cli/1.0",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.per_page = per_page
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay
        self.user_agent = user_agent
        self._token: str | None = None
        self._rate_limit: RateLimit | None = None
        self._authenticated = False
        self._last_request_at: float = 0.0
        self._min_request_interval: float = 0.5  # throttle requests

        # Sub-clients
        self.issues: IssuesClient | None = None
        self.prs: PRsClient | None = None
        self.repos: ReposClient | None = None
        self.actions: ActionsClient | None = None
        self.codeowners: CODEOWNERSClient | None = None
        self.search: SearchClient | None = None

    @property
    def is_authenticated(self) -> bool:
        return self._authenticated

    @property
    def rate_limit(self) -> RateLimit | None:
        return self._rate_limit

    async def authenticate(self) -> bool:
        """Authenticate using available credentials.

        Tries (in order):
        1. Token from constructor
        2. GITHUB_TOKEN env var
        3. gh CLI auth token

        Returns True if authentication succeeded.
        """
        if self._token:
            self._authenticated = True
            logger.debug("Using explicit token for authentication")
            return True

        # Environment variable
        env_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if env_token:
            self._token = env_token
            self._authenticated = True
            logger.debug("Authenticated via GITHUB_TOKEN environment variable")
            return True

        # gh CLI fallback
        gh_token = await self._get_gh_token()
        if gh_token:
            self._token = gh_token
            self._authenticated = True
            logger.info("Authenticated via gh CLI")
            return True

        logger.warning("No GitHub authentication available")
        return False

    async def _get_gh_token(self) -> str | None:
        """Get token from gh CLI."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "gh", "auth", "token",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0 and stdout:
                return stdout.decode().strip()
            return None
        except (FileNotFoundError, OSError) as e:
            logger.debug("gh CLI not available: %s", e)
            return None

    async def _throttle(self) -> None:
        """Enforce minimum interval between requests."""
        elapsed = time.time() - self._last_request_at
        if elapsed < self._min_request_interval:
            await asyncio.sleep(self._min_request_interval - elapsed)
        self._last_request_at = time.time()

    async def request(
        self,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> APIResponse:
        """Make an HTTP request to the GitHub API with retry logic.

        Args:
            method: HTTP method (GET, POST, PUT, PATCH, DELETE).
            path: API path (without base_url).
            json_body: JSON request body.
            params: Query parameters.

        Returns:
            APIResponse with parsed data.

        Raises:
            GitHubRateLimitError: When rate limit is exhausted.
            GitHubAuthError: When authentication fails.
        """
        if not self._authenticated:
            raise GitHubAuthError("Not authenticated. Call authenticate() first.")

        if not self._token:
            raise GitHubAuthError("No token available.")

        import httpx

        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": self.user_agent,
        }

        last_exception: Exception | None = None
        for attempt in range(self.max_retries + 1):
            await self._throttle()
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    kwargs: dict[str, Any] = {"headers": headers}
                    if json_body:
                        kwargs["json"] = json_body
                    if params:
                        kwargs["params"] = params

                    resp = await client.request(method, url, **kwargs)

                    # Parse rate limit headers
                    self._rate_limit = RateLimit(
                        limit=int(resp.headers.get("x-ratelimit-limit", "60")),
                        remaining=int(resp.headers.get("x-ratelimit-remaining", "0")),
                        reset_at=float(resp.headers.get("x-ratelimit-reset", "0")),
                        used=int(resp.headers.get("x-ratelimit-used", "0")),
                    )

                    if resp.status_code == 401:
                        raise GitHubAuthError(
                            f"Authentication failed: {resp.text[:200]}"
                        )

                    if resp.status_code == 403 and "rate limit" in resp.text.lower():
                        wait = self._rate_limit.wait_seconds if self._rate_limit else 60
                        if attempt < self.max_retries:
                            logger.warning(
                                "Rate limit hit. Waiting %.1fs (attempt %d/%d)",
                                wait, attempt + 1, self.max_retries,
                            )
                            await asyncio.sleep(min(wait, 60.0))
                            continue
                        raise GitHubRateLimitError(
                            f"Rate limit exhausted. Resets in {wait:.0f}s"
                        )

                    if resp.status_code == 404:
                        return APIResponse(
                            status_code=404,
                            data=None,
                            headers=dict(resp.headers),
                            rate_limit=self._rate_limit,
                        )

                    # Handle pagination
                    is_paginated = "next" in resp.links
                    next_page_url = resp.links.get("next", {}).get("url")

                    try:
                        data = resp.json()
                    except (json.JSONDecodeError, ValueError):
                        data = resp.text

                    return APIResponse(
                        status_code=resp.status_code,
                        data=data,
                        headers=dict(resp.headers),
                        rate_limit=self._rate_limit,
                        is_paginated=is_paginated,
                        next_page_url=next_page_url,
                    )

            except (httpx.ConnectError, httpx.TimeoutException, OSError) as e:
                last_exception = e
                if attempt < self.max_retries:
                    delay = self.retry_base_delay * (2 ** attempt)
                    logger.debug(
                        "Request failed (attempt %d/%d), retrying in %.1fs: %s",
                        attempt + 1, self.max_retries, delay, e,
                    )
                    await asyncio.sleep(delay)
                else:
                    break

        raise GitHubError(
            f"Request failed after {self.max_retries} retries: {last_exception}"
        ) from last_exception

    # ── Convenience accessors ──

    async def get_user(self) -> dict[str, Any] | None:
        """Get the authenticated user's profile."""
        resp = await self.request("GET", "/user")
        if resp.ok:
            return resp.json
        return None

    async def get_repo(self, owner: str, repo: str) -> dict[str, Any] | None:
        """Get repository details."""
        resp = await self.request("GET", f"/repos/{owner}/{repo}")
        if resp.ok:
            return resp.json
        return None

    async def list_repos(self, username: str = "") -> list[dict[str, Any]]:
        """List repositories for a user or org."""
        path = f"/users/{username}/repos" if username else "/user/repos"
        resp = await self.request("GET", path, params={"per_page": self.per_page})
        if resp.ok:
            return resp.json if isinstance(resp.json, list) else []
        return []

    async def get_contents(
        self, owner: str, repo: str, path: str, ref: str = "main"
    ) -> dict[str, Any] | None:
        """Get file/directory contents from a repository."""
        resp = await self.request(
            "GET",
            f"/repos/{owner}/{repo}/contents/{path.lstrip('/')}",
            params={"ref": ref},
        )
        if resp.ok:
            return resp.json
        return None

    def initialize_subclients(self) -> None:
        """Initialize sub-clients that depend on this client instance."""
        self.issues = IssuesClient(self)
        self.prs = PRsClient(self)
        self.repos = ReposClient(self)
        self.actions = ActionsClient(self)
        self.codeowners = CODEOWNERSClient(self)
        self.search = SearchClient(self)
