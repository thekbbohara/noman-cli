# Gateway Reference

## Overview

NoMan supports multiple platform gateways that allow you to interact with the agent from different channels.

## Supported Platforms

| Platform | Status | Config Key |
|----------|--------|------------|
| Telegram | ✅ | `gateway.telegram` |
| Discord | ✅ | `gateway.discord` |
| Slack | ✅ | `gateway.slack` |
| WhatsApp | ✅ | `gateway.whatsapp` |
| Signal | ✅ | `gateway.signal` |
| Matrix | ✅ | `gateway.matrix` |
| Webhook | ✅ | `gateway.webhook` |
| Feishu/Lark | ✅ | `gateway.feishu` |
| WeChat | ✅ | `gateway.wechat` |
| Home Assistant | ✅ | `gateway.homeassistant` |

## Configuration

```toml
[gateway.telegram]
enabled = true
bot_token = "your-bot-token"
allowed_users = ["user123"]
rate_limit = 1.0

[gateway.discord]
enabled = true
bot_token = "your-discord-token"

[gateway.webhook]
enabled = true
port = 9090
auth_token = "your-secret"
```

## CLI Commands

```bash
noman gateway run            # Start configured gateways
noman gateway status         # Show gateway status
noman gateway setup          # Interactive configuration wizard
noman gateway install        # Install as background service
noman gateway start/stop/restart
```

## Slash Commands

All gateways support these slash commands:

- `/help` - Show help
- `/reset` - Reset current session
- `/status` - Show session status
- `/model` - Switch LLM provider
- `/sessions` - List active sessions
