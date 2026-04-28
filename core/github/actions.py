"""GitHub Actions management.

Provides workflow run, status, and configuration operations.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class WorkflowRun:
    """GitHub Actions workflow run."""

    id: int
    name: str
    status: str  # completed, in_progress, queued, etc.
    conclusion: str | None  # success, failure, cancelled, etc.
    head_branch: str = ""
    head_sha: str = ""
    run_number: int = 0
    event: str = ""
    created_at: str = ""
    updated_at: str = ""
    run_attempt: int = 1
    url: str = ""
    html_url: str = ""
    actor: str = ""
    repository: str = ""

    @property
    def is_completed(self) -> bool:
        return self.conclusion is not None

    @property
    def is_success(self) -> bool:
        return self.conclusion == "success"

    @property
    def is_failed(self) -> bool:
        return self.conclusion == "failure"


@dataclass
class Workflow:
    """GitHub Actions workflow definition."""

    id: int
    name: str
    path: str
    state: str  # active, disabled_manually, disabled_inactivity
    branch: str = "main"
    branch_url: str = ""
    created_at: str = ""
    updated_at: str = ""
    url: str = ""
    html_url: str = ""
    html_url_alt: str = ""
    repository: str = ""


class ActionsClient:
    """Manage GitHub Actions workflows and runs.

    All methods are async. Requires a GitHubClient instance.
    """

    def __init__(self, github_client: "GitHubClient") -> None:
        self.client = github_client

    # ── Workflow runs ──

    async def list_runs(
        self,
        owner_repo: str,
        workflow_id: int | str | None = None,
        branch: str | None = None,
        status: str | None = None,
        event: str | None = None,
        actor: str | None = None,
        per_page: int = 25,
    ) -> list[WorkflowRun]:
        """List workflow runs.

        Args:
            owner_repo: 'owner/repo' format.
            workflow_id: Filter by workflow ID or filename.
            branch: Filter by branch.
            status: 'completed', 'in_progress', 'queued', 'requested', etc.
            event: Filter by event type ('push', 'pull_request', etc.).
            actor: Filter by actor username.
            per_page: Results per page (max 100).

        Returns:
            List of WorkflowRun objects.
        """
        if workflow_id is not None:
            path = f"/repos/{owner_repo}/actions/workflows/{workflow_id}/runs"
        else:
            path = f"/repos/{owner_repo}/actions/runs"

        params: dict[str, Any] = {"per_page": min(per_page, 100)}
        if branch:
            params["branch"] = branch
        if status:
            params["status"] = status
        if event:
            params["event"] = event
        if actor:
            params["actor"] = actor

        resp = await self.client.request("GET", path, params=params)
        if not resp.ok:
            return []

        data = resp.json if isinstance(resp.json, dict) else {}
        runs = data.get("workflow_runs", data if isinstance(data, list) else [])
        return [
            WorkflowRun(
                id=item.get("id", 0),
                name=item.get("name", ""),
                status=item.get("status", ""),
                conclusion=item.get("conclusion"),
                head_branch=item.get("head_branch", ""),
                head_sha=item.get("head_sha", ""),
                run_number=item.get("run_number", 0),
                event=item.get("event", ""),
                created_at=item.get("created_at", ""),
                updated_at=item.get("updated_at", ""),
                run_attempt=item.get("run_attempt", 1),
                url=item.get("html_url", ""),
                html_url=item.get("html_url", ""),
                actor=item.get("actor", {}).get("login", ""),
                repository=owner_repo,
            )
            for item in runs
        ]

    async def get_run(
        self, owner_repo: str, run_id: int
    ) -> WorkflowRun | None:
        """Get a specific workflow run."""
        resp = await self.client.request(
            "GET", f"/repos/{owner_repo}/actions/runs/{run_id}"
        )
        if not resp.ok:
            return None
        data = resp.json
        return WorkflowRun(
            id=data.get("id", 0),
            name=data.get("name", ""),
            status=data.get("status", ""),
            conclusion=data.get("conclusion"),
            head_branch=data.get("head_branch", ""),
            head_sha=data.get("head_sha", ""),
            run_number=data.get("run_number", 0),
            event=data.get("event", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            url=data.get("html_url", ""),
            html_url=data.get("html_url", ""),
            actor=data.get("actor", {}).get("login", ""),
            repository=owner_repo,
        )

    async def rerun_run(
        self, owner_repo: str, run_id: int
    ) -> bool:
        """Rerun a workflow run."""
        resp = await self.client.request(
            "POST", f"/repos/{owner_repo}/actions/runs/{run_id}/rerun"
        )
        return resp.ok

    async def cancel_run(
        self, owner_repo: str, run_id: int
    ) -> bool:
        """Cancel a running workflow run."""
        resp = await self.client.request(
            "POST", f"/repos/{owner_repo}/actions/runs/{run_id}/cancel"
        )
        return resp.ok

    async def get_logs(
        self, owner_repo: str, run_id: int
    ) -> str | None:
        """Get the combined logs for a workflow run."""
        resp = await self.client.request(
            "GET", f"/repos/{owner_repo}/actions/runs/{run_id}/logs"
        )
        if resp.ok:
            return resp.data  # raw text logs
        return None

    # ── Workflow dispatch ──

    async def dispatch(
        self,
        owner_repo: str,
        workflow_id: int | str,
        ref: str,
        inputs: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Dispatch a workflow run.

        Args:
            owner_repo: 'owner/repo' format.
            workflow_id: Workflow filename or ID.
            ref: Git ref (branch, tag, or SHA) to trigger on.
            inputs: Workflow input parameters.

        Returns:
            Run data on success, None on failure.
        """
        payload: dict[str, Any] = {"ref": ref}
        if inputs:
            payload["inputs"] = inputs

        resp = await self.client.request(
            "POST",
            f"/repos/{owner_repo}/actions/workflows/{workflow_id}/dispatches",
            json_body=payload,
        )
        if resp.ok:
            return resp.json
        logger.error("Failed to dispatch workflow: %d", resp.status_code)
        return None

    # ── Workflow definitions ──

    async def list_workflows(
        self, owner_repo: str, per_page: int = 25
    ) -> list[Workflow]:
        """List all workflows in a repository."""
        resp = await self.client.request(
            "GET",
            f"/repos/{owner_repo}/actions/workflows",
            params={"per_page": min(per_page, 100)},
        )
        if not resp.ok:
            return []
        data = resp.json if isinstance(resp.json, dict) else {}
        workflows = data.get("workflows", [])
        return [
            Workflow(
                id=w.get("id", 0),
                name=w.get("name", ""),
                path=w.get("path", ""),
                state=w.get("state", "active"),
                branch=w.get("branch", {}).get("name", "")
                if w.get("branch")
                else "main",
                branch_url=w.get("branch", {}).get("url", "")
                if w.get("branch")
                else "",
                created_at=w.get("created_at", ""),
                updated_at=w.get("updated_at", ""),
                url=w.get("url", ""),
                html_url=w.get("html_url", ""),
                repository=owner_repo,
            )
            for w in workflows
        ]

    async def get_workflow(
        self, owner_repo: str, workflow_id: int | str
    ) -> Workflow | None:
        """Get a specific workflow definition."""
        resp = await self.client.request(
            "GET", f"/repos/{owner_repo}/actions/workflows/{workflow_id}"
        )
        if not resp.ok:
            return None
        data = resp.json
        return Workflow(
            id=data.get("id", 0),
            name=data.get("name", ""),
            path=data.get("path", ""),
            state=data.get("state", "active"),
            repository=owner_repo,
        )

    async def list_artifacts(
        self, owner_repo: str, run_id: int | None = None, per_page: int = 25
    ) -> list[dict[str, Any]]:
        """List artifacts for a workflow run."""
        path = (
            f"/repos/{owner_repo}/actions/runs/{run_id}/artifacts"
            if run_id
            else f"/repos/{owner_repo}/actions/artifacts"
        )
        resp = await self.client.request(
            "GET", path, params={"per_page": min(per_page, 100)}
        )
        if resp.ok:
            data = resp.json if isinstance(resp.json, dict) else {}
            return data.get("artifacts", [])
        return []

    async def download_artifact(
        self, owner_repo: str, artifact_id: int
    ) -> str | None:
        """Get the download URL for an artifact."""
        resp = await self.client.request(
            "GET", f"/repos/{owner_repo}/actions/artifacts/{artifact_id}/archive"
        )
        if resp.ok:
            # The response is a redirect to the actual download URL
            return resp.headers.get("location") or resp.headers.get("x-artifact-url")
        return None

    async def get_job_logs(
        self, owner_repo: str, run_id: int, job_id: int
    ) -> str | None:
        """Get logs for a specific job within a run."""
        resp = await self.client.request(
            "GET",
            f"/repos/{owner_repo}/actions/jobs/{job_id}/logs",
        )
        if resp.ok:
            return resp.data
        return None
