## 9. Performance Optimization

### 9.1 Caching Strategy

```python
# core/utils/cache.py

from functools import lru_cache
from pathlib import Path
import hashlib

class LayeredCache:
    """Multi-layer caching strategy."""
    
    def __init__(self, cache_dir: str, memory_limit_mb: int = 256):
        self.cache_dir = Path(cache_dir)
        self.memory_limit = memory_limit_mb * 1024 * 1024
        self.lru = lru_cache(maxsize=1000)  # In-memory LRU
        self.disk_index = {}  # Disk cache index
    
    def get(self, key: str) -> any | None:
        """Get cached value."""
        # Try memory first
        if key in self.lru:
            return self.lru[key]
        
        # Try disk
        if key in self.disk_index:
            path = self.cache_dir / self.disk_index[key]
            if path.exists():
                value = pickle.loads(path.read_bytes())
                self.lru[key] = value  # Promote to memory
                return value
        
        return None
    
    def set(self, key: str, value: any, ttl_hours: int = 24):
        """Cache a value."""
        self.lru[key] = value
        
        # Also write to disk for persistence
        hash_key = hashlib.sha256(key.encode()).hexdigest()[:16]
        path = self.cache_dir / hash_key
        path.write_bytes(pickle.dumps(value))
        self.disk_index[key] = hash_key
```

### 9.2 Parallelization Opportunities

| Operation | Parallelizable | Strategy |
|-----------|---------------|----------|
| Tree-sitter parsing | Yes | Parse files concurrently (async pool) |
| PageRank computation | Partial | Parallel iteration, synchronized convergence |
| Fact extraction | Yes | Process traces in background worker |
| Embedding generation | Yes | Batch embeddings, parallel API calls |
| Trace analysis | Yes | Multiple critics analyze different traces |

### 9.3 Memory Footprint Targets

| Component | Target | Measurement |
|-----------|--------|-------------|
| Skeleton cache | <50MB for 50k LOC | RSS memory |
| SQLite database | <500MB | File size |
| Vector index | <200MB | sqlite-vec index size |
| In-flight traces | <100MB | Session peak |
| **Total target** | **<1GB** | Typical workload |

### 9.4 Implementation Tasks

| Task | File(s) | Priority | Dependencies |
|------|---------|----------|--------------|
| Layered cache | `core/utils/cache.py` | P0 | None |
| Async parsing pool | `core/context/parser_pool.py` | P1 | Context mgmt |
| Background workers | `core/utils/workers.py` | P1 | None |
| Memory profiler | `scripts/profile_memory.py` | P2 | None |
| Benchmark harness | `tests/benchmarks/performance.py` | P1 | Testing framework |

---

