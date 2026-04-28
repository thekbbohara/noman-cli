"""GitHub Issues management.

Provides create, list, update, close, and search operations
for GitHub issues.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Issue:
    """GitHub issue representation."""

    number: int
    title: str
    body: str
    state: str  # open, closed
    author: str
    labels: list[str] = field(default_factory=list)
    assignees: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    closed_at: str = ""
    comments: int = 0
    url: str = ""
    milestone: str | None = None
    repository: str = ""

    @property
    def is_open(self) -> bool:
        return self.state == "open"

    @property
    def is_closed(self) -> bool:
        return self.state == "closed"


class IssuesClient:
    """Manage GitHub issues for a repository.

    Requires a GitHubClient instance. All methods are async.

    Usage::

        client = GitHubClient()
        await client.authenticate()
        client.initialize_subclients()
        issues = client.issues
        issue = await issues.create("owner", "repo", "Bug title", "Bug description")
    """

    def __init__(self, github_client: "GitHubClient") -> None:
        self.client = github_client

    async def create(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str = "",
        labels: list[str] | None = None,
        assignees: list[str] | None = None,
        milestone: int | None = None,
    ) -> Issue | None:
        """Create a new issue.

        Args:
            owner: Repository owner (user or org).
            repo: Repository name.
            title: Issue title.
            body: Markdown description.
            labels: List of label names.
            assignees: List of usernames to assign.
            milestone: Milestone number.

        Returns:
            Created Issue on success, None on failure.
        """
        payload: dict[str, Any] = {"title": title}
        if body:
            payload["body"] = body
        if labels:
            payload["labels"] = labels
        if assignees:
            payload["assignees"] = assignees
        if milestone:
            payload["milestone"] = milestone

        resp = await self.client.request(
            "POST", f"/repos/{owner}/{repo}/issues", json_body=payload
        )
        if resp.ok:
            data = resp.json
            return Issue(
                number=data.get("number", 0),
                title=data.get("title", ""),
                body=data.get("body", ""),
                state=data.get("state", "open"),
                author=data.get("user", {}).get("login", ""),
                labels=[lb.get("name", "") for lb in data.get("labels", [])],
                assignees=[a.get("login", "") for a in data.get("assignees", [])],
                created_at=data.get("created_at", ""),
                updated_at=data.get("updated_at", ""),
                closed_at=data.get("closed_at", ""),
                comments=data.get("comments", 0),
                url=data.get("html_url", ""),
                milestone=data.get("milestone", {}).get("title") if data.get("milestone") else None,
                repository=f"{owner}/{repo}",
            )
        logger.error("Failed to create issue: %d - %s", resp.status_code, resp.data)
        return None

    async def list(
        self,
        owner: str,
        repo: str,
        state: str = "open",
        labels: list[str] | None = None,
        sort: str = "created",
        direction: str = "desc",
        since: str | None = None,
        page: int = 1,
        per_page: int = 30,
    ) -> list[Issue]:
        """List issues with filters.

        Args:
            owner: Repository owner.
            repo: Repository name.
            state: Filter by state ('open', 'closed', 'all').
            labels: Filter by label names.
            sort: Sort field ('created', 'updated', 'comments').
            direction: Sort direction ('asc', 'desc').
            since: ISO 8601 timestamp filter.
            page: Page number.
            per_page: Results per page (max 100).

        Returns:
            List of Issue objects.
        """
        params: dict[str, Any] = {
            "state": state,
            "sort": sort,
            "direction": direction,
            "page": page,
            "per_page": min(per_page, 100),
        }
        if labels:
            params["labels"] = ",".join(labels)
        if since:
            params["since"] = since

        resp = await self.client.request(
            "GET", f"/repos/{owner}/{repo}/issues", params=params
        )
        if not resp.ok:
            logger.error("Failed to list issues: %d", resp.status_code)
            return []

        data = resp.json if isinstance(resp.json, list) else []
        return [
            Issue(
                number=item.get("number", 0),
                title=item.get("title", ""),
                body=item.get("body", ""),
                state=item.get("state", "open"),
                author=item.get("user", {}).get("login", ""),
                labels=[lb.get("name", "") for lb in item.get("labels", [])],
                assignees=[a.get("login", "") for a in item.get("assignees", [])],
                created_at=item.get("created_at", ""),
                updated_at=item.get("updated_at", ""),
                closed_at=item.get("closed_at", ""),
                comments=item.get("comments", 0),
                url=item.get("html_url", ""),
                milestone=(
                    item.get("milestone", {}).get("title")
                    if item.get("milestone")
                    else None
                ),
                repository=f"{owner}/{repo}",
            )
            for item in data
        ]

    async def get(self, owner: str, repo: str, number: int) -> Issue | None:
        """Get a single issue by number.

        Args:
            owner: Repository owner.
            repo: Repository name.
            number: Issue number.

        Returns:
            Issue object or None.
        """
        resp = await self.client.request(
            "GET", f"/repos/{owner}/{repo}/issues/{number}"
        )
        if not resp.ok:
            logger.error("Failed to get issue #%d: %d", number, resp.status_code)
            return None

        data = resp.json
        return Issue(
            number=data.get("number", 0),
            title=data.get("title", ""),
            body=data.get("body", ""),
            state=data.get("state", "open"),
            author=data.get("user", {}).get("login", ""),
            labels=[lb.get("name", "") for lb in data.get("labels", [])],
            assignees=[a.get("login", "") for a in data.get("assignees", [])],
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            closed_at=data.get("closed_at", ""),
            comments=data.get("comments", 0),
            url=data.get("html_url", ""),
            milestone=(
                data.get("milestone", {}).get("title")
                if data.get("milestone")
                else None
            ),
            repository=f"{owner}/{repo}",
        )

    async def update(
        self,
        owner: str,
        repo: str,
        number: int,
        title: str | None = None,
        body: str | None = None,
        state: str | None = None,
        labels: list[str] | None = None,
        assignees: list[str] | None = None,
        milestone: int | None = None,
    ) -> Issue | None:
        """Update an issue.

        Only provided fields are updated (PATCH semantics).
        """
        payload: dict[str, Any] = {}
        if title is not None:
            payload["title"] = title
        if body is not None:
            payload["body"] = body
        if state is not None:
            payload["state"] = state
        if labels is not None:
            payload["labels"] = labels
        if assignees is not None:
            payload["assignees"] = assignees
        if milestone is not None:
            payload["milestone"] = milestone

        resp = await self.client.request(
            "PATCH", f"/repos/{owner}/{repo}/issues/{number}", json_body=payload
        )
        if resp.ok:
            data = resp.json
            return Issue(
                number=data.get("number", number),
                title=data.get("title", ""),
                body=data.get("body", ""),
                state=data.get("state", "open"),
                author=data.get("user", {}).get("login", ""),
                labels=[lb.get("name", "") for lb in data.get("labels", [])],
                assignees=[a.get("login", "") for a in data.get("assignees", [])],
                created_at=data.get("created_at", ""),
                updated_at=data.get("updated_at", ""),
                closed_at=data.get("closed_at", ""),
                comments=data.get("comments", 0),
                url=data.get("html_url", ""),
                milestone=(
                    data.get("milestone", {}).get("title")
                    if data.get("milestone")
                    else None
                ),
                repository=f"{owner}/{repo}",
            )
        logger.error("Failed to update issue #%d: %d", number, resp.status_code)
        return None

    async def close(self, owner: str, repo: str, number: int) -> Issue | None:
        """Close an issue. Convenience wrapper around update(state='closed')."""
        return await self.update(owner, repo, number, state="closed")

    async def reopen(self, owner: str, repo: str, number: int) -> Issue | None:
        """Reopen a closed issue."""
        return await self.update(owner, repo, number, state="open")

    async def add_labels(
        self, owner: str, repo: str, number: int, labels: list[str]
    ) -> Issue | None:
        """Add labels to an issue. Appends to existing labels."""
        # First get current labels
        current = await self.get(owner, repo, number)
        if not current:
            return None
        existing = set(current.labels)
        new_labels = list(existing | set(labels))
        return await self.update(owner, repo, number, labels=new_labels)

    async def add_comment(
        self, owner: str, repo: str, number: int, body: str
    ) -> dict[str, Any] | None:
        """Add a comment to an issue."""
        resp = await self.client.request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{number}/comments",
            json_body={"body": body},
        )
        if resp.ok:
            return resp.json
        logger.error("Failed to add comment to issue #%d: %d", number, resp.status_code)
        return None

    async def list_comments(
        self, owner: str, repo: str, number: int, sort: str = "created"
    ) -> list[dict[str, Any]]:
        """List comments on an issue."""
        resp = await self.client.request(
            "GET",
            f"/repos/{owner}/{repo}/issues/{number}/comments",
            params={"sort": sort},
        )
        if resp.ok:
            return resp.json if isinstance(resp.json, list) else []
        return []

    async def list_events(
        self, owner: str, repo: str, number: int
    ) -> list[dict[str, Any]]:
        """List timeline events for an issue."""
        resp = await self.client.request(
            "GET",
            f"/repos/{owner}/{repo}/issues/{number}/events",
        )
        if resp.ok:
            return resp.json if isinstance(resp.json, list) else []
        return []
