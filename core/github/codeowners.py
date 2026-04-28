"""CODEOWNERS file management.

Provides parsing, validation, and update operations
for GitHub CODEOWNERS files.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CodeOwnerRule:
    """A single CODEOWNERS rule."""

    pattern: str
    owners: list[str]
    line_number: int = 0
    is_valid: bool = True
    comment: str = ""


class CODEOWNERSClient:
    """Manage CODEOWNERS files in GitHub repositories.

    Supports parsing, validation, and updating CODEOWNERS rules
    via both local file operations and the GitHub API.

    All methods are async. Requires a GitHubClient instance.
    """

    def __init__(self, github_client: "GitHubClient") -> None:
        self.client = github_client

    async def get_codeowners(
        self, owner_repo: str, ref: str = "main"
    ) -> list[CodeOwnerRule]:
        """Fetch and parse CODEOWNERS from a repository.

        Args:
            owner_repo: 'owner/repo' format.
            ref: Git ref (branch/tag/SHA) to read from.

        Returns:
            List of parsed CODEOWNERS rules.
        """
        contents = await self.client.get_contents(
            owner_repo.split("/")[0],
            "/".join(owner_repo.split("/")[1:]),
            "CODEOWNERS",
            ref,
        )
        if not contents or not isinstance(contents, dict):
            logger.warning("No CODEOWNERS found in %s", owner_repo)
            return []

        content = contents.get("content", "")
        if not content:
            return []

        # GitHub stores CODEOWNERS with base64 encoding
        import base64

        try:
            decoded = base64.b64decode(content).decode("utf-8")
        except Exception:
            decoded = content  # Already decoded

        return self.parse_codeowners(decoded)

    def parse_codeowners(self, content: str) -> list[CodeOwnerRule]:
        """Parse CODEOWNERS content string into rules.

        Handles:
        - Glob patterns (*, **, /path/, /*.ext)
        - Owner formats (@user, @org/team, user)
        - Comments (# ...)
        - Empty lines
        """
        rules: list[CodeOwnerRule] = []
        for line_num, line in enumerate(content.splitlines(), 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            # Split pattern and owners
            parts = stripped.split(None, 1)
            if len(parts) < 2:
                continue
            pattern = parts[0]
            owners_str = parts[1].strip()
            # Parse owners: @user, @org/team, user
            owners = self._parse_owners(owners_str)
            rules.append(
                CodeOwnerRule(
                    pattern=pattern,
                    owners=owners,
                    line_number=line_num,
                    is_valid=bool(owners),
                    comment=stripped if not owners else "",
                )
            )
        return rules

    def _parse_owners(self, owners_str: str) -> list[str]:
        """Parse owner string into list of owner identifiers."""
        # Remove inline comments
        comment_idx = owners_str.find("#")
        if comment_idx >= 0:
            owners_str = owners_str[:comment_idx]

        owners = []
        for token in owners_str.split():
            token = token.strip()
            if token.startswith("@"):
                owners.append(token)
            elif token:
                owners.append(token)
        return owners

    async def update_codeowners(
        self,
        owner_repo: str,
        rules: list[CodeOwnerRule],
        message: str = "Update CODEOWNERS",
        branch: str = "main",
    ) -> bool:
        """Update the CODEOWNERS file in a repository.

        Args:
            owner_repo: 'owner/repo' format.
            rules: List of CODEOWNERS rules.
            message: Commit message.
            branch: Branch to commit to.

        Returns:
            True if update succeeded.
        """
        content = "\n".join(
            f"{r.pattern} {' '.join(r.owners)}" for r in rules if r.is_valid
        )

        current = await self.client.get_contents(
            owner_repo.split("/")[0],
            "/".join(owner_repo.split("/")[1:]),
            "CODEOWNERS",
            branch,
        )

        sha = current.get("sha", "") if current else ""

        payload = {
            "message": message,
            "content": content.encode("utf-8").hex(),  # GitHub API expects hex
            "branch": branch,
        }
        if sha:
            payload["sha"] = sha

        resp = await self.client.request(
            "PUT",
            f"/repos/{owner_repo}/contents/CODEOWNERS",
            json_body=payload,
        )
        return resp.ok

    async def add_owner(
        self,
        owner_repo: str,
        pattern: str,
        owner: str,
        message: str = "Add CODEOWNERS rule",
        branch: str = "main",
    ) -> bool:
        """Add a single CODEOWNERS rule.

        Args:
            owner_repo: 'owner/repo' format.
            pattern: File/directory glob pattern.
            owner: Owner identifier (@user or @org/team).
            message: Commit message.
            branch: Branch to commit to.

        Returns:
            True if update succeeded.
        """
        rules = await self.get_codeowners(owner_repo, branch)
        # Check if rule already exists for this pattern
        existing = [r for r in rules if r.pattern == pattern]
        if existing:
            existing[0].owners.append(owner)
            return await self.update_codeowners(
                owner_repo, rules, message, branch
            )
        rules.append(
            CodeOwnerRule(
                pattern=pattern,
                owners=[owner],
                is_valid=True,
            )
        )
        return await self.update_codeowners(
            owner_repo, rules, message, branch
        )

    async def get_owners_for_path(
        self, path: str, rules: list[CodeOwnerRule]
    ) -> list[str]:
        """Get CODEOWNERS for a given file path.

        Matches rules from most specific to least specific.
        """
        owners: list[str] = []
        seen: set[str] = set()

        for rule in rules:
            if self._pattern_matches(rule.pattern, path):
                for owner in rule.owners:
                    if owner not in seen:
                        owners.append(owner)
                        seen.add(owner)
        return owners

    def _pattern_matches(self, pattern: str, path: str) -> bool:
        """Check if a CODEOWNERS glob pattern matches a path."""
        # Normalize paths
        pattern = pattern.strip().lstrip("/")
        path = path.strip().lstrip("/")

        # Exact match
        if pattern == path:
            return True

        # Directory match
        if pattern.endswith("/"):
            return path.startswith(pattern) or path.startswith(pattern.rstrip("/")) + "/"

        # Glob patterns
        if "**" in pattern:
            # Convert ** to regex
            regex = pattern.replace("**/", ".*").replace("**", ".*")
            regex = f"^{regex}$"
            return bool(re.match(regex, path, re.IGNORECASE))

        if "*" in pattern:
            regex = pattern.replace(".", r"\.").replace("*", "[^/]*")
            regex = f"^{regex}$"
            return bool(re.match(regex, path, re.IGNORECASE))

        return False

    async def validate_codeowners(
        self, owner_repo: str, ref: str = "main"
    ) -> dict[str, Any]:
        """Validate CODEOWNERS rules in a repository.

        Returns:
            Validation report with errors and warnings.
        """
        rules = await self.get_codeowners(owner_repo, ref)
        errors: list[str] = []
        warnings: list[str] = []

        for rule in rules:
            if not rule.is_valid:
                errors.append(
                    f"Line {rule.line_number}: No valid owners for pattern '{rule.pattern}'"
                )
            # Check pattern syntax
            if not any(c in rule.pattern for c in ["*", "/", ".", "@"]):
                warnings.append(
                    f"Line {rule.line_number}: Pattern '{rule.pattern}' may not match any files"
                )

        return {
            "valid": len(errors) == 0,
            "rules_count": len(rules),
            "errors": errors,
            "warnings": warnings,
        }
