## 10. Collaboration & Multi-User

### 10.1 Team Memory Sync Architecture

```
┌─────────────────┐         HTTPS          ┌─────────────────┐
│   User A        │                        │   Sync Server   │
│   noman         │ ◄────────────────────► │   (optional)    │
│   memory.db     │                        │                 │
└─────────────────┘                        └────────┬────────┘
                                                   │
                                          ┌────────▼────────┐
                                          │   User B        │
                                          │   noman         │
                                          │   memory.db     │
                                          └─────────────────┘
```

### 10.2 Sync Configuration

```toml
# user/config.toml

[collaboration]
team_id = "acme-corp/engineering"
sync_endpoint = "https://internal-noman.acme.com/sync"
auth_token = "${NOMAN_TEAM_TOKEN}"
push_on_session_end = true
pull_on_init = true
conflict_resolution = "last-write-wins"  # or "manual"

[sync_filters]
# What to sync
include_tiers = ["semantic", "procedural"]
exclude_tiers = ["episodic"]
include_scopes = ["project", "team"]
exclude_scopes = ["personal"]
```

### 10.3 Conflict Resolution

```python
# core/collaboration/conflicts.py

from dataclasses import dataclass
from datetime import datetime

@dataclass
class SyncConflict:
    local_fact: dict
    remote_fact: dict
    conflict_type: str  # "divergent_values", "both_modified", "deleted_vs_modified"
    detected_at: datetime

class ConflictResolver:
    """Resolve sync conflicts."""
    
    def __init__(self, strategy: str = "last-write-wins"):
        self.strategy = strategy
    
    def resolve(self, conflict: SyncConflict) -> dict | None:
        """Return winning fact, or None to delete."""
        
        if self.strategy == "last-write-wins":
            local_time = datetime.fromisoformat(conflict.local_fact["timestamp"])
            remote_time = datetime.fromisoformat(conflict.remote_fact["timestamp"])
            return conflict.local_fact if local_time > remote_time else conflict.remote_fact
        
        elif self.strategy == "manual":
            # Queue for user resolution
            queue_for_review(conflict)
            return None
        
        elif self.strategy == "merge":
            # Attempt semantic merge (for compatible facts)
            return self._try_merge(conflict)
```

### 10.4 Implementation Tasks

| Task | File(s) | Priority | Dependencies |
|------|---------|----------|--------------|
| Sync protocol | `core/collaboration/protocol.py` | P2 | Memory system |
| Conflict detector | `core/collaboration/conflicts.py` | P2 | Memory system |
| Sync CLI | `cli/commands/collaboration.py` | P2 | CLI surface |
| Reference server | `servers/sync_server.py` | P3 | Sync protocol |

---

