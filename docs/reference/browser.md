# Browser Reference

## Overview

NoMan supports browser automation via Playwright for web interaction.

## Features

- Headless and headed browser modes
- Persistent browser contexts (cookies, localStorage)
- Screenshot capture
- DOM snapshot extraction
- Element interaction (click, type, fill)
- Navigation and waiting
- Network interception
- Auto-reconnect

## CLI Commands

```bash
noman browser run --url https://example.com    # Open browser
noman browser screenshot --url https://example.com  # Take screenshot
noman browser snapshot --url https://example.com   # Extract DOM
```
