# Profiles Reference

## Overview

Profiles allow you to run multiple independent NoMan instances with isolated configs, sessions, skills, and memory.

## CLI Commands

```bash
noman profile list                  # List all profiles
noman profile create NAME           # Create a new profile
noman profile use NAME              # Set active profile
noman profile delete NAME           # Delete a profile
noman profile show NAME             # Show profile details
noman profile export NAME           # Export profile to tar.gz
noman profile import FILE           # Import profile from archive
noman profile rename A B            # Rename a profile
noman profile alias NAME            # Create wrapper script
```

## Configuration

```toml
[profiles.default]
model = "gpt-4o"
provider = "openai"

[profiles.dev]
model = "claude-3-opus"
provider = "anthropic"
```
