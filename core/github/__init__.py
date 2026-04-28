"""GitHub integration module.

Provides GitHub API client, issue management, PR workflow,
repository operations, Actions orchestration, CODEOWNERS management,
and code/search API access.
"""

from __future__ import annotations

from core.github.client import GitHubClient
from core.github.issues import IssuesClient
from core.github.prs import PRsClient
from core.github.repos import ReposClient
from core.github.actions import ActionsClient
from core.github.codeowners import CODEOWNERSClient
from core.github.search import SearchClient

__all__ = [
    "GitHubClient",
    "IssuesClient",
    "PRsClient",
    "ReposClient",
    "ActionsClient",
    "CODEOWNERSClient",
    "SearchClient",
]
