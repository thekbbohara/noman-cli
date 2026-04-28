# GitHub Reference

## Overview

NoMan supports GitHub integration for issues, PRs, repos, and actions.

## CLI Commands

```bash
noman github issues list --repo owner/repo
noman github issues create --repo owner/repo --title "Fix bug"
noman github prs list --repo owner/repo
noman github prs create --repo owner/repo --base main --head feature-branch
noman github repos list
noman github actions run --repo owner/repo --workflow ci.yml
```

## Features

- Issue management (create, list, update, close)
- PR management (create, list, review, merge)
- Repository management (clone, fork, list)
- GitHub Actions (run workflows, check status)
- CODEOWNERS management
- Code search
