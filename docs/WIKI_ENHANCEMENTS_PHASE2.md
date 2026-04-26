# Wiki Enhancement Plan (Phase 2)

## Overview
12 additional improvements to make the wiki truly powerful for AI-assisted development.

## Implementation Order (by dependency)

### Phase 1: Foundation
1. **Incremental updates** (no dependencies)
2. **Graph query language** (uses graph data structures)
3. **Entity lifecycle** (extends Entity schema)

### Phase 2: Intelligence
4. **Auto-extraction from file reads** (uses incremental updates)
5. **Multi-language support** (extends initializer)
6. **Call chain detection** (extends initializer)
7. **Auto cross-project linking** (uses semantic search)

### Phase 3: Context & Visualization
8. **Diff history** (uses incremental updates)
9. **Type annotation relationships** (extends initializer)
10. **Dependency visualization** (extends graph rendering)
11. **Knowledge graph queries** (uses graph query language)
12. **Context-aware summary injection** (uses graph query language)

## Detailed Plans

### 1. Incremental Updates
**Files:** `core/wiki/initializer.py`, `core/wiki/wiki.py`
- Add `_file_hashes` dict to track file → hash mappings
- On init, compare current hashes with stored hashes
- Only re-parse files that have changed
- Store new hashes after processing

### 2. Graph Query Language
**Files:** `core/wiki/query.py` (new), `core/wiki/tools.py`
- Natural language → structured query parser
- Support: "show packages that depend on X", "find classes with complexity > N", "list entities of type X"
- Returns formatted results

### 3. Entity Lifecycle
**Files:** `core/wiki/graph.py`
- Add `status` field to Entity: "active", "deprecated", "archived", "superseded"
- Add `superseded_by` field
- Filter functions to exclude archived entities by default
- Add `wiki_entity_status()` tool to update lifecycle

### 4. Auto-Extraction from File Reads
**Files:** `core/tools/bus.py`, `core/wiki/auto_extract.py` (new)
- Hook into ToolBus when a file is read
- Check if file's module is in wiki
- If not, auto-extract and create entity
- Track "last scanned" to avoid re-processing

### 5. Multi-Language Support
**Files:** `core/wiki/initializer.py`
- Add TypeScript parser (AST + regex patterns)
- Add Rust parser (regex patterns for structs, impl blocks)
- Add SQL schema parser (regex patterns for tables, columns)
- Integrate with existing package structure scanner

### 6. Call Chain Detection
**Files:** `core/wiki/initializer.py`
- Detect method calls across files
- Build call graph for high-complexity functions
- Store as call_chain metadata on entities

### 7. Auto Cross-Project Linking
**Files:** `core/wiki/crosslink.py` (new)
- Compare embeddings across projects
- Auto-link entities with similarity > threshold
- Update wiki with detected links

### 8. Diff History
**Files:** `core/wiki/diff.py` (new)
- Track changes between wiki versions
- Store diff as structured data
- Add `wiki_diff()` tool to view changes

### 9. Type Annotation Relationships
**Files:** `core/wiki/initializer.py`
- Parse type annotations in Python
- Extract inferred relationships
- Add as edges in graph

### 10. Dependency Visualization
**Files:** `core/wiki/graph.py`
- Enhanced ASCII diagrams with edge details
- Color-coded risk levels
- Interactive-style text output

### 11. Knowledge Graph Queries
**Files:** `core/wiki/query.py` (extends #2)
- Natural language → graph query translation
- "Which packages use security?" → find all packages with DEPENDS_ON security
- "Show me complex classes" → filter by complexity metadata

### 12. Context-Aware Summary Injection
**Files:** `core/wiki/context.py` (new)
- Analyze what the AI is currently working on
- Select most relevant entities for summary
- Inject into system prompt dynamically

## Test Strategy
- All changes must pass existing 322 tests
- Add tests for each new feature
- Test incremental updates with file modification
- Test multi-language parsing with sample files
