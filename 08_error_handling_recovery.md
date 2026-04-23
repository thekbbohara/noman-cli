## 8. Error Handling & Recovery

### 8.1 Error Categories

```python
# core/errors.py

from enum import Enum

class ErrorCategory(Enum):
    TRANSIENT = "transient"      # Retry will likely succeed
    CONFIG = "config"            # User must fix configuration
    PERMISSION = "permission"    # User must grant permission
    MODEL = "model"              # LLM error, may need fallback
    SANDBOX = "sandbox"          # Security violation
    INTERNAL = "internal"        # Bug in NoMan itself

class NoManError(Exception):
    """Base exception for NoMan."""
    
    def __init__(
        self,
        message: str,
        category: ErrorCategory,
        recoverable: bool = False,
        suggestions: list[str] = None
    ):
        super().__init__(message)
        self.category = category
        self.recoverable = recoverable
        self.suggestions = suggestions or []

class TransientError(NoManError):
    """Network timeout, rate limit, etc."""
    def __init__(self, message: str, retry_after: int = None):
        super().__init__(
            message,
            ErrorCategory.TRANSIENT,
            recoverable=True,
            suggestions=["Retry after delay"]
        )
        self.retry_after = retry_after

class ModelError(NoManError):
    """LLM returned invalid response."""
    def __init__(self, message: str, fallback_provider: str = None):
        super().__init__(
            message,
            ErrorCategory.MODEL,
            recoverable=bool(fallback_provider),
            suggestions=[f"Switch to {fallback_provider}"] if fallback_provider else []
        )
```

### 8.2 Checkpoint & Resume

```python
# core/orchestrator/checkpoint.py

import json
from pathlib import Path

@dataclass
class Checkpoint:
    session_id: str
    turn_id: int
    conversation_state: list
    memory_state: dict
    context_state: dict
    timestamp: str

class CheckpointManager:
    """Save and restore session state."""
    
    def __init__(self, checkpoint_dir: str):
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
    
    def save(self, checkpoint: Checkpoint):
        """Save checkpoint to disk."""
        path = self.checkpoint_dir / f"{checkpoint.session_id}.json"
        path.write_text(json.dumps(self._serialize(checkpoint)))
    
    def load(self, session_id: str) -> Checkpoint | None:
        """Load latest checkpoint for session."""
        path = self.checkpoint_dir / f"{session_id}.json"
        if not path.exists():
            return None
        return self._deserialize(json.loads(path.read_text()))
    
    def resume(self, session_id: str, orchestrator) -> bool:
        """Resume session from checkpoint."""
        checkpoint = self.load(session_id)
        if not checkpoint:
            return False
        
        orchestrator.restore_state(checkpoint)
        return True
```

### 8.3 Implementation Tasks

| Task | File(s) | Priority | Dependencies |
|------|---------|----------|--------------|
| Error hierarchy | `core/errors.py` | P0 | None |
| Retry logic | `core/utils/retry.py` | P0 | Errors |
| Checkpoint manager | `core/orchestrator/checkpoint.py` | P1 | Orchestrator |
| Rollback mechanism | `core/selfimprove/rollback.py` | P1 | Self-improve |
| Error reporting | `cli/commands/report.py` | P2 | Observability |

---

