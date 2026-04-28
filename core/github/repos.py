"""GitHub repository management.

Provides clone, fork, list, create, and configure operations.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Repository:
    """GitHub repository representation."""

    full_name: str
    name: str
    owner: str
    description: str = ""
    url: str = ""
    html_url: str = ""
    default_branch: str = "main"
    private: bool = False
    fork: bool = False
    stars: int = 0
    forks: int = 0
    open_issues: int = 0
    language: str = ""
    topics: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    pushed_at: str = ""
    size: int = 0
    license: str = ""
    has_wiki: bool = True
    has_downloads: bool = True
    has_projects: bool = True
    archived: bool = False
    disabled: bool = False

    @property
    def is_public(self) -> bool:
        return not self.private

    @property
    def is_fork(self) -> bool:
        return self.fork


class ReposClient:
    """Manage GitHub repositories.

    Uses a mix of the GitHub API and gh CLI for operations.
    All methods are async.
    """

    def __init__(self, github_client: "GitHubClient") -> None:
        self.client = github_client

    # ── gh CLI wrappers ──

    async def clone(
        self,
        owner_repo: str,
        path: str | None = None,
        ssh: bool = True,
    ) -> str:
        """Clone a repository.

        Args:
            owner_repo: 'owner/repo' format.
            path: Local directory (defaults to repo name).
            ssh: Use SSH URL instead of HTTPS.

        Returns:
            Path to the cloned repository.
        """
        url = f"git@github.com:{owner_repo}.git" if ssh else f"https://github.com/{owner_repo}.git"
        target = path or os.path.basename(owner_repo)
        cmd = f"git clone {url} {target}"
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"git clone failed: {stderr.decode().strip()}")
        resolved = os.path.abspath(target)
        logger.info("Cloned %s -> %s", owner_repo, resolved)
        return resolved

    async def fork(
        self, owner_repo: str, path: str | None = None
    ) -> Repository | None:
        """Fork a repository using gh CLI."""
        cmd = f"gh repo fork {owner_repo} --clone=false"
        if path:
            cmd += f" --name={path}"
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.error("gh repo fork failed: %s", stderr.decode().strip())
            return None
        logger.info("Forked %s", owner_repo)
        return Repository(
            full_name=owner_repo,
            name=owner_repo.split("/")[-1],
            owner=owner_repo.split("/")[0],
            fork=True,
        )

    async def create(
        self,
        name: str,
        description: str = "",
        private: bool = False,
        auto_init: bool = False,
        gitignore: str = "",
        license: str = "",
        owner: str | None = None,
    ) -> Repository | None:
        """Create a new repository using gh CLI."""
        cmd = f"gh repo create {name}"
        if description:
            cmd += f" --description='{description}'"
        if private:
            cmd += " --private"
        else:
            cmd += " --public"
        if auto_init:
            cmd += " --confirm"
        if gitignore:
            cmd += f" --gitignore={gitignore}"
        if license:
            cmd += f" --license={license}"
        if owner:
            cmd += f" --owner={owner}"

        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.error("gh repo create failed: %s", stderr.decode().strip())
            return None
        return Repository(
            full_name=f"{owner or self.client.config.get('user', 'user')}/{name}"
            if owner
            else f"{name}",
            name=name,
            owner=owner or "user",
            description=description,
            private=private,
            fork=False,
        )

    async def delete(self, owner_repo: str, confirm: bool = False) -> bool:
        """Delete a repository."""
        cmd = f"gh repo delete {owner_repo}"
        if confirm:
            cmd += " --yes"
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        success = proc.returncode == 0
        if not success:
            logger.error("gh repo delete failed: %s", stderr.decode().strip())
        return success

    async def list_forks(
        self, owner_repo: str, sort: str = "newest", per_page: int = 30
    ) -> list[Repository]:
        """List forks of a repository."""
        resp = await self.client.request(
            "GET",
            f"/repos/{owner_repo}/forks",
            params={"sort": sort, "per_page": min(per_page, 100)},
        )
        if not resp.ok:
            return []
        data = resp.json if isinstance(resp.json, list) else []
        return [
            Repository(
                full_name=item.get("full_name", ""),
                name=item.get("name", ""),
                owner=item.get("owner", {}).get("login", ""),
                description=item.get("description", ""),
                url=item.get("html_url", ""),
                html_url=item.get("html_url", ""),
                default_branch=item.get("default_branch", "main"),
                private=item.get("private", False),
                fork=item.get("fork", False),
                stars=item.get("stargazers_count", 0),
                forks=item.get("forks_count", 0),
                open_issues=item.get("open_issues_count", 0),
                language=item.get("language", ""),
                created_at=item.get("created_at", ""),
                updated_at=item.get("updated_at", ""),
                pushed_at=item.get("pushed_at", ""),
                license=item.get("license", {}).get("name", "")
                if item.get("license")
                else "",
            )
            for item in data
        ]

    async def list_branches(
        self, owner_repo: str, per_page: int = 30
    ) -> list[dict[str, Any]]:
        """List branches of a repository."""
        resp = await self.client.request(
            "GET",
            f"/repos/{owner_repo}/branches",
            params={"per_page": min(per_page, 100)},
        )
        if resp.ok:
            return resp.json if isinstance(resp.json, list) else []
        return []

    async def get_branch(
        self, owner_repo: str, branch: str
    ) -> dict[str, Any] | None:
        """Get details of a specific branch."""
        resp = await self.client.request(
            "GET", f"/repos/{owner_repo}/branches/{branch}"
        )
        if resp.ok:
            return resp.json
        return None

    async def create_branch(
        self, owner_repo: str, branch: str, base_ref: str = "main"
    ) -> bool:
        """Create a new branch using gh CLI."""
        cmd = f"gh repo create {owner_repo} --branch={branch} --source={base_ref}"
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        return proc.returncode == 0

    async def list_tags(
        self, owner_repo: str, per_page: int = 30
    ) -> list[dict[str, Any]]:
        """List tags of a repository."""
        resp = await self.client.request(
            "GET",
            f"/repos/{owner_repo}/tags",
            params={"per_page": min(per_page, 100)},
        )
        if resp.ok:
            return resp.json if isinstance(resp.json, list) else []
        return []

    async def list_releases(
        self, owner_repo: str, per_page: int = 30
    ) -> list[dict[str, Any]]:
        """List releases of a repository."""
        resp = await self.client.request(
            "GET",
            f"/repos/{owner_repo}/releases",
            params={"per_page": min(per_page, 100)},
        )
        if resp.ok:
            return resp.json if isinstance(resp.json, list) else []
        return []

    async def list_contributors(
        self, owner_repo: str, per_page: int = 30
    ) -> list[dict[str, Any]]:
        """List contributors of a repository."""
        resp = await self.client.request(
            "GET",
            f"/repos/{owner_repo}/contributors",
            params={"per_page": min(per_page, 100)},
        )
        if resp.ok:
            return resp.json if isinstance(resp.json, list) else []
        return []

    async def list_webhooks(
        self, owner_repo: str
    ) -> list[dict[str, Any]]:
        """List webhooks configured on a repository."""
        resp = await self.client.request(
            "GET", f"/repos/{owner_repo}/hooks"
        )
        if resp.ok:
            return resp.json if isinstance(resp.json, list) else []
        return []

    async def add_webhook(
        self,
        owner_repo: str,
        url: str,
        events: list[str] | None = None,
        active: bool = True,
    ) -> dict[str, Any] | None:
        """Add a webhook to a repository.

        Events: 'push', 'pull_request', 'issues', 'release', etc.
        """
        payload: dict[str, Any] = {
            "name": "web",
            "active": active,
            "events": events or ["push"],
            "config": {"url": url, "content_type": "json"},
        }
        resp = await self.client.request(
            "POST", f"/repos/{owner_repo}/hooks", json_body=payload
        )
        if resp.ok:
            return resp.json
        return None

    async def get_contents(
        self, owner_repo: str, path: str, ref: str = "main"
    ) -> dict[str, Any] | None:
        """Get file/directory contents via API (convenience wrapper)."""
        return await self.client.get_contents(
            "/".join(owner_repo.split("/")[:1]),
            "/".join(owner_repo.split("/")[1:]),
            path,
            ref,
        )
