# Delegation Reference

## Overview

NoMan supports spawning independent worker processes for parallel task execution.

## CLI Commands

```bash
noman delegate "goal description" --context "context" --toolsets terminal,file
noman delegate list             # List active delegations
noman delegate status <id>      # Check delegation status
noman delegate cancel <id>      # Cancel a delegation
```

## Features

- Independent worker processes
- Parallel task execution
- Context propagation (files, tools, environment)
- Result aggregation
- Worker lifecycle management
- Graceful failure handling
