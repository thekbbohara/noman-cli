# NoMan Context Management — Detailed Design

> *The eyes of NoMan. Provides the illusion of whole-repo awareness within tight token budgets through skeleton maps, symbol ranking, and JIT loading.*

**Version:** 0.1  
**Status:** Ready for Implementation  
**Parent Document:** NOMAN_DESIGN.md  
**Last Updated:** 2026-04-23

---

## 1. Overview

### 1.1 Purpose

Context Management solves the fundamental problem: **How do we give a coding agent awareness of a 50k+ LOC repository while staying within a 4K–32K token context window?**

The answer is three-fold:
1. **Skeleton Maps** — Compress the repo to signatures only (~1 line per symbol)
2. **PageRank Ranking** — Surface important symbols first, hide peripheral ones
3. **JIT Loading** — Fetch full content only when genuinely needed

### 1.2 Key Principles

| Principle | Description | Rationale |
|-----------|-------------|-----------|
| **Never read eagerly** | Don't load full files unless editing every line | Token frugality |
| **Rank by importance** | Use call/import graph centrality to prioritize | Model attention is scarce |
| **Cache aggressively** | Parse results are cached until file changes | Avoid redundant work |
| **Incremental updates** | Re-parse only changed files, not entire repo | Performance at scale |

### 1.3 Non-Goals

- **Not a full-text search engine** — Delegates to ripgrep/grep for content search
- **Not an IDE language server** — Doesn't provide real-time type checking or autocomplete
- **Not a code formatter** — Doesn't modify code structure beyond what tools request

---

## 2. Architecture

### 2.1 Component Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                   Context Management                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────┐    ┌─────────────────┐                │
│  │  Tree-sitter    │    │   PageRank      │                │
│  │   Parser        │───►│   Ranker        │                │
│  └────────┬────────┘    └────────┬────────┘                │
│           │                      │                          │
│           ▼                      ▼                          │
│  ┌─────────────────┐    ┌─────────────────┐                │
│  │   Skeleton      │    │   Symbol        │                │
│  │   Cache         │    │   Index         │                │
│  └────────┬────────┘    └────────┬────────┘                │
│           │                      │                          │
│           └──────────┬───────────┘                          │
│                      │                                      │
│              ┌───────▼────────┐                             │
│              │  Context View  │                             │
│              │   Assembler    │                             │
│              └───────┬────────┘                             │
│                      │                                      │
│  ┌───────────────────▼───────────────────┐                 │
│  │         Just-in-Time Loader           │                 │
│  │  (read_lines, read_symbol, search)    │                 │
│  └───────────────────────────────────────┘                 │
│                                                             │
│  ┌─────────────────────────────────────────┐               │
│  │          File Watchdog                  │               │
│  │    (incremental re-parse on change)     │               │
│  └─────────────────────────────────────────┘               │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Data Flow

```
1. Repo initialization
   ├─► Walk directory tree
   ├─► Parse each file with Tree-sitter
   ├─► Extract symbols (signatures only)
   ├─► Build call/import graph
   ├─► Run PageRank on graph
   └─► Store in Skeleton Cache + Symbol Index

2. Context request (per turn)
   ├─► Receive query + budget from Orchestrator
   ├─► Load skeleton (top-N symbols by rank)
   ├─► Truncate to fit budget
   └─► Return ContextView

3. JIT load request (during turn)
   ├─► Agent requests specific symbol/lines
   ├─► Check cache (return if hit)
   ├─► Read from disk (if miss)
   ├─► Update cache
   └─► Return content
```

---

## 3. Tree-sitter Skeleton Map

### 3.1 What Gets Extracted

For each file, extract only:

| Element | Example Output | Token Cost |
|---------|---------------|------------|
| **Function/method signatures** | `def authenticate(user_id: int, token: str) -> bool` | ~10-15 tokens |
| **Class headers** | `class SessionManager(BaseStore):` | ~5-8 tokens |
| **Top-level constants** | `MAX_SESSIONS = 1000` | ~3-5 tokens |
| **Type aliases** | `UserId = int` | ~3 tokens |
| **Docstrings (first line)** | `"""Manage user sessions with TTL."""` | ~5-10 tokens |

**What's excluded:**
- Function bodies
- Implementation details
- Comments (except docstring first lines)
- Import statements (tracked separately in graph)

### 3.2 Skeleton Format

Compact newline-delimited format:

```
# src/auth/session.py
class SessionManager(BaseStore):
  """Manage user sessions with TTL."""
  def create_session(user_id: int, ttl: int=3600) -> Session
  def revoke(session_id: str) -> bool
  def get_session(session_id: str) -> Optional[Session]

# src/auth/middleware.py
def auth_middleware(request: Request) -> Response
def validate_token(token: str) -> Claims

# src/api/users.py
class UserAPI:
  def get_user(user_id: int) -> User
  def create_user(data: CreateUserRequest) -> User
  def delete_user(user_id: int) -> bool
```

**Compression ratio:** A 50k-LOC repo (~2M tokens raw) compresses to ~4-8k tokens of skeleton (250-500x compression).

### 3.3 Tree-sitter Language Support

| Language | Grammar Package | Maturity |
|----------|----------------|----------|
| Python | `tree-sitter-python` | Stable |
| JavaScript/TypeScript | `tree-sitter-typescript` | Stable |
| Rust | `tree-sitter-rust` | Stable |
| Go | `tree-sitter-go` | Stable |
| Java | `tree-sitter-java` | Stable |
| C/C++ | `tree-sitter-cpp` | Stable |
| Ruby | `tree-sitter-ruby` | Stable |
| Swift | `tree-sitter-swift` | Beta |

Fallback for unsupported languages: regex-based signature extraction (less accurate).

### 3.4 Parser Implementation

```python
class TreeSitterParser:
    """Extract symbols from source files using tree-sitter."""
    
    def __init__(self, language: str):
        self.language = language
        self.parser = Parser()
        self.parser.set_language(self._load_language(language))
        
        # Define extraction queries per language
        self.queries = self._load_queries(language)
    
    def parse_file(self, file_path: Path) -> List[Symbol]:
        """Parse a file and extract symbols."""
        
        with open(file_path, 'r', encoding='utf-8') as f:
            source_code = f.read()
        
        tree = self.parser.parse(source_code.encode())
        root_node = tree.root_node
        
        symbols = []
        for match in self.queries.captures(root_node):
            symbol = self._node_to_symbol(match, file_path, source_code)
            symbols.append(symbol)
        
        return symbols
    
    def _node_to_symbol(
        self,
        node: Node,
        file_path: Path,
        source_code: str
    ) -> Symbol:
        """Convert a tree-sitter node to a Symbol object."""
        
        # Extract signature text
        start_byte = node.start_byte
        end_byte = node.end_byte
        signature = source_code[start_byte:end_byte].split('\n')[0]  # First line only
        
        # Extract docstring if present
        docstring = self._extract_docstring(node, source_code)
        
        return Symbol(
            file_path=str(file_path),
            name=self._get_symbol_name(node),
            type=self._get_symbol_type(node),
            signature=signature,
            docstring_first_line=docstring,
            start_line=node.start_point[0],
            end_line=node.end_point[0],
            pagerank_score=0.0  # Will be computed later
        )
```

### 3.5 Incremental Re-parsing

Instead of re-parsing the entire repo on every change:

```python
class IncrementalParser:
    """Re-parse only changed files via filesystem watcher."""
    
    def __init__(self, repo_path: Path):
        self.repo_path = repo_path
        self.symbol_cache: Dict[str, List[Symbol]] = {}
        self.file_hashes: Dict[str, str] = {}
        
        # Set up watchdog observer
        self.observer = Observer()
        self.observer.schedule(
            RepoChangeHandler(self),
            str(repo_path),
            recursive=True
        )
        self.observer.start()
    
    def on_file_changed(self, file_path: Path):
        """Handle a file change event."""
        
        # Check if file hash actually changed
        new_hash = self._compute_hash(file_path)
        if new_hash == self.file_hashes.get(str(file_path)):
            return  # No actual change
        
        # Re-parse only this file
        symbols = self.parser.parse_file(file_path)
        self.symbol_cache[str(file_path)] = symbols
        self.file_hashes[str(file_path)] = new_hash
        
        # Mark graph as stale (will rebuild on next context request)
        self.graph_stale = True
    
    def get_symbols(self, file_path: Path) -> List[Symbol]:
        """Get cached symbols for a file."""
        return self.symbol_cache.get(str(file_path), [])
```

---

## 4. PageRank Symbol Ranking

### 4.1 Call Graph Construction

Build a directed graph where:
- **Nodes** = symbols (functions, classes, methods)
- **Edges** = calls/imports/references between symbols

```python
class CallGraphBuilder:
    """Build a directed call/import graph from parsed symbols."""
    
    def __init__(self):
        self.graph = nx.DiGraph()
    
    def build_graph(self, all_symbols: List[Symbol]) -> nx.DiGraph:
        """Build the complete call graph."""
        
        # Add all symbols as nodes
        for symbol in all_symbols:
            self.graph.add_node(
                symbol.id,  # e.g., "src/auth.py::authenticate"
                symbol=symbol,
                file_path=symbol.file_path,
                name=symbol.name,
                type=symbol.type
            )
        
        # Add edges based on references
        for symbol in all_symbols:
            references = self._extract_references(symbol)
            for ref in references:
                if ref in self.graph.nodes:
                    self.graph.add_edge(symbol.id, ref)
        
        return self.graph
    
    def _extract_references(self, symbol: Symbol) -> List[str]:
        """Extract function/class references from a symbol's signature."""
        
        # Simple approach: look for identifiers in signature
        # More advanced: use tree-sitter to find actual call sites
        
        refs = []
        signature = symbol.signature
        
        # Find potential references (simplified)
        for match in re.finditer(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\b', signature):
            candidate = match.group(1)
            
            # Skip keywords and built-ins
            if candidate in KEYWORDS or candidate in BUILTINS:
                continue
            
            # Try to resolve to a known symbol
            resolved = self._resolve_reference(candidate, symbol.file_path)
            if resolved:
                refs.append(resolved)
        
        return refs
```

### 4.2 PageRank Algorithm

```python
def compute_pagerank(graph: nx.DiGraph, damping: float = 0.85, max_iter: int = 100) -> Dict[str, float]:
    """Compute PageRank scores for all symbols."""
    
    # Use networkx implementation
    ranks = nx.pagerank(graph, alpha=damping, max_iter=max_iter)
    
    # Normalize to [0, 1] range
    max_rank = max(ranks.values()) if ranks else 1.0
    normalized = {k: v / max_rank for k, v in ranks.items()}
    
    return normalized
```

### 4.3 Power Law Observation

In typical repos, ~10% of symbols receive ~80% of references. This means:
- Top 50 symbols often represent the core abstractions
- Bottom 50% are rarely referenced utility functions
- **Strategy:** Always show top-N in skeleton, hide rest behind search

### 4.4 Handling Special Cases

| Case | Treatment |
|------|-----------|
| **Entry points** (`main`, `__init__`) | Boost score artificially (always important) |
| **Test functions** | Lower priority (only relevant during debugging) |
| **Generated code** | Exclude from graph (noise) |
| **Vendor/dependency code** | Separate graph (not part of project skeleton) |
| **Circular imports** | PageRank handles naturally (damping factor) |

---

## 5. Just-in-Time Loading

### 5.1 Tool Interface

Exposed to the agent via tools:

```python
@tool(name="read_lines", cost_estimate=200)
def read_lines(path: str, start: int, end: int) -> str:
    """Read specific line range from a file."""
    ...

@tool(name="read_symbol", cost_estimate=150)
def read_symbol(path: str, symbol_name: str) -> str:
    """Read the full body of a named function/class."""
    ...

@tool(name="search_symbols", cost_estimate=100)
def search_symbols(query: str, scope: Optional[str] = None) -> List[Symbol]:
    """Search for symbols by name/pattern."""
    ...
```

### 5.2 read_lines Implementation

```python
async def read_lines(path: str, start: int, end: int) -> str:
    """Read specific line range from a file."""
    
    # Validate path (security check)
    validated_path = security.validate_path(path, allowed_root=working_dir)
    
    # Check cache
    cache_key = f"{validated_path}:{start}:{end}"
    if cache_key in line_cache:
        return line_cache[cache_key]
    
    # Read from disk
    with open(validated_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # Extract range (1-indexed)
    selected = lines[start-1:end]
    result = ''.join(selected)
    
    # Update cache
    line_cache[cache_key] = result
    
    return result
```

### 5.3 read_symbol Implementation

```python
async def read_symbol(path: str, symbol_name: str) -> str:
    """Read the full body of a named function/class using tree-sitter."""
    
    # Validate path
    validated_path = security.validate_path(path, allowed_root=working_dir)
    
    # Look up symbol in index
    symbol = symbol_index.lookup(validated_path, symbol_name)
    if not symbol:
        raise ValueError(f"Symbol '{symbol_name}' not found in {path}")
    
    # Check cache
    cache_key = f"{validated_path}:{symbol_name}"
    if cache_key in symbol_cache:
        return symbol_cache[cache_key]
    
    # Read full symbol body from disk
    with open(validated_path, 'r', encoding='utf-8') as f:
        source = f.read()
    
    # Extract using tree-sitter spans
    lines = source.split('\n')
    body_lines = lines[symbol.start_line:symbol.end_line+1]
    result = '\n'.join(body_lines)
    
    # Update cache
    symbol_cache[cache_key] = result
    
    return result
```

### 5.4 search_symbols Implementation

```python
async def search_symbols(query: str, scope: Optional[str] = None) -> List[Dict]:
    """Search for symbols by name/pattern."""
    
    # Fuzzy match against symbol names
    matches = fuzzymatch.search(
        query=query,
        candidates=symbol_index.all_symbols,
        key=lambda s: s.name,
        threshold=0.6
    )
    
    # Filter by scope if provided
    if scope:
        matches = [m for m in matches if m.file_path.startswith(scope)]
    
    # Sort by PageRank score
    matches.sort(key=lambda s: s.pagerank_score, reverse=True)
    
    # Return top results
    return [
        {
            "name": m.name,
            "file_path": m.file_path,
            "type": m.type,
            "signature": m.signature,
            "relevance_score": m.pagerank_score
        }
        for m in matches[:20]  # Limit results
    ]
```

---

## 6. Token Budget Enforcement

### 6.1 Context Slot Allocation

| Slot | Default Budget | Behavior at Cap |
|------|---------------|-----------------|
| System + skeleton | 3000 tokens | Truncate low-rank symbols |
| Conversation recap | 1500 tokens | Summarize oldest 50% |
| Tool results | 2000 tokens | Reject new calls, ask to narrow |
| Working reasoning | 1500+ tokens | Force checkpoint/commit |

### 6.2 Skeleton Truncation Strategy

```python
def truncate_skeleton(skeleton: Skeleton, max_tokens: int) -> str:
    """Truncate skeleton to fit within token budget."""
    
    # Sort by PageRank (descending)
    sorted_symbols = sorted(
        skeleton.symbols,
        key=lambda s: s.pagerank_score,
        reverse=True
    )
    
    # Accumulate until budget reached
    output_lines = []
    current_file = None
    token_count = 0
    
    for symbol in sorted_symbols:
        # Add file header if new file
        if symbol.file_path != current_file:
            header = f"\n# {symbol.file_path}\n"
            header_tokens = tokenizer.count_tokens(header)
            
            if token_count + header_tokens > max_tokens:
                break
            
            output_lines.append(header)
            current_file = symbol.file_path
            token_count += header_tokens
        
        # Add symbol line
        symbol_line = f"  {symbol.signature}\n"
        symbol_tokens = tokenizer.count_tokens(symbol_line)
        
        if token_count + symbol_tokens > max_tokens:
            break
        
        output_lines.append(symbol_line)
        token_count += symbol_tokens
    
    # Add truncation notice
    included_count = len([l for l in output_lines if not l.startswith('#')])
    total_count = len(sorted_symbols)
    if included_count < total_count:
        output_lines.append(f"\n... and {total_count - included_count} more symbols\n")
        output_lines.append("Use search_symbols to find specific symbols.\n")
    
    return ''.join(output_lines)
```

### 6.3 Dynamic Budget Adjustment

```python
def adjust_budget_for_task(task_type: str) -> Dict[str, int]:
    """Adjust context slot budgets based on task type."""
    
    base_budgets = {
        "system_skeleton": 3000,
        "conversation_recap": 1500,
        "tool_results": 2000,
        "working_reasoning": 1500
    }
    
    if task_type == "understand_architecture":
        # Need more skeleton, less tool results
        return {
            "system_skeleton": 5000,
            "conversation_recap": 1000,
            "tool_results": 1000,
            "working_reasoning": 1500
        }
    
    elif task_type == "debug_specific_function":
        # Need less skeleton, more tool results for traces
        return {
            "system_skeleton": 1500,
            "conversation_recap": 1500,
            "tool_results": 3000,
            "working_reasoning": 1500
        }
    
    elif task_type == "large_refactor":
        # Balanced, but more tool results for diffs
        return {
            "system_skeleton": 2500,
            "conversation_recap": 1500,
            "tool_results": 3000,
            "working_reasoning": 1500
        }
    
    return base_budgets
```

---

## 7. Caching Strategy

### 7.1 Cache Layers

| Cache Type | Key | TTL | Invalidation Trigger |
|------------|-----|-----|---------------------|
| **Skeleton** | `file_path + file_hash` | Until file change | Watchdog event |
| **PageRank** | `skeleton_hash` | Until skeleton change | Any file change |
| **Line ranges** | `file_path:start:end` | 5 minutes | File change |
| **Symbol bodies** | `file_path:symbol_name` | Until file change | Watchdog event |

### 7.2 Cache Implementation

```python
class ContextCache:
    """Multi-layer cache for context data."""
    
    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.memory_cache = LRUCache(max_size=1000)
        self.disk_cache = DiskCache(cache_dir / "context")
    
    def get_skeleton(self, file_path: str, file_hash: str) -> Optional[List[Symbol]]:
        """Get cached skeleton for a file."""
        
        key = f"skeleton:{file_path}:{file_hash}"
        
        # Check memory first
        if key in self.memory_cache:
            return self.memory_cache[key]
        
        # Check disk
        cached = self.disk_cache.get(key)
        if cached:
            self.memory_cache[key] = cached
            return cached
        
        return None
    
    def set_skeleton(self, file_path: str, file_hash: str, symbols: List[Symbol]):
        """Cache skeleton for a file."""
        
        key = f"skeleton:{file_path}:{file_hash}"
        self.memory_cache[key] = symbols
        self.disk_cache.set(key, symbols)
    
    def invalidate_file(self, file_path: str):
        """Invalidate all cache entries for a file."""
        
        # Clear memory cache entries
        keys_to_remove = [k for k in self.memory_cache if file_path in k]
        for key in keys_to_remove:
            del self.memory_cache[key]
        
        # Disk cache entries will expire naturally or be cleaned on next access
```

### 7.3 Cache Warming

On repo init, pre-populate cache:

```python
async def warm_cache(repo_path: Path):
    """Pre-populate cache on repo initialization."""
    
    # Parse all files in parallel
    tasks = [
        parser.parse_file(file_path)
        for file_path in repo_path.glob("**/*.py")
    ]
    
    all_symbols = await asyncio.gather(*tasks)
    
    # Flatten and cache
    for symbols in all_symbols:
        for symbol in symbols:
            cache.set_skeleton(
                symbol.file_path,
                compute_hash(symbol.file_path),
                [symbol]
            )
    
    # Build and cache PageRank
    graph = build_call_graph(flatten(all_symbols))
    ranks = compute_pagerank(graph)
    cache.set_pagerank(ranks)
```

---

## 8. Configuration

### 8.1 Context Management Config

```toml
# user/config.toml

[context]
max_skeleton_tokens = 3000
enable_pagerank = true
pagemax_iterations = 100
pagemax_damping = 0.85
cache_memory_max_items = 1000
cache_disk_enabled = true
cache_disk_max_size_mb = 500

[languages]
enabled = ["python", "javascript", "typescript", "rust", "go"]
fallback_to_regex = true

[watchdog]
enabled = true
debounce_ms = 100
exclude_patterns = [
    "**/__pycache__/**",
    "**/node_modules/**",
    "**/.git/**",
    "**/*.min.js",
    "**/vendor/**"
]
```

### 8.2 Runtime Overrides

```bash
# Disable PageRank for faster startup (use alphabetical order)
noman --no-pagerank "add logging"

# Increase skeleton budget for complex task
noman --skeleton-budget 5000 "refactor the entire auth module"

# Force re-parse of entire repo
noman context refresh
```

---

## 9. Testing Strategy

### 9.1 Unit Tests

```python
# tests/test_context_mgmt.py

class TestTreeSitterParser:
    
    def test_parse_python_file(self):
        parser = TreeSitterParser("python")
        symbols = parser.parse_file("tests/fixtures/sample.py")
        
        assert len(symbols) > 0
        assert any(s.name == "authenticate" for s in symbols)
        assert all(s.type in ["function", "class", "method"] for s in symbols)
    
    def test_skeleton_compression_ratio(self):
        parser = TreeSitterParser("python")
        symbols = parser.parse_file("tests/fixtures/large_repo/")
        
        skeleton_tokens = count_tokens(format_skeleton(symbols))
        raw_tokens = count_tokens(read_full_repo("tests/fixtures/large_repo/"))
        
        compression_ratio = raw_tokens / skeleton_tokens
        assert compression_ratio > 100  # At least 100x compression

class TestPageRank:
    
    def test_entry_point_ranks_high(self):
        graph = build_test_graph()
        ranks = compute_pagerank(graph)
        
        # Entry point should rank highest
        assert "main" in ranks
        assert ranks["main"] > 0.8
    
    def test_utility_functions_rank_low(self):
        graph = build_test_graph()
        ranks = compute_pagerank(graph)
        
        # Utility functions should rank lower
        assert ranks.get("helper_utility", 0) < 0.3

class TestJITLoading:
    
    def test_read_lines_range(self):
        result = read_lines("tests/fixtures/sample.py", start=10, end=20)
        lines = result.split('\n')
        
        assert len(lines) == 11  # Inclusive range
        assert not result.contains_full_file()
    
    def test_read_symbol_body(self):
        result = read_symbol("tests/fixtures/sample.py", "authenticate")
        
        assert "def authenticate" in result
        assert result.contains_full_function_body()
    
    def test_search_symbols_fuzzy(self):
        results = search_symbols("auth", scope="src/")
        
        assert len(results) > 0
        assert any("auth" in r["name"].lower() for r in results)
        assert results[0]["relevance_score"] > results[-1]["relevance_score"]
```

### 9.2 Integration Tests

```python
# tests/integration/test_context_full.py

async def test_full_context_pipeline():
    """Test complete context loading pipeline."""
    
    context_mgr = ContextManagement(repo_path=test_repo)
    
    # Initialize (parse + PageRank)
    await context_mgr.initialize()
    
    # Request context with budget
    context = await context_mgr.get_context(
        query="authentication flow",
        budget=5000
    )
    
    assert context.skeleton is not None
    assert count_tokens(context.skeleton) <= 5000
    assert "SessionManager" in context.skeleton  # High-rank symbol
    
    # JIT load a symbol
    symbol_body = await context_mgr.read_symbol(
        path="src/auth/session.py",
        symbol_name="create_session"
    )
    
    assert "def create_session" in symbol_body
    assert len(symbol_body) > 100  # Full body, not just signature
```

### 9.3 Performance Benchmarks

```python
# benchmarks/test_context_performance.py

def benchmark_skeleton_generation(benchmark):
    """Benchmark skeleton generation for large repo."""
    
    def run():
        parser = TreeSitterParser("python")
        symbols = parser.parse_file("fixtures/50k_loc_repo/")
        return format_skeleton(symbols)
    
    result = benchmark(run)
    
    # Should complete in <5 seconds for 50k LOC
    assert result.duration < 5.0
    assert result.tokens < 10000

def benchmark_pagerank_computation(benchmark):
    """Benchmark PageRank computation."""
    
    graph = load_test_graph(num_nodes=10000)
    
    def run():
        return compute_pagerank(graph)
    
    result = benchmark(run)
    
    # Should complete in <2 seconds
    assert result.duration < 2.0
```

---

## 10. Performance Targets

| Metric | Target | Measurement |
|--------|--------|-------------|
| Initial parse (50k LOC) | <10 seconds | Time from `noman init` to ready |
| Incremental re-parse (single file) | <100ms | File change to cache update |
| PageRank computation (10k symbols) | <2 seconds | Graph build + ranking |
| Context assembly (with budget) | <500ms | Request to ContextView return |
| JIT symbol load (cached) | <10ms | Cache hit latency |
| JIT symbol load (disk) | <50ms | Cache miss latency |
| Memory footprint (50k LOC skeleton) | <50 MB | RSS delta after init |

---

## 11. Open Questions

1. **Should we support multiple skeleton granularities?** E.g., coarse (classes only) vs fine (all methods). Trade-off: flexibility vs complexity.

2. **How to handle polyglot repos?** Run separate parsers per language, merge into unified graph? Or keep language-specific subgraphs?

3. **Should PageRank be time-decayed?** Recently modified symbols might be more relevant. Add temporal weighting?

4. **What about cross-repo context?** For monorepos or multi-project workspaces, how do we share context across boundaries?

---

## 12. Implementation Checklist

- [ ] Tree-sitter parser setup for Python
- [ ] Symbol extraction queries (Python)
- [ ] Skeleton formatting logic
- [ ] Call graph builder
- [ ] PageRank implementation
- [ ] Symbol index data structure
- [ ] JIT loading tools (read_lines, read_symbol, search_symbols)
- [ ] Multi-layer caching (memory + disk)
- [ ] Watchdog integration for incremental updates
- [ ] Token budget enforcement
- [ ] Skeleton truncation logic
- [ ] Configuration schema
- [ ] CLI commands (`noman context refresh`, `noman context stats`)
- [ ] Unit tests (80%+ coverage)
- [ ] Performance benchmarks
- [ ] Documentation for supported languages

---

## 13. References

- **Tree-sitter**: https://tree-sitter.github.io/
- **PageRank Paper**: https://en.wikipedia.org/wiki/PageRank
- **Parent Design**: [NOMAN_DESIGN.md](./NOMAN_DESIGN.md)
- **Related**: [orchestrator.md](./orchestrator.md), [tools.md](./tools.md)
