"""Handler functions for common webhook types.

Provides handlers for popular webhook services:
- GitHub: push, pull_request, issues, etc.
- GitLab: push, merge_request, etc.
- Generic: catch-all handler for any webhook source
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from core.cron.jobs import CronJob
from core.webhooks.subscriptions import WebhookSubscription

logger = logging.getLogger(__name__)


class WebhookHandler:
    """Base handler for webhook payloads."""

    def handle(
        self,
        subscription: WebhookSubscription,
        payload: Any,
        event_type: str | None = None,
    ) -> list[CronJob]:
        """Handle a webhook event and create corresponding jobs.

        Args:
            subscription: The matched WebhookSubscription.
            payload: The parsed webhook payload.
            event_type: The event type string.

        Returns:
            List of CronJobs to execute.
        """
        raise NotImplementedError


class GitHubHandler(WebhookHandler):
    """Handler for GitHub webhook events.

    Supports events: push, pull_request, issues, issue_comment,
    pull_request_review, workflow_run, release, fork, watch.
    """

    EVENT_MAP: dict[str, str] = {
        "push": "github-push",
        "pull_request": "github-pr",
        "issues": "github-issues",
        "issue_comment": "github-issue-comment",
        "pull_request_review": "github-pr-review",
        "workflow_run": "github-workflow",
        "release": "github-release",
        "fork": "github-fork",
        "watch": "github-watch",
        "star": "github-star",
    }

    def handle(
        self,
        subscription: WebhookSubscription,
        payload: Any,
        event_type: str | None = None,
    ) -> list[CronJob]:
        """Handle a GitHub webhook event.

        Args:
            subscription: The matched subscription.
            payload: The GitHub webhook payload.
            event_type: The GitHub event type.

        Returns:
            Empty list (GitHub webhooks typically trigger external actions).
        """
        if event_type:
            logger.info("GitHub webhook event: %s", event_type)

        # GitHub webhook payloads contain a 'action' and 'repository' key
        # We can extract relevant info for logging/reporting
        repo = None
        action = None
        if isinstance(payload, dict):
            repo = payload.get("repository", {})
            action = payload.get("action")

        repo_name = f"{repo.get('full_name', 'unknown')}" if repo else "unknown"
        logger.info(
            "GitHub event: %s on %s (action: %s)",
            event_type,
            repo_name,
            action,
        )

        return []


class GitLabHandler(WebhookHandler):
    """Handler for GitLab webhook events.

    Supports events: push, merge_request, tag_push, issue, note.
    """

    EVENT_MAP: dict[str, str] = {
        "push": "gitlab-push",
        "merge_request": "gitlab-mr",
        "tag_push": "gitlab-tag-push",
        "issue": "gitlab-issue",
        "note": "gitlab-note",
        "wiki_page": "gitlab-wiki",
    }

    def handle(
        self,
        subscription: WebhookSubscription,
        payload: Any,
        event_type: str | None = None,
    ) -> list[CronJob]:
        """Handle a GitLab webhook event.

        Args:
            subscription: The matched subscription.
            payload: The GitLab webhook payload.
            event_type: The GitLab event type.

        Returns:
            Empty list (GitLab webhooks typically trigger external actions).
        """
        if event_type:
            logger.info("GitLab webhook event: %s", event_type)

        project = payload.get("project", {}) if isinstance(payload, dict) else {}
        project_name = project.get("name", "unknown")
        logger.info(
            "GitLab event: %s on %s",
            event_type,
            project_name,
        )

        return []


class BitbucketHandler(WebhookHandler):
    """Handler for Bitbucket webhook events."""

    EVENT_MAP: dict[str, str] = {
        "repo:push": "bitbucket-push",
        "pullrequest:created": "bitbucket-pr-created",
        "pullrequest:updated": "bitbucket-pr-updated",
        "pullrequest:fulfilled": "bitbucket-pr-merged",
        "pullrequest:rejected": "bitbucket-pr-rejected",
    }

    def handle(
        self,
        subscription: WebhookSubscription,
        payload: Any,
        event_type: str | None = None,
    ) -> list[CronJob]:
        """Handle a Bitbucket webhook event.

        Args:
            subscription: The matched subscription.
            payload: The Bitbucket webhook payload.
            event_type: The Bitbucket event type.

        Returns:
            Empty list.
        """
        if event_type:
            logger.info("Bitbucket webhook event: %s", event_type)
        return []


class GenericHandler(WebhookHandler):
    """Generic handler for arbitrary webhook payloads.

    Useful for webhooks from services that don't have a specialized
    handler. Logs the event and payload for inspection.
    """

    def handle(
        self,
        subscription: WebhookSubscription,
        payload: Any,
        event_type: str | None = None,
    ) -> list[CronJob]:
        """Handle a generic webhook event.

        Args:
            subscription: The matched subscription.
            payload: The webhook payload.
            event_type: The event type.

        Returns:
            Empty list (generic handler logs but doesn't create jobs).
        """
        payload_str = ""
        if isinstance(payload, bytes):
            try:
                payload_str = payload.decode("utf-8")
            except UnicodeDecodeError:
                payload_str = f"<binary: {len(payload)} bytes>"
        elif isinstance(payload, dict):
            payload_str = json.dumps(payload, indent=2, default=str)

        logger.info(
            "Generic webhook event: %s (subscription: %s)\n%s",
            event_type or "unknown",
            subscription.name,
            payload_str[:2000],
        )

        return []


def get_handler(source: str) -> WebhookHandler:
    """Get the appropriate handler for a webhook source.

    Args:
        source: Webhook source name ('github', 'gitlab', 'bitbucket', 'generic').

    Returns:
        The appropriate WebhookHandler instance.

    Raises:
        ValueError: If the source is not recognized.
    """
    handlers: dict[str, WebhookHandler] = {
        "github": GitHubHandler(),
        "gitlab": GitLabHandler(),
        "bitbucket": BitbucketHandler(),
        "generic": GenericHandler(),
    }

    source_lower = source.lower().strip()
    handler = handlers.get(source_lower)
    if handler is None:
        logger.warning("Unknown webhook source '%s', using generic handler", source)
        return GenericHandler()
    return handler


def detect_source(payload: Any) -> str:
    """Detect the webhook source from the payload.

    Examines common headers and payload structure to determine
    the source of the webhook.

    Args:
        payload: The webhook payload (dict or bytes).

    Returns:
        The detected source name ('github', 'gitlab', 'bitbucket', 'generic').
    """
    # Check headers if payload is a dict
    if isinstance(payload, dict):
        headers = payload.get("headers", {})
        if isinstance(headers, dict):
            if headers.get("X-GitHub-Event"):
                return "github"
            if headers.get("X-Gitlab-Event"):
                return "gitlab"
            if headers.get("X-Event-Key"):
                return "bitbucket"
            if headers.get("X-Hub-Signature-256"):
                return "github"

        # Check payload keys
        if "ref" in payload and "repository" in payload:
            if "pusher" in payload:
                return "github"
            return "generic"
        if "project" in payload and "checkout_pages" in payload:
            return "gitlab"

    # Check if payload is bytes with known headers
    if isinstance(payload, bytes):
        payload_str = payload.decode("utf-8", errors="ignore")
        if "X-GitHub-Event" in payload_str:
            return "github"
        if "X-Gitlab-Event" in payload_str:
            return "gitlab"

    return "generic"
