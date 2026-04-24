# NoMan Memory System — Detailed Design

> *The long-term memory of NoMan. A tiered, SQLite-backed system that learns from every session and gets smarter over time.*

**Version:** 0.1  
**Status:** Ready for Implementation  
**Parent Document:** NOMAN_DESIGN.md  
**Last Updated:** 2026-04-23

---

## 1. Overview

### 1.1 Purpose

The Memory System provides:
- **Persistent storage** across sessions (unlike context window)
- **Tiered organization** by information type (episodic, semantic, procedural)
- **Efficient retrieval** via vector + keyword search
- **Fact extraction** to distill raw traces into durable knowledge
- **Self-improvement fuel** for the meta-agent

### 1.2 Key Principles

| Principle | Description | Rationale |
|-----------|-------------|-----------|
| **Local-first** | All data stored locally in SQLite | Privacy, portability, no vendor lock-in |
| **Tiered by nature** | Separate episodic, semantic, procedural | Different TTLs, retrieval strategies |
| **Atomic facts** | Store distilled facts, not raw logs | Avoid noise pollution in retrieval |
| **Conflict-aware** | Detect and resolve stale/contradictory facts | Maintain consistency |
| **Queryable** | Both vector similarity and structured queries | Flexible retrieval patterns |

### 1.3 Non-Goals

- **Not a general database** — Optimized for agent memory access patterns
- **Not a distributed store** — Single-user, single-machine focus (initially)
- **Not a graph database** — Relationships are simple (scope/key/value)

---

## 2. Architecture

### 2.1 Component Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                      Memory System                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────┐    ┌─────────────────┐                │
│  │   Tiered        │    │   Fact          │                │
│  │   Storage       │    │   Extractor     │                │
│  │   (SQLite)      │    │                 │                │
│  └────────┬────────┘    └────────┬────────┘                │
│           │                      │                          │
│           ▼                      ▼                          │
│  ┌─────────────────┐    ┌─────────────────┐                │
│  │   Vector        │    │   Conflict      │                │
│  │   Index         │    │   Detector      │                │
│  │   (sqlite-vec)  │    │                 │                │
│  └────────┬────────┘    └────────┬────────┘                │
│           │                      │                          │
│           └──────────┬───────────┘                          │
│                      │                                      │
│              ┌───────▼────────┐                             │
│              │   Retrieval    │                             │
│              │   Engine       │                             │
│              └───────┬────────┘                             │
│                      │                                      │
│  ┌───────────────────▼───────────────────┐                 │
│  │         Query Interface               │                 │
│  │  (recall, remember, forget, skill_*)  │                 │
│  └───────────────────────────────────────┘                 │
│                                                             │
│  ┌─────────────────────────────────────────┐               │
│  │          Background Workers             │               │
│  │    (fact extraction, summarization)     │               │
│  └─────────────────────────────────────────┘               │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Data Flow

```
1. Write path (remember)
   ├─► Receive fact (scope, key, value)
   ├─► Check for conflicts with existing facts
   ├─► Generate embedding for value
   ├─► Store in SQLite (with metadata)
   └─► Update vector index

2. Read path (recall)
   ├─► Receive query (+ optional tier filter)
   ├─► Generate embedding for query
   ├─► Search vector index for similar items
   ├─► Apply structured filters (scope, tier, recency)
   ├─► Rank by combined score (similarity + recency + confidence)
   └─► Return top-k results

3. Fact extraction (post-session)
   ├─► Load session trace
   ├─► Send to LLM with extraction prompt
   ├─► Parse ADD/UPDATE/DELETE operations
   ├─► Validate each operation
   └─► Apply to memory store
```

---

## 3. Tiered Memory Model

### 3.1 Memory Tiers

| Tier | Purpose | TTL | Example | Retrieval Strategy |
|------|---------|-----|---------|-------------------|
| **Episodic** | Recent interaction traces, command outputs, errors | 7 days (then summarized) | "last migration failed with error X" | Time-decayed vector search |
| **Semantic** | Project-wide facts, conventions, architecture | Indefinite | "we use pytest", "auth requires X-User-Id header" | Structured query + vector fallback |
| **Procedural** | Skills, reusable task patterns | Indefinite | "how to add a new API endpoint" | Trigger-based skill loading |

### 3.2 Schema Design

```sql
-- Core memory table
CREATE TABLE memories (
    id TEXT PRIMARY KEY,                    -- UUID
    tier TEXT NOT NULL,                     -- 'episodic', 'semantic', 'procedural'
    scope TEXT NOT NULL,                    -- 'project', 'file', 'symbol', 'global'
    key TEXT NOT NULL,                      -- Fact key
    value TEXT NOT NULL,                    -- Fact value (JSON or text)
    embedding BLOB,                         -- Vector embedding (sqlite-vec)
    confidence REAL DEFAULT 1.0,            -- Confidence score [0, 1]
    source_trace_id TEXT,                   -- Reference to originating trace
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,                   -- NULL = indefinite
    is_valid BOOLEAN DEFAULT TRUE,          -- Soft delete flag
    
    UNIQUE(tier, scope, key)
);

-- Indexes
CREATE INDEX idx_memories_tier ON memories(tier);
CREATE INDEX idx_memories_scope ON memories(scope);
CREATE INDEX idx_memories_created ON memories(created_at);
CREATE INDEX idx_memories_expires ON memories(expires_at);
CREATE INDEX idx_memories_valid ON memories(is_valid) WHERE is_valid = FALSE;

-- Vector index (using sqlite-vec)
-- Note: sqlite-vec creates virtual tables internally

-- Traces table (for episodic memory source)
CREATE TABLE traces (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    task_description TEXT,
    turns INTEGER,
    success BOOLEAN,
    critic_score REAL,
    token_usage INTEGER,
    duration_sec REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Skills table (procedural memory index)
CREATE TABLE skills (
    id TEXT PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    description TEXT,
    trigger_keywords TEXT,                  -- Comma-separated keywords
    file_path TEXT NOT NULL,                -- Path to overlay/skills/<name>.md
    usage_count INTEGER DEFAULT 0,
    last_used_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 3.3 Data Models

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum

class MemoryTier(Enum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"

class MemoryScope(Enum):
    GLOBAL = "global"       # Universal facts
    PROJECT = "project"     # Project-specific
    FILE = "file"           # File-specific
    SYMBOL = "symbol"       # Symbol-specific

@dataclass
class Memory:
    id: str
    tier: MemoryTier
    scope: MemoryScope
    key: str
    value: str
    embedding: Optional[List[float]] = None
    confidence: float = 1.0
    source_trace_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None
    is_valid: bool = True
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "tier": self.tier.value,
            "scope": self.scope.value,
            "key": self.key,
            "value": self.value,
            "confidence": self.confidence,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None
        }

@dataclass
class Skill:
    id: str
    name: str
    description: str
    trigger_keywords: List[str]
    file_path: str
    usage_count: int = 0
    last_used_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.now)
    
    def matches_query(self, query: str) -> bool:
        """Check if query matches skill triggers."""
        query_lower = query.lower()
        return any(kw.lower() in query_lower for kw in self.trigger_keywords)
```

---

## 4. Operations

### 4.1 Remember (Write)

```python
class MemoryStore:
    """SQLite-backed memory store with vector search."""
    
    def __init__(self, db_path: Path, embedder: Embedder):
        self.db_path = db_path
        self.embedder = embedder
        self.conn = self._init_db()
    
    async def remember(
        self,
        tier: MemoryTier,
        scope: MemoryScope,
        key: str,
        value: str,
        ttl_days: Optional[int] = None,
        source_trace_id: Optional[str] = None
    ) -> Memory:
        """Store a memory."""
        
        # Check for existing fact (conflict detection)
        existing = await self._find_existing(tier, scope, key)
        
        if existing:
            if existing.value == value:
                # No change needed
                return existing
            
            # Update existing
            memory = await self._update(existing, value)
        else:
            # Insert new
            memory = await self._insert(
                tier=tier,
                scope=scope,
                key=key,
                value=value,
                ttl_days=ttl_days,
                source_trace_id=source_trace_id
            )
        
        return memory
    
    async def _insert(
        self,
        tier: MemoryTier,
        scope: MemoryScope,
        key: str,
        value: str,
        ttl_days: Optional[int],
        source_trace_id: Optional[str]
    ) -> Memory:
        """Insert a new memory."""
        
        # Generate embedding
        embedding = await self.embedder.embed(value)
        
        # Calculate expiration
        expires_at = None
        if ttl_days:
            expires_at = datetime.now() + timedelta(days=ttl_days)
        
        # Create memory object
        memory = Memory(
            id=str(uuid.uuid4()),
            tier=tier,
            scope=scope,
            key=key,
            value=value,
            embedding=embedding,
            expires_at=expires_at,
            source_trace_id=source_trace_id
        )
        
        # Insert into database
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO memories (id, tier, scope, key, value, embedding, expires_at, source_trace_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            memory.id,
            memory.tier.value,
            memory.scope.value,
            memory.key,
            memory.value,
            serialize_embedding(memory.embedding),
            memory.expires_at,
            memory.source_trace_id
        ))
        
        self.conn.commit()
        
        return memory
    
    async def _update(self, existing: Memory, new_value: str) -> Memory:
        """Update an existing memory."""
        
        # Generate new embedding
        new_embedding = await self.embedder.embed(new_value)
        
        # Update record
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE memories
            SET value = ?, embedding = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (new_value, serialize_embedding(new_embedding), existing.id))
        
        self.conn.commit()
        
        return Memory(
            id=existing.id,
            tier=existing.tier,
            scope=existing.scope,
            key=existing.key,
            value=new_value,
            embedding=new_embedding,
            confidence=existing.confidence,
            created_at=existing.created_at,
            updated_at=datetime.now(),
            expires_at=existing.expires_at
        )
```

### 4.2 Recall (Read)

```python
    async def recall(
        self,
        query: str,
        tier: Optional[MemoryTier] = None,
        scope: Optional[MemoryScope] = None,
        k: int = 10,
        min_confidence: float = 0.5
    ) -> List[Memory]:
        """Retrieve memories relevant to a query."""
        
        # Generate query embedding
        query_embedding = await self.embedder.embed(query)
        
        # Build SQL query with filters
        filters = ["is_valid = TRUE"]
        params = []
        
        if tier:
            filters.append("tier = ?")
            params.append(tier.value)
        
        if scope:
            filters.append("scope = ?")
            params.append(scope.value)
        
        if min_confidence:
            filters.append("confidence >= ?")
            params.append(min_confidence)
        
        # Exclude expired
        filters.append("(expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)")
        
        where_clause = " AND ".join(filters)
        
        # Vector similarity search using sqlite-vec
        cursor = self.conn.cursor()
        cursor.execute(f"""
            SELECT id, tier, scope, key, value, embedding, confidence, 
                   created_at, updated_at, expires_at,
                   vec_distance_cosine(embedding, ?) as similarity
            FROM memories
            WHERE {where_clause}
            ORDER BY similarity ASC
            LIMIT ?
        """, [*params, serialize_embedding(query_embedding), k])
        
        rows = cursor.fetchall()
        
        # Convert to Memory objects
        memories = []
        for row in rows:
            memory = Memory(
                id=row[0],
                tier=MemoryTier(row[1]),
                scope=MemoryScope(row[2]),
                key=row[3],
                value=row[4],
                embedding=deserialize_embedding(row[5]),
                confidence=row[6],
                created_at=datetime.fromisoformat(row[7]),
                updated_at=datetime.fromisoformat(row[8]),
                expires_at=datetime.fromisoformat(row[9]) if row[9] else None
            )
            memories.append(memory)
        
        return memories
```

### 4.3 Forget (Invalidate)

```python
    async def forget(self, tier: MemoryTier, scope: MemoryScope, key: str) -> bool:
        """Soft-delete a memory."""
        
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE memories
            SET is_valid = FALSE, updated_at = CURRENT_TIMESTAMP
            WHERE tier = ? AND scope = ? AND key = ?
        """, (tier.value, scope.value, key))
        
        self.conn.commit()
        
        return cursor.rowcount > 0
    
    async def hard_delete_expired(self) -> int:
        """Permanently delete expired memories."""
        
        cursor = self.conn.cursor()
        cursor.execute("""
            DELETE FROM memories
            WHERE expires_at IS NOT NULL 
              AND expires_at < CURRENT_TIMESTAMP
              AND is_valid = TRUE
        """)
        
        self.conn.commit()
        
        return cursor.rowcount
```

---

## 5. Fact Extraction

### 5.1 Extraction Prompt

```python
FACT_EXTRACTION_PROMPT = """
Given this session trace, extract atomic, durable facts about the project.

Emit each fact as one of:
  ADD {tier, scope, key, value, confidence}
  UPDATE {tier, scope, key, new_value, confidence}
  DELETE {tier, scope, key}

Rules:
- Only emit high-confidence, project-durable facts
- Prefer semantic tier for conventions, architecture, APIs
- Use episodic only for recent failures/wins worth remembering
- Never emit trivial facts (e.g., "file was read")
- Confidence should reflect certainty (0.5-1.0)

Example output:
ADD {tier: "semantic", scope: "project", key: "test_framework", value: "pytest with fixtures in conftest.py", confidence: 0.95}
ADD {tier: "semantic", scope: "file", key: "src/auth.py::auth_middleware", value: "requires X-User-Id header", confidence: 0.9}
UPDATE {tier: "semantic", scope: "project", key: "python_version", new_value: "3.12", confidence: 1.0}
DELETE {tier: "semantic", scope: "file", key: "src/legacy.py::*"}

Session trace:
{trace_json}
"""
```

### 5.2 Extractor Implementation

```python
class FactExtractor:
    """Extract atomic facts from session traces."""
    
    def __init__(self, model_adapter: ModelAdapter, memory_store: MemoryStore):
        self.model_adapter = model_adapter
        self.memory_store = memory_store
    
    async def extract_from_trace(self, trace: Trace) -> List[MemoryOperation]:
        """Extract facts from a session trace."""
        
        # Format trace for prompt
        trace_json = json.dumps(trace.to_dict(), indent=2)
        prompt = FACT_EXTRACTION_PROMPT.format(trace_json=trace_json)
        
        # Call LLM
        response = await self.model_adapter.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1  # Low temp for deterministic output
        )
        
        # Parse operations
        operations = self._parse_operations(response.content)
        
        # Validate and apply
        validated = []
        for op in operations:
            if await self._validate_operation(op):
                validated.append(op)
        
        return validated
    
    def _parse_operations(self, text: str) -> List[MemoryOperation]:
        """Parse LLM output into operations."""
        
        operations = []
        
        for line in text.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            
            if line.startswith("ADD "):
                data = json.loads(line[4:])
                operations.append(MemoryOperation(
                    type="ADD",
                    tier=MemoryTier(data["tier"]),
                    scope=MemoryScope(data["scope"]),
                    key=data["key"],
                    value=data["value"],
                    confidence=data.get("confidence", 1.0)
                ))
            
            elif line.startswith("UPDATE "):
                data = json.loads(line[7:])
                operations.append(MemoryOperation(
                    type="UPDATE",
                    tier=MemoryTier(data["tier"]),
                    scope=MemoryScope(data["scope"]),
                    key=data["key"],
                    value=data["new_value"],
                    confidence=data.get("confidence", 1.0)
                ))
            
            elif line.startswith("DELETE "):
                data = json.loads(line[7:])
                operations.append(MemoryOperation(
                    type="DELETE",
                    tier=MemoryTier(data["tier"]),
                    scope=MemoryScope(data["scope"]),
                    key=data["key"]
                ))
        
        return operations
    
    async def _validate_operation(self, op: MemoryOperation) -> bool:
        """Validate an operation before applying."""
        
        # Check confidence threshold
        if op.confidence < 0.7:
            logger.warning(f"Low confidence fact: {op}")
            return False
        
        # Check for contradictions
        if op.type == "ADD":
            existing = await self.memory_store._find_existing(
                op.tier, op.scope, op.key
            )
            if existing and existing.value != op.value:
                # Contradiction detected - flag for review
                logger.warning(f"Contradictory fact: {op.key}")
                return False  # Require human review
        
        return True
```

---

## 6. Skill Library (Procedural Memory)

### 6.1 Skill Format

Skills are stored as Markdown files in `overlay/skills/`:

```markdown
---
name: add_api_endpoint
description: Add a new REST API endpoint with proper structure
trigger_keywords: ["api", "endpoint", "route", "REST", "HTTP"]
version: 1.0
created: 2026-04-22
---

# Skill: Add API Endpoint

## When to Use
When adding a new REST API endpoint to the codebase.

## Steps

1. **Locate the API module**
   - Use `search_symbols` to find existing API classes
   - Check `src/api/` directory structure

2. **Add the endpoint method**
   ```python
   @app.route("/api/v1/resource", methods=["POST"])
   def create_resource():
       data = request.get_json()
       # Validate input
       # Process request
       return jsonify(result), 201
   ```

3. **Add input validation**
   - Use Pydantic models for request validation
   - Check existing validation patterns in `src/validators/`

4. **Add tests**
   - Create test in `tests/test_api.py`
   - Test happy path and error cases

5. **Update documentation**
   - Add to API docs in `docs/api.md`

## Common Pitfalls
- Forgetting to add CORS headers
- Not validating input properly
- Missing error handling

## Related Skills
- add_database_model
- add_authentication
```

### 6.2 Skill Loading

```python
class SkillLibrary:
    """Manage procedural memory (skills)."""
    
    def __init__(self, skills_dir: Path, memory_store: MemoryStore):
        self.skills_dir = skills_dir
        self.memory_store = memory_store
        self.skills: Dict[str, Skill] = {}
        
        # Load skills from disk
        self._discover_skills()
    
    def _discover_skills(self):
        """Load all skills from skills directory."""
        
        for skill_file in self.skills_dir.glob("*.md"):
            skill = self._parse_skill_file(skill_file)
            if skill:
                self.skills[skill.name] = skill
    
    def _parse_skill_file(self, path: Path) -> Optional[Skill]:
        """Parse a skill Markdown file."""
        
        content = path.read_text()
        
        # Extract front matter
        match = re.match(r'^---\n(.+?)\n---\n(.+)$', content, re.DOTALL)
        if not match:
            return None
        
        front_matter = yaml.safe_load(match.group(1))
        body = match.group(2)
        
        return Skill(
            id=str(uuid.uuid4()),
            name=front_matter.get("name", path.stem),
            description=front_matter.get("description", ""),
            trigger_keywords=front_matter.get("trigger_keywords", []),
            file_path=str(path),
            created_at=datetime.fromisoformat(front_matter.get("created", datetime.now().isoformat()))
        )
    
    async def get_relevant_skills(self, query: str, k: int = 3) -> List[str]:
        """Get skill bodies relevant to a query."""
        
        # Find matching skills
        matching = [
            skill for skill in self.skills.values()
            if skill.matches_query(query)
        ]
        
        # Sort by usage count (most used first)
        matching.sort(key=lambda s: s.usage_count, reverse=True)
        
        # Load top-k skill bodies
        result = []
        for skill in matching[:k]:
            body = Path(skill.file_path).read_text()
            result.append(body)
            
            # Update usage stats
            skill.usage_count += 1
            skill.last_used_at = datetime.now()
        
        return result
```

---

## 7. Configuration

### 7.1 Memory Config

```toml
# user/config.toml

[memory]
db_path = ".noman/memory.db"
enable_vector_search = true
embedding_model = "nomic-embed-text"
embedding_dimension = 768

[episodic]
default_ttl_days = 7
max_items = 10000
summarize_after_days = 3

[semantic]
min_confidence_threshold = 0.7
auto_extract_facts = true
require_approval_for_writes = false

[procedural]
skills_dir = "overlay/skills/"
auto_load_relevant = true
max_skills_per_query = 3

[fact_extraction]
enabled = true
run_post_session = true
model_role = "critic"
min_confidence = 0.7
```

### 7.2 Runtime Commands

```bash
# Search memory
noman memory search "authentication pattern"

# List memories by tier
noman memory ls --tier semantic

# Export memory
noman memory export --output backup.json

# Import memory
noman memory import --file backup.json

# Show memory stats
noman memory stats

# Clear expired memories
noman memory vacuum
```

---

## 8. Testing Strategy

### 8.1 Unit Tests

```python
# tests/test_memory.py

class TestMemoryStore:
    
    async def test_remember_and_recall(self):
        store = MemoryStore(test_db, test_embedder)
        
        # Remember a fact
        memory = await store.remember(
            tier=MemoryTier.SEMANTIC,
            scope=MemoryScope.PROJECT,
            key="test_framework",
            value="pytest with fixtures"
        )
        
        assert memory.id is not None
        assert memory.value == "pytest with fixtures"
        
        # Recall the fact
        results = await store.recall(query="what testing framework")
        
        assert len(results) > 0
        assert results[0].key == "test_framework"
    
    async def test_conflict_detection(self):
        store = MemoryStore(test_db, test_embedder)
        
        # Add initial fact
        await store.remember(
            tier=MemoryTier.SEMANTIC,
            scope=MemoryScope.PROJECT,
            key="python_version",
            value="3.11"
        )
        
        # Try to add contradictory fact
        memory = await store.remember(
            tier=MemoryTier.SEMANTIC,
            scope=MemoryScope.PROJECT,
            key="python_version",
            value="3.12"
        )
        
        # Should update, not duplicate
        assert memory.value == "3.12"
        
        # Verify only one record exists
        all_memories = await store.recall("python version", k=10)
        assert len(all_memories) == 1
    
    async def test_expiration(self):
        store = MemoryStore(test_db, test_embedder)
        
        # Add expiring memory
        await store.remember(
            tier=MemoryTier.EPISODIC,
            scope=MemoryScope.PROJECT,
            key="temp_fact",
            value="temporary",
            ttl_days=1
        )
        
        # Should exist now
        results = await store.recall("temp")
        assert len(results) > 0
        
        # Simulate expiration (mock time)
        with freeze_time(datetime.now() + timedelta(days=2)):
            results = await store.recall("temp")
            assert len(results) == 0  # Expired

class TestFactExtractor:
    
    async def test_extract_add_operation(self):
        extractor = FactExtractor(mock_model, mock_store)
        
        trace = Trace(
            id="test-trace",
            task="add logging",
            turns=5,
            success=True
        )
        
        operations = await extractor.extract_from_trace(trace)
        
        assert len(operations) > 0
        assert any(op.type == "ADD" for op in operations)
```

---

## 9. Performance Targets

| Metric | Target | Measurement |
|--------|--------|-------------|
| Write latency (remember) | <50ms | Insert + embed time |
| Read latency (recall, k=10) | <100ms | Query + vector search time |
| Embedding generation | <20ms | Per text (local model) |
| Fact extraction (post-session) | <5 seconds | Full trace processing |
| DB size (10k memories) | <500 MB | `du -sh memory.db` |
| Vector search (10k items) | <50ms | Cosine similarity search |

---

## 10. Open Questions

1. **Embedding model swaps:** If user changes embedding models, all stored vectors become invalid. Should we store model version per-row and lazily re-embed on access?

2. **Multi-user sync:** How to handle team memory sharing without conflicts? Central server vs P2P sync?

3. **Memory prioritization:** Should some memories be "pinned" to never expire or be deprioritized in eviction?

4. **Cross-repo memories:** Should project-scoped memories be shareable across related repos (monorepo scenarios)?

---

## 11. Implementation Checklist

- [ ] SQLite schema setup with migrations
- [ ] Embedder interface (abstract base class)
- [ ] Local embedding backend (Ollama, fastembed)
- [ ] Memory store CRUD operations
- [ ] Vector search integration (sqlite-vec)
- [ ] Fact extraction pipeline
- [ ] Conflict detection logic
- [ ] Skill library loader
- [ ] Background workers (expiration cleanup)
- [ ] CLI commands (`noman memory *`)
- [ ] Export/import functionality
- [ ] Unit tests (80%+ coverage)
- [ ] Performance benchmarks
- [ ] Documentation for memory management

---

## 12. References

- **SQLite**: https://www.sqlite.org/
- **sqlite-vec**: https://github.com/asg017/sqlite-vec
- **Parent Design**: [NOMAN_DESIGN.md](./NOMAN_DESIGN.md)
- **Related**: [orchestrator.md](./orchestrator.md), [self_improve.md](./self_improve.md)
