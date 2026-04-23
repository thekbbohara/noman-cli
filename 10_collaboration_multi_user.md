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

### 10.4 Conflict Resolution (FIXED)

**Problem:** "Last-write-wins" silently loses data, no merge semantics for contradictory facts.

**Solution:** Semantic merge with user intervention for contradictions.

```python
# core/collaboration/conflicts.py

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List
from enum import Enum

class ConflictType(Enum):
    DIVERGENT_VALUES = "divergent_values"  # Same key, different values
    BOTH_MODIFIED = "both_modified"        # Both sides modified independently
    DELETED_VS_MODIFIED = "deleted_vs_modified"  # One deleted, other modified
    CONTRADICTORY_FACTS = "contradictory_facts"  # Facts that logically conflict


@dataclass
class SyncConflict:
    local_fact: dict
    remote_fact: dict
    conflict_type: ConflictType
    detected_at: datetime
    severity: str = "medium"  # low, medium, high, critical
    
    @property
    def requires_user_intervention(self) -> bool:
        """Determine if conflict needs human resolution."""
        return (
            self.conflict_type == ConflictType.CONTRADICTORY_FACTS or
            self.severity == "critical" or
            self.conflict_type == ConflictType.DELETED_VS_MODIFIED
        )


class ConflictResolver:
    """Resolve sync conflicts with semantic awareness."""
    
    def __init__(self, strategy: str = "semantic_merge"):
        self.strategy = strategy
        self.auto_resolvable = {
            ConflictType.DIVERGENT_VALUES: self._merge_divergent,
            ConflictType.BOTH_MODIFIED: self._merge_both_modified,
        }
    
    def resolve(self, conflict: SyncConflict) -> tuple[Optional[dict], bool]:
        """
        Resolve a conflict.
        
        Returns:
            (winning_fact_or_none, was_auto_resolved)
        """
        # Check if auto-resolvable
        if conflict.conflict_type in self.auto_resolvable and not conflict.requires_user_intervention:
            resolver = self.auto_resolvable[conflict.conflict_type]
            result = resolver(conflict)
            if result is not None:
                return result, True
        
        # Requires manual resolution
        return None, False
    
    def _merge_divergent(self, conflict: SyncConflict) -> Optional[dict]:
        """Merge divergent values by timestamp with metadata preservation."""
        local_time = datetime.fromisoformat(conflict.local_fact["timestamp"])
        remote_time = datetime.fromisoformat(conflict.remote_fact["timestamp"])
        
        # Keep newer value but preserve both in metadata
        winner = conflict.local_fact if local_time > remote_time else conflict.remote_fact
        loser = conflict.remote_fact if local_time > remote_time else conflict.local_fact
        
        # Add merge metadata
        winner["_merged_from"] = {
            "loser_value": loser.get("value"),
            "loser_timestamp": loser["timestamp"],
            "merge_strategy": "last-write-with-metadata",
            "merged_at": datetime.now().isoformat()
        }
        
        return winner
    
    def _merge_both_modified(self, conflict: SyncConflict) -> Optional[dict]:
        """Attempt semantic merge of independently modified facts."""
        # For simple value types, use last-write
        if isinstance(conflict.local_fact.get("value"), (str, int, float)):
            return self._merge_divergent(conflict)[0]
        
        # For complex types (dicts, lists), attempt merge
        if isinstance(conflict.local_fact.get("value"), dict) and \
           isinstance(conflict.remote_fact.get("value"), dict):
            return self._merge_dicts(
                conflict.local_fact["value"],
                conflict.remote_fact["value"],
                conflict.local_fact,
                conflict.remote_fact
            )
        
        # Cannot auto-merge, require user intervention
        return None
    
    def _merge_dicts(self, local: dict, remote: dict, local_meta: dict, remote_meta: dict) -> Optional[dict]:
        """Recursively merge dictionaries."""
        merged = {}
        all_keys = set(local.keys()) | set(remote.keys())
        
        for key in all_keys:
            if key in local and key in remote:
                if local[key] == remote[key]:
                    # No conflict
                    merged[key] = local[key]
                elif isinstance(local[key], dict) and isinstance(remote[key], dict):
                    # Recursive merge
                    sub_merged = self._merge_dicts(
                        local[key], remote[key], local_meta, remote_meta
                    )
                    if sub_merged is None:
                        return None  # Cannot merge at this level
                    merged[key] = sub_merged
                else:
                    # Conflict at leaf - use newer
                    local_time = datetime.fromisoformat(local_meta["timestamp"])
                    remote_time = datetime.fromisoformat(remote_meta["timestamp"])
                    merged[key] = local[key] if local_time > remote_time else remote[key]
            elif key in local:
                merged[key] = local[key]
            else:
                merged[key] = remote[key]
        
        return {"value": merged, "timestamp": datetime.now().isoformat()}
    
    def queue_for_review(self, conflict: SyncConflict):
        """Queue conflict for manual user resolution."""
        # Store in .noman/conflicts/ for later review
        ...


class ContradictionDetector:
    """Detect logically contradictory facts."""
    
    def __init__(self):
        # Rules for detecting contradictions
        self.contradiction_rules = [
            self._check_mutual_exclusion,
            self._check_temporal_impossibility,
            self._check_causal_violation,
        ]
    
    def detect_contradiction(self, fact1: dict, fact2: dict) -> bool:
        """Check if two facts are contradictory."""
        for rule in self.contradiction_rules:
            if rule(fact1, fact2):
                return True
        return False
    
    def _check_mutual_exclusion(self, fact1: dict, fact2: dict) -> bool:
        """Check if facts claim mutually exclusive states."""
        # Example: "file exists" vs "file deleted"
        # Implementation depends on fact schema
        return False
    
    def _check_temporal_impossibility(self, fact1: dict, fact2: dict) -> bool:
        """Check if facts violate temporal logic."""
        # Example: event B happened before event A, but B depends on A
        return False
    
    def _check_causal_violation(self, fact1: dict, fact2: dict) -> bool:
        """Check if facts violate causal relationships."""
        # Example: effect without cause
        return False
```

### 10.5 Implementation Tasks

| Task | File(s) | Priority | Dependencies | Change |
|------|---------|----------|--------------|--------|
| Sync protocol | `core/collaboration/protocol.py` | P2 | Memory system | — |
| **Contradiction detector** | `core/collaboration/contradictions.py` | **P1** | Memory system | ↑ NEW - Detect logical conflicts |
| **Semantic merge resolver** | `core/collaboration/conflicts.py` | **P1** | Memory system | ↑ Fixed last-write-wins data loss |
| Conflict detector | `core/collaboration/conflicts.py` | P2 | Memory system | ↓ Moved to P2 |
| Sync CLI | `cli/commands/collaboration.py` | P2 | CLI surface | — |
| Reference server | `servers/sync_server.py` | P3 | Sync protocol | — |
| **Conflict review UI** | `cli/commands/review_conflicts.py` | **P1** | Sync CLI | ↑ NEW - Manual resolution interface |

