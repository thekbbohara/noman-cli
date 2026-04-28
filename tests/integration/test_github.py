"""Integration tests for GitHub integration."""

import pytest


async def test_github_client():
    """Test GitHubClient."""
    from core.github.client import GitHubClient
    client = GitHubClient()
    assert client is not None


async def test_github_issues():
    """Test issues module."""
    from core.github.issues import IssuesManager
    assert IssuesManager is not None


async def test_github_prs():
    """Test PRs module."""
    from core.github.prs import PRsManager
    assert PRsManager is not None
