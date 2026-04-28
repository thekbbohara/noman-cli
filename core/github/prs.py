"""GitHub Pull Request management.

Provides create, list, review, merge, and related PR operations.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PullRequest:
    """GitHub pull request representation."""

    number: int
    title: str
    body: str
    state: str  # open, closed, merged
    author: str
    labels: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    merged_at: str = ""
    closed_at: str = ""
    url: str = ""
    base_ref: str = ""
    head_ref: str = ""
    base_repo: str = ""
    head_repo: str = ""
    commits: int = 0
    additions: int = 0
    deletions: int = 0
    changed_files: int = 0
    merged_by: str = ""
    repository: str = ""

    @property
    def is_open(self) -> bool:
        return self.state == "open"

    @property
    def is_merged(self) -> bool:
        return self.state == "merged"

    @property
    def is_closed(self) -> bool:
        return self.state == "closed"

    @property
    def ref(self) -> str:
        return f"{self.head_repo}:{self.head_ref}"


class PRsClient:
    """Manage pull requests for a repository.

    All methods are async. Requires a GitHubClient instance.

    Usage::

        client = GitHubClient()
        await client.authenticate()
        client.initialize_subclients()
        prs = client.prs
        pr = await prs.create("owner", "repo", "feature-branch", "main", "Title", "Body")
    """

    def __init__(self, github_client: "GitHubClient") -> None:
        self.client = github_client

    async def create(
        self,
        owner: str,
        repo: str,
        head: str,
        base: str,
        title: str,
        body: str = "",
        draft: bool = False,
        maintainer_can_modify: bool = True,
        labels: list[str] | None = None,
    ) -> PullRequest | None:
        """Create a new pull request.

        Args:
            owner: Repository owner.
            repo: Repository name.
            head: Source branch (e.g. 'feature-branch').
            base: Target branch (e.g. 'main').
            title: PR title.
            body: Markdown description.
            draft: Create as draft PR.
            maintainer_can_modify: Allow maintainer edits.
            labels: List of label names.

        Returns:
            PullRequest on success, None on failure.
        """
        payload: dict[str, Any] = {
            "title": title,
            "head": head,
            "base": base,
            "draft": draft,
            "maintainer_can_modify": maintainer_can_modify,
        }
        if body:
            payload["body"] = body
        if labels:
            payload["labels"] = labels

        resp = await self.client.request(
            "POST", f"/repos/{owner}/{repo}/pulls", json_body=payload
        )
        if resp.ok:
            data = resp.json
            return PullRequest(
                number=data.get("number", 0),
                title=data.get("title", ""),
                body=data.get("body", ""),
                state=data.get("state", "open"),
                author=data.get("user", {}).get("login", ""),
                created_at=data.get("created_at", ""),
                updated_at=data.get("updated_at", ""),
                url=data.get("html_url", ""),
                base_ref=data.get("base", {}).get("ref", ""),
                head_ref=data.get("head", {}).get("ref", ""),
                base_repo=data.get("base", {}).get("repo", {}).get("full_name", ""),
                head_repo=data.get("head", {}).get("repo", {}).get("full_name", ""),
                repository=f"{owner}/{repo}",
            )
        logger.error("Failed to create PR: %d - %s", resp.status_code, resp.data)
        return None

    async def list(
        self,
        owner: str,
        repo: str,
        state: str = "open",
        head: str | None = None,
        base: str | None = None,
        sort: str = "created",
        direction: str = "desc",
        page: int = 1,
        per_page: int = 30,
    ) -> list[PullRequest]:
        """List pull requests with filters.

        Args:
            owner: Repository owner.
            repo: Repository name.
            state: 'open', 'closed', 'all'.
            head: Filter by head user/branch ('user:branch').
            base: Filter by base branch.
            sort: 'created', 'updated', 'popularity', 'long-running'.
            direction: 'asc' or 'desc'.
            page: Page number.
            per_page: Results per page (max 100).

        Returns:
            List of PullRequest objects.
        """
        params: dict[str, Any] = {
            "state": state,
            "sort": sort,
            "direction": direction,
            "page": page,
            "per_page": min(per_page, 100),
        }
        if head:
            params["head"] = head
        if base:
            params["base"] = base

        resp = await self.client.request(
            "GET", f"/repos/{owner}/{repo}/pulls", params=params
        )
        if not resp.ok:
            logger.error("Failed to list PRs: %d", resp.status_code)
            return []

        data = resp.json if isinstance(resp.json, list) else []
        return [
            PullRequest(
                number=item.get("number", 0),
                title=item.get("title", ""),
                body=item.get("body", ""),
                state=item.get("state", "open"),
                author=item.get("user", {}).get("login", ""),
                labels=[lb.get("name", "") for lb in item.get("labels", [])],
                created_at=item.get("created_at", ""),
                updated_at=item.get("updated_at", ""),
                merged_at=item.get("merged_at", ""),
                closed_at=item.get("closed_at", ""),
                url=item.get("html_url", ""),
                base_ref=item.get("base", {}).get("ref", ""),
                head_ref=item.get("head", {}).get("ref", ""),
                base_repo=item.get("base", {}).get("repo", {}).get("full_name", ""),
                head_repo=item.get("head", {}).get("repo", {}).get("full_name", ""),
                commits=item.get("commits", 0),
                additions=item.get("additions", 0),
                deletions=item.get("deletions", 0),
                changed_files=item.get("changed_files", 0),
                merged_by=item.get("merged_by", {}).get("login", "")
                if item.get("merged_by")
                else "",
                repository=f"{owner}/{repo}",
            )
            for item in data
        ]

    async def get(self, owner: str, repo: str, number: int) -> PullRequest | None:
        """Get a single PR by number."""
        resp = await self.client.request(
            "GET", f"/repos/{owner}/{repo}/pulls/{number}"
        )
        if not resp.ok:
            return None
        data = resp.json
        return PullRequest(
            number=data.get("number", 0),
            title=data.get("title", ""),
            body=data.get("body", ""),
            state=data.get("state", "open"),
            author=data.get("user", {}).get("login", ""),
            labels=[lb.get("name", "") for lb in data.get("labels", [])],
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            merged_at=data.get("merged_at", ""),
            closed_at=data.get("closed_at", ""),
            url=data.get("html_url", ""),
            base_ref=data.get("base", {}).get("ref", ""),
            head_ref=data.get("head", {}).get("ref", ""),
            base_repo=data.get("base", {}).get("repo", {}).get("full_name", ""),
            head_repo=data.get("head", {}).get("repo", {}).get("full_name", ""),
            commits=data.get("commits", 0),
            additions=data.get("additions", 0),
            deletions=data.get("deletions", 0),
            changed_files=data.get("changed_files", 0),
            merged_by=data.get("merged_by", {}).get("login", "")
            if data.get("merged_by")
            else "",
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
        base: str | None = None,
    ) -> PullRequest | None:
        """Update a PR's title, body, state, or base branch."""
        payload: dict[str, Any] = {}
        if title is not None:
            payload["title"] = title
        if body is not None:
            payload["body"] = body
        if state is not None:
            payload["state"] = state
        if base is not None:
            payload["base"] = base

        resp = await self.client.request(
            "PATCH", f"/repos/{owner}/{repo}/pulls/{number}", json_body=payload
        )
        if resp.ok:
            return await self.get(owner, repo, number)
        return None

    async def list_reviews(
        self, owner: str, repo: str, number: int
    ) -> list[dict[str, Any]]:
        """List review requests for a PR."""
        resp = await self.client.request(
            "GET", f"/repos/{owner}/{repo}/pulls/{number}/requested_reviewers"
        )
        if resp.ok:
            return resp.json if isinstance(resp.json, list) else []
        return []

    async def request_review(
        self, owner: str, repo: str, number: int, reviewers: list[str]
    ) -> bool:
        """Request reviews from specific users."""
        resp = await self.client.request(
            "POST",
            f"/repos/{owner}/{repo}/pulls/{number}/requested_reviewers",
            json_body={"reviewers": reviewers},
        )
        return resp.ok

    async def submit_review(
        self,
        owner: str,
        repo: str,
        number: int,
        commit_id: str,
        event: str,
        body: str = "",
        comments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        """Submit a PR review.

        Args:
            event: 'APPROVE', 'REQUEST_CHANGES', or 'COMMENT'.
            commit_id: SHA of the commit being reviewed.
            body: Review comment body.
            comments: List of comment dicts with 'path', 'line', 'body'.

        Returns:
            Review data on success, None on failure.
        """
        payload: dict[str, Any] = {
            "commit_id": commit_id,
            "event": event.upper(),
        }
        if body:
            payload["body"] = body
        if comments:
            payload["comments"] = comments

        resp = await self.client.request(
            "POST",
            f"/repos/{owner}/{repo}/pulls/{number}/reviews",
            json_body=payload,
        )
        if resp.ok:
            return resp.json
        logger.error("Failed to submit review: %d", resp.status_code)
        return None

    async def list_comments(
        self, owner: str, repo: str, number: int
    ) -> list[dict[str, Any]]:
        """List review comments on a PR."""
        resp = await self.client.request(
            "GET", f"/repos/{owner}/{repo}/pulls/{number}/comments"
        )
        if resp.ok:
            return resp.json if isinstance(resp.json, list) else []
        return []

    async def list_files(
        self, owner: str, repo: str, number: int
    ) -> list[dict[str, Any]]:
        """List files changed in a PR."""
        resp = await self.client.request(
            "GET", f"/repos/{owner}/{repo}/pulls/{number}/files"
        )
        if resp.ok:
            return resp.json if isinstance(resp.json, list) else []
        return []

    async def list_commits(
        self, owner: str, repo: str, number: int
    ) -> list[dict[str, Any]]:
        """List commits in a PR."""
        resp = await self.client.request(
            "GET", f"/repos/{owner}/{repo}/pulls/{number}/commits"
        )
        if resp.ok:
            return resp.json if isinstance(resp.json, list) else []
        return []

    async def get_status(
        self, owner: str, repo: str, number: int
    ) -> list[dict[str, Any]]:
        """Get combined commit status for a PR's head commit."""
        resp = await self.client.request(
            "GET", f"/repos/{owner}/{repo}/commits/{number}/check-runs"
        )
        if resp.ok:
            return resp.json if isinstance(resp.json, dict) else {}
        return {}

    async def merge(
        self,
        owner: str,
        repo: str,
        number: int,
        commit_title: str = "",
        commit_message: str = "",
        merge_method: str = "merge",
    ) -> dict[str, Any] | None:
        """Merge a pull request.

        Args:
            merge_method: 'merge', 'squash', or 'rebase'.

        Returns:
            Merge result data on success, None on failure.
        """
        payload: dict[str, Any] = {"merge_method": merge_method}
        if commit_title:
            payload["commit_title"] = commit_title
        if commit_message:
            payload["commit_message"] = commit_message

        resp = await self.client.request(
            "PUT", f"/repos/{owner}/{repo}/pulls/{number}/merge", json_body=payload
        )
        if resp.ok:
            return resp.json
        logger.error("Failed to merge PR #%d: %d", number, resp.status_code)
        return None

    async def close(self, owner: str, repo: str, number: int) -> bool:
        """Close a PR without merging."""
        return await self.update(owner, repo, number, state="closed")

    async def get_diff(
        self, owner: str, repo: str, number: int
    ) -> str | None:
        """Get the raw diff of a PR."""
        resp = await self.client.request(
            "GET", f"/repos/{owner}/{repo}/pulls/{number}"
        )
        if resp.ok:
            return resp.json.get("diff", "")
        return None

    async def get_patch(
        self, owner: str, repo: str, number: int
    ) -> str | None:
        """Get the patch of a PR."""
        resp = await self.client.request(
            "GET", f"/repos/{owner}/{repo}/pulls/{number}"
        )
        if resp.ok:
            return resp.json.get("patch", "")
        return None
