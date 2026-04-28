# Cron Reference

## Overview

NoMan includes a built-in cron scheduler for automating tasks.

## Configuration

```toml
[cron]
enabled = true
port = 9090
timezone = "UTC"
max_jobs = 100

[cron.retry]
max_attempts = 3
backoff_sec = 5.0
```

## CLI Commands

```bash
noman cron list              # List all jobs
noman cron create "30m"      # Create job (runs every 30 minutes)
noman cron create "0 9 * * *"  # Create job (runs at 9 AM daily)
noman cron edit <id>         # Edit a job
noman cron pause <id>        # Pause a job
noman cron resume <id>       # Resume a job
noman cron remove <id>       # Delete a job
noman cron run <id>          # Trigger job now
noman cron status            # Show scheduler status
```

## Job Types

| Type | Schedule Format | Example |
|------|----------------|---------|
| Cron | Standard 5-field | `0 9 * * *` |
| Interval | Human-readable | `30m`, `2h`, `1d` |
| One-shot | `once` | Run once |
| Repeat | `once` + repeat count | Run N times |

## Delivery

Jobs can deliver results to:
- `origin` - Back to the originating platform
- `local` - Save to file
- `gateway:chat_id` - To a specific channel
