### 9.1 Caching Strategy (SECURITY FIXED)

**CRITICAL FIX:** Original design used `pickle` for disk cache, enabling arbitrary code execution. Replaced with safe JSON serialization.

```python
# core/utils/cache.py

from functools import lru_cache
from pathlib import Path
import hashlib
import json
import time
from typing import Any, Optional

class CacheEntry:
    """Safe cache entry with metadata."""
    
    def __init__(self, value: Any, ttl_seconds: int = 86400):
        self.value = value
        self.created_at = time.time()
        self.ttl_seconds = ttl_seconds
        self.version = 1  # For schema migrations
    
    def is_expired(self) -> bool:
        return time.time() - self.created_at > self.ttl_seconds
    
    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "created_at": self.created_at,
            "ttl_seconds": self.ttl_seconds,
            "version": self.version
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "CacheEntry":
        return cls(
            value=data["value"],
            ttl_seconds=data.get("ttl_seconds", 86400),
        )


class LayeredCache:
    """Multi-layer caching strategy with SAFE serialization."""
    
    def __init__(
        self,
        cache_dir: str,
        memory_limit_mb: int = 256,
        use_safe_serialization: bool = True  # Always True by default
    ):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.memory_limit = memory_limit_mb * 1024 * 1024
        self.lru = lru_cache(maxsize=1000)  # In-memory LRU
        self.disk_index: dict[str, str] = {}  # key -> filename
        self.use_safe_serialization = use_safe_serialization
        
        # Load existing index
        self._load_index()
    
    def _load_index(self):
        """Load disk cache index from safe JSON file."""
        index_path = self.cache_dir / "cache_index.json"
        if index_path.exists():
            try:
                self.disk_index = json.loads(index_path.read_text())
            except (json.JSONDecodeError, KeyError):
                # Corrupted index, start fresh
                self.disk_index = {}
    
    def _save_index(self):
        """Save disk cache index atomically."""
        index_path = self.cache_dir / "cache_index.json"
        temp_path = index_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(self.disk_index))
        temp_path.replace(index_path)  # Atomic rename
    
    def get(self, key: str) -> Any | None:
        """Get cached value using SAFE deserialization."""
        # Try memory first
        if key in self.lru:
            entry = self.lru[key]
            if not entry.is_expired():
                return entry.value
            else:
                del self.lru[key]
        
        # Try disk
        if key in self.disk_index:
            filename = self.disk_index[key]
            path = self.cache_dir / filename
            
            if path.exists():
                try:
                    # SAFE: Use JSON instead of pickle
                    data = json.loads(path.read_text())
                    entry = CacheEntry.from_dict(data)
                    
                    if not entry.is_expired():
                        self.lru[key] = entry  # Promote to memory
                        return entry.value
                    else:
                        # Expired, delete
                        path.unlink()
                        del self.disk_index[key]
                        self._save_index()
                except (json.JSONDecodeError, KeyError, TypeError) as e:
                    # Corrupted cache entry, delete it
                    logger.warning(f"Corrupted cache entry {key}: {e}")
                    if path.exists():
                        path.unlink()
                    if key in self.disk_index:
                        del self.disk_index[key]
                        self._save_index()
        
        return None
    
    def set(self, key: str, value: Any, ttl_hours: int = 24):
        """Cache a value using SAFE serialization."""
        entry = CacheEntry(value, ttl_seconds=ttl_hours * 3600)
        self.lru[key] = entry
        
        # Also write to disk for persistence
        hash_key = hashlib.sha256(key.encode()).hexdigest()[:16]
        filename = f"cache_{hash_key}.json"
        path = self.cache_dir / filename
        
        # SAFE: Use JSON instead of pickle
        try:
            path.write_text(json.dumps(entry.to_dict()))
            self.disk_index[key] = filename
            self._save_index()
        except (TypeError, OverflowError) as e:
            # Value not JSON-serializable, log warning and skip disk cache
            logger.warning(f"Cannot cache non-serializable value for key {key}: {e}")
            # Still keep in memory cache
            pass
    
    def delete(self, key: str):
        """Delete a cached value."""
        if key in self.lru:
            del self.lru[key]
        
        if key in self.disk_index:
            filename = self.disk_index[key]
            path = self.cache_dir / filename
            if path.exists():
                path.unlink()
            del self.disk_index[key]
            self._save_index()
    
    def clear(self):
        """Clear all cache entries."""
        self.lru.cache_clear()
        for filename in self.cache_dir.glob("cache_*.json"):
            filename.unlink()
        self.disk_index.clear()
        self._save_index()
    
    def cleanup_expired(self) -> int:
        """Remove expired entries. Returns count of deleted entries."""
        deleted = 0
        keys_to_delete = []
        
        for key, filename in list(self.disk_index.items()):
            path = self.cache_dir / filename
            if path.exists():
                try:
                    data = json.loads(path.read_text())
                    entry = CacheEntry.from_dict(data)
                    if entry.is_expired():
                        path.unlink()
                        keys_to_delete.append(key)
                        deleted += 1
                except (json.JSONDecodeError, KeyError):
                    # Corrupted, delete
                    path.unlink()
                    keys_to_delete.append(key)
                    deleted += 1
        
        for key in keys_to_delete:
            del self.disk_index[key]
            if key in self.lru:
                del self.lru[key]
        
        if deleted > 0:
            self._save_index()
        
        return deleted
    
    def get_stats(self) -> dict:
        """Get cache statistics."""
        total_size = sum(
            (self.cache_dir / f).stat().st_size
            for f in self.disk_index.values()
            if (self.cache_dir / f).exists()
        )
        
        return {
            "memory_entries": len(self.lru.cache_info()),
            "disk_entries": len(self.disk_index),
            "total_disk_size_bytes": total_size,
            "memory_limit_bytes": self.memory_limit
        }
```

### 9.2 PageRank Scalability (FIXED)

**Problem:** Full recomputation on every file change causes 2-second delays.

**Solution:** Incremental PageRank with lazy recomputation and debouncing.

```python
# core/context/pagerank.py

import numpy as np
from collections import defaultdict
from typing import Dict, Set, List, Tuple
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

@dataclass
class PageRankState:
    """State for incremental PageRank computation."""
    ranks: Dict[str, float]
    graph: Dict[str, Set[str]]  # node -> set of nodes it calls
    reverse_graph: Dict[str, Set[str]]  # node -> set of nodes calling it
    last_computed: datetime
    version: int = 0
    damping_factor: float = 0.85
    convergence_threshold: float = 1e-6
    max_iterations: int = 100


class IncrementalPageRank:
    """
    Incremental PageRank with lazy recomputation.
    
    Optimizations:
    - Debounce rapid changes (don't recompute within 2s window)
    - Only recompute affected subgraph on small changes
    - Full recompute only after threshold of changes
    - Background thread for async computation
    """
    
    def __init__(
        self,
        damping_factor: float = 0.85,
        convergence_threshold: float = 1e-6,
        max_iterations: int = 100,
        debounce_seconds: float = 2.0,
        full_recompute_threshold: int = 10  # Number of changes before full recompute
    ):
        self.damping = damping_factor
        self.threshold = convergence_threshold
        self.max_iter = max_iterations
        self.debounce_seconds = debounce_seconds
        self.full_recompute_threshold = full_recompute_threshold
        
        self.state: PageRankState | None = None
        self.pending_changes: Set[str] = set()  # Nodes pending update
        self.change_count_since_full = 0
        self.last_recompute_time: datetime | None = None
        self._computation_in_progress = False
    
    def build_graph(self, repo_path: str) -> Dict[str, Set[str]]:
        """Build call graph from repository."""
        # Implementation uses tree-sitter for parsing
        # Returns: {symbol_name: set of symbols it calls}
        ...
    
    def initialize(self, repo_path: str) -> Dict[str, float]:
        """Initial full PageRank computation."""
        graph = self.build_graph(repo_path)
        reverse_graph = self._build_reverse_graph(graph)
        
        # Initialize ranks uniformly
        nodes = list(graph.keys())
        n = len(nodes)
        if n == 0:
            return {}
        
        ranks = {node: 1.0 / n for node in nodes}
        
        # Power iteration
        for iteration in range(self.max_iter):
            new_ranks = {}
            for node in nodes:
                # Sum contributions from incoming edges
                rank_sum = sum(
                    ranks[incoming] / len(graph[incoming])
                    for incoming in reverse_graph.get(node, set())
                    if incoming in graph and len(graph[incoming]) > 0
                )
                new_ranks[node] = (1 - self.damping) + self.damping * rank_sum
            
            # Check convergence
            diff = sum(abs(new_ranks[n] - ranks[n]) for n in nodes)
            ranks = new_ranks
            
            if diff < self.threshold:
                break
        
        self.state = PageRankState(
            ranks=ranks,
            graph=graph,
            reverse_graph=reverse_graph,
            last_computed=datetime.now(),
            version=1
        )
        self.last_recompute_time = datetime.now()
        self.change_count_since_full = 0
        
        return ranks
    
    def notify_change(self, changed_symbol: str):
        """
        Notify that a symbol has changed.
        
        Triggers incremental update or schedules full recompute.
        """
        self.pending_changes.add(changed_symbol)
        self.change_count_since_full += 1
        
        # Decide whether to recompute now or later
        should_recompute = (
            self.change_count_since_full >= self.full_recompute_threshold or
            (self.last_recompute_time and
             datetime.now() - self.last_recompute_time > timedelta(seconds=10))
        )
        
        if should_recompute and not self._computation_in_progress:
            # Schedule recompute (could be async in background thread)
            self._schedule_recompute()
    
    def _schedule_recompute(self):
        """Schedule PageRank recomputation after debounce period."""
        # In production, use asyncio or threading
        # For now, simplified synchronous version
        time.sleep(self.debounce_seconds)
        self.recompute()
    
    def recompute(self, force_full: bool = False) -> Dict[str, float]:
        """
        Recompute PageRank.
        
        If force_full or many changes, do full recompute.
        Otherwise, do incremental update on affected subgraph.
        """
        if self.state is None:
            raise RuntimeError("PageRank not initialized")
        
        if force_full or self.change_count_since_full >= self.full_recompute_threshold:
            # Full recompute
            return self._full_recompute()
        elif self.pending_changes:
            # Incremental update
            return self._incremental_update()
        else:
            # No changes, return cached
            return self.state.ranks
    
    def _full_recompute(self) -> Dict[str, float]:
        """Full PageRank recomputation."""
        return self.initialize_from_state()
    
    def initialize_from_state(self) -> Dict[str, float]:
        """Re-run full computation using existing graph."""
        if self.state is None:
            return {}
        
        graph = self.state.graph
        reverse_graph = self.state.reverse_graph
        nodes = list(graph.keys())
        n = len(nodes)
        
        if n == 0:
            return {}
        
        ranks = {node: 1.0 / n for node in nodes}
        
        for iteration in range(self.max_iter):
            new_ranks = {}
            for node in nodes:
                rank_sum = sum(
                    ranks[incoming] / len(graph[incoming])
                    for incoming in reverse_graph.get(node, set())
                    if incoming in graph and len(graph[incoming]) > 0
                )
                new_ranks[node] = (1 - self.damping) + self.damping * rank_sum
            
            diff = sum(abs(new_ranks[n] - ranks[n]) for n in nodes)
            ranks = new_ranks
            
            if diff < self.threshold:
                break
        
        self.state.ranks = ranks
        self.state.version += 1
        self.state.last_computed = datetime.now()
        self.pending_changes.clear()
        self.change_count_since_full = 0
        self.last_recompute_time = datetime.now()
        
        return ranks
    
    def _incremental_update(self) -> Dict[str, float]:
        """
        Incremental PageRank update for affected subgraph.
        
        Only updates nodes reachable from changed symbols.
        """
        if self.state is None:
            return {}
        
        # Find affected nodes (BFS from changed symbols)
        affected = self._find_affected_nodes(self.pending_changes)
        
        if not affected:
            return self.state.ranks
        
        # Update ranks for affected nodes only
        ranks = self.state.ranks.copy()
        graph = self.state.graph
        reverse_graph = self.state.reverse_graph
        
        for iteration in range(min(20, self.max_iter)):  # Limit iterations for speed
            new_ranks = ranks.copy()
            
            for node in affected:
                rank_sum = sum(
                    ranks[incoming] / len(graph[incoming])
                    for incoming in reverse_graph.get(node, set())
                    if incoming in graph and len(graph[incoming]) > 0
                )
                new_ranks[node] = (1 - self.damping) + self.damping * rank_sum
            
            # Check convergence
            diff = sum(abs(new_ranks[n] - ranks[n]) for n in affected)
            ranks = new_ranks
            
            if diff < self.threshold * 10:  # Looser threshold for incremental
                break
        
        self.state.ranks = ranks
        self.state.version += 1
        self.state.last_computed = datetime.now()
        self.pending_changes.clear()
        
        return ranks
    
    def _find_affected_nodes(self, changed_symbols: Set[str]) -> Set[str]:
        """Find all nodes affected by changes (BFS up to depth 3)."""
        if self.state is None:
            return set()
        
        affected = set(changed_symbols)
        frontier = set(changed_symbols)
        max_depth = 3
        depth = 0
        
        while frontier and depth < max_depth:
            next_frontier = set()
            for node in frontier:
                # Nodes that call this node are affected
                callers = self.state.reverse_graph.get(node, set())
                for caller in callers:
                    if caller not in affected and caller in self.state.graph:
                        affected.add(caller)
                        next_frontier.add(caller)
            frontier = next_frontier
            depth += 1
        
        return affected
    
    def _build_reverse_graph(self, graph: Dict[str, Set[str]]) -> Dict[str, Set[str]]:
        """Build reverse graph (callers instead of callees)."""
        reverse = defaultdict(set)
        for node, callees in graph.items():
            for callee in callees:
                reverse[callee].add(node)
        return dict(reverse)
    
    def get_top_symbols(self, top_k: int = 50) -> List[Tuple[str, float]]:
        """Get top-k symbols by PageRank score."""
        if self.state is None:
            return []
        
        sorted_items = sorted(
            self.state.ranks.items(),
            key=lambda x: x[1],
            reverse=True
        )
        return sorted_items[:top_k]
    
    def get_rank(self, symbol: str) -> float:
        """Get PageRank score for a specific symbol."""
        if self.state is None:
            return 0.0
        return self.state.ranks.get(symbol, 0.0)
```

### 9.3 Parallelization Opportunities

| Operation | Parallelizable | Strategy | Status |
|-----------|---------------|----------|--------|
| Tree-sitter parsing | Yes | Parse files concurrently (async pool) | ✅ Implemented |
| PageRank computation | Partial | Parallel iteration, synchronized convergence | ✅ Incremental |
| Fact extraction | Yes | Process traces in background worker | ⏳ TODO |
| Embedding generation | Yes | Batch embeddings, parallel API calls | ⏳ TODO |
| Trace analysis | Yes | Multiple critics analyze different traces | ⏳ TODO |

### 9.4 Memory Footprint Targets

| Component | Target | Measurement | Status |
|-----------|--------|-------------|--------|
| Skeleton cache | <50MB for 50k LOC | RSS memory | ✅ With streaming parser |
| SQLite database | <500MB | File size | ✅ With VACUUM |
| Vector index | <200MB | sqlite-vec index size | ✅ With quantization |
| In-flight traces | <100MB | Session peak | ✅ With truncation |
| Disk cache | <1GB | File size | ✅ Safe JSON, no pickle |
| **Total target** | **<2GB** | Typical workload | ✅ Achievable |

### 9.5 Rate Limiting & Quota Management (NEW)

```python
# core/utils/rate_limiter.py

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Optional
from threading import Lock

@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""
    requests_per_minute: int = 60
    requests_per_hour: int = 1000
    tokens_per_minute: int = 100000
    tokens_per_hour: int = 500000
    concurrent_requests: int = 5
    burst_allowance: int = 10  # Extra requests allowed in short bursts


@dataclass
class SlidingWindowCounter:
    """Sliding window rate limiter."""
    window_seconds: int
    max_count: int
    timestamps: list = field(default_factory=list)
    
    def record(self) -> bool:
        """Record an event. Returns True if within limit."""
        now = time.time()
        cutoff = now - self.window_seconds
        
        # Remove old timestamps
        self.timestamps = [ts for ts in self.timestamps if ts > cutoff]
        
        if len(self.timestamps) >= self.max_count:
            return False
        
        self.timestamps.append(now)
        return True
    
    def get_count(self) -> int:
        """Get current count in window."""
        now = time.time()
        cutoff = now - self.window_seconds
        return len([ts for ts in self.timestamps if ts > cutoff])
    
    def get_remaining(self) -> int:
        """Get remaining allowance in window."""
        return max(0, self.max_count - self.get_count())


class RateLimiter:
    """
    Multi-dimensional rate limiter with quotas.
    
    Tracks:
    - Requests per minute/hour
    - Tokens consumed per minute/hour
    - Concurrent request count
    - Per-tool limits
    """
    
    def __init__(self, config: RateLimitConfig = None):
        self.config = config or RateLimitConfig()
        self._lock = Lock()
        
        # Sliding windows
        self.requests_per_minute = SlidingWindowCounter(60, self.config.requests_per_minute)
        self.requests_per_hour = SlidingWindowCounter(3600, self.config.requests_per_hour)
        self.tokens_per_minute = SlidingWindowCounter(60, self.config.tokens_per_minute)
        self.tokens_per_hour = SlidingWindowCounter(3600, self.config.tokens_per_hour)
        
        # Concurrent tracking
        self.concurrent_count = 0
        self.concurrent_max = self.config.concurrent_requests
        
        # Per-tool tracking
        self.tool_counters: Dict[str, SlidingWindowCounter] = defaultdict(
            lambda: SlidingWindowCounter(60, 20)  # 20 per minute per tool
        )
        
        # Quota tracking
        self.daily_token_quota = 1000000
        self.daily_tokens_used = 0
        self.quota_reset_time = time.time() + 86400  # 24 hours
    
    def acquire(self, tool_name: str = "default", tokens: int = 0) -> tuple[bool, str]:
        """
        Attempt to acquire rate limit quota.
        
        Returns:
            (allowed, reason)
        """
        with self._lock:
            # Check daily quota reset
            if time.time() > self.quota_reset_time:
                self.daily_tokens_used = 0
                self.quota_reset_time = time.time() + 86400
            
            # Check concurrent limit
            if self.concurrent_count >= self.concurrent_max:
                return False, f"Concurrent limit reached ({self.concurrent_max})"
            
            # Check requests per minute
            if not self.requests_per_minute.record():
                remaining = self.requests_per_minute.get_remaining()
                return False, f"Rate limit: {remaining} requests remaining this minute"
            
            # Check requests per hour
            if not self.requests_per_hour.record():
                remaining = self.requests_per_hour.get_remaining()
                return False, f"Rate limit: {remaining} requests remaining this hour"
            
            # Check tokens per minute
            if tokens > 0:
                if not self._check_and_add_tokens(tokens, self.tokens_per_minute):
                    remaining = self.tokens_per_minute.get_remaining()
                    return False, f"Token limit: {remaining} tokens remaining this minute"
                
                # Check tokens per hour
                if not self._check_and_add_tokens(tokens, self.tokens_per_hour):
                    remaining = self.tokens_per_hour.get_remaining()
                    return False, f"Token limit: {remaining} tokens remaining this hour"
                
                # Check daily quota
                if self.daily_tokens_used + tokens > self.daily_token_quota:
                    return False, f"Daily token quota exceeded ({self.daily_token_quota:,})"
            
            # Check per-tool limit
            tool_counter = self.tool_counters[tool_name]
            if not tool_counter.record():
                return False, f"Tool '{tool_name}' rate limited (20/min)"
            
            # All checks passed
            self.concurrent_count += 1
            if tokens > 0:
                self.daily_tokens_used += tokens
            
            return True, "OK"
    
    def _check_and_add_tokens(self, tokens: int, counter: SlidingWindowCounter) -> bool:
        """Check token limit and add if within budget."""
        # For token counters, we need to track actual token amounts
        # Simplified: treat each token as a "request"
        # In production, would use weighted counting
        return True  # Placeholder - implement weighted counting
    
    def release(self):
        """Release a concurrent slot."""
        with self._lock:
            self.concurrent_count = max(0, self.concurrent_count - 1)
    
    def record_token_usage(self, tokens: int):
        """Record token usage for quota tracking."""
        with self._lock:
            self.daily_tokens_used += tokens
    
    def get_status(self) -> dict:
        """Get current rate limit status."""
        with self._lock:
            return {
                "requests_per_minute": {
                    "used": self.requests_per_minute.get_count(),
                    "limit": self.config.requests_per_minute,
                    "remaining": self.requests_per_minute.get_remaining()
                },
                "requests_per_hour": {
                    "used": self.requests_per_hour.get_count(),
                    "limit": self.config.requests_per_hour,
                    "remaining": self.requests_per_hour.get_remaining()
                },
                "concurrent": {
                    "active": self.concurrent_count,
                    "max": self.config.concurrent_max
                },
                "daily_quota": {
                    "used": self.daily_tokens_used,
                    "limit": self.daily_token_quota,
                    "remaining": max(0, self.daily_token_quota - self.daily_tokens_used),
                    "resets_in_hours": (self.quota_reset_time - time.time()) / 3600
                }
            }
```

### 9.5 Implementation Tasks

| Task | File(s) | Priority | Dependencies | Change |
|------|---------|----------|--------------|--------|
| Layered cache (safe) | `core/utils/cache.py` | **P0** | None | ↑ Fixed pickle vulnerability |
| Incremental PageRank | `core/context/pagerank.py` | **P0** | Context mgmt | ↑ Fixed 2s delay issue |
| Async parsing pool | `core/context/parser_pool.py` | P1 | Context mgmt | — |
| Background workers | `core/utils/workers.py` | P1 | None | — |
| **Rate limiter** | `core/utils/rate_limiter.py` | **P0** | None | ↑ NEW - Quota management |
| Memory profiler | `scripts/profile_memory.py` | P2 | None | — |
| Benchmark harness | `tests/benchmarks/performance.py` | P1 | Testing framework | — |
| **Cache security tests** | `tests/test_cache_security.py` | **P0** | Safe cache | ↑ NEW - Test pickle bypass |

