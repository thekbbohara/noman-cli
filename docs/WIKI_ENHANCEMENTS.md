# Wiki Enhancements Implementation Plan

## Overview
This document describes 8 enhancements to the noman wiki knowledge graph subsystem, ordered by implementation dependency.

## Enhancement 1: Import Graph Integration (real edges)
**Problem:** Current edges are only pattern-based (e.g., "adapters USES tools"). No real code-level edges.
**Solution:** 
- Add `_extract_class_deps()` to detect class inheritance (extends/implements)
- Add `_extract_cross_module_imports()` to detect which module imports classes from another
- Add `_extract_function_refs()` to detect which classes/functions are imported by name
- Create edges for: `IMPLEMENTS` (inheritance), `DEPENDS_ON` (cross-module imports), `REFERENCES` (function-level refs)
**Files:** `core/wiki/initializer.py` - enhance `_build_dependency_graph()` and `_scan_python_file()`

## Enhancement 2: Conversation-Derived Entity Extraction
**Problem:** Wiki only captures initial scan, not evolving knowledge from conversations.
**Solution:**
- Add `ConversationContext` class in `core/wiki/conversation.py` to track discussed entities
- Extract entity mentions from conversation messages (class names, module names, patterns)
- Auto-create/update wiki pages when entity is mentioned 2+ times
- Store conversation-derived insights as metadata on existing entities
**Files:** `core/wiki/conversation.py` (new), `core/wiki/tools.py` (new handler), `core/tools/bus.py` (hook)

## Enhancement 3: Semantic Search
**Problem:** Current search is exact substring matching — "memory system" won't find "MemoryStore".
**Solution:**
- Add `_embed_text()` method using sentence-transformers (lightweight) or TF-IDF fallback
- Store embeddings alongside pages in `core/wiki/embeddings.py`
- Add `wiki_semantic_search()` tool that returns top-k results by cosine similarity
- Fallback to TF-IDF (sklearn) or simple n-gram overlap if no embedding provider
**Files:** `core/wiki/embeddings.py` (new), `core/wiki/wiki.py` (add embedding storage), `core/wiki/tools.py` (new handler)

## Enhancement 4: Cross-Project Linking
**Problem:** Graphs are siloed per project. No way to link entities across projects.
**Solution:**
- Add `_register_cross_project()` method to Graph for linking entities
- Add `cross_project_links` field to Entity metadata
- Add `wiki_cross_links()` tool to list/link entities across projects
- Auto-link when initializer detects same package name in different projects
**Files:** `core/wiki/graph.py` (add cross-project support), `core/wiki/wiki.py` (add cross-index), `core/wiki/tools.py` (new handler)

## Enhancement 5: On-the-Fly Entity Creation
**Problem:** Requires manual `wiki_init` step. Graph doesn't grow during work.
**Solution:**
- Add `_on_file_read()` hook in ToolBus that checks if file's module is in wiki
- If not, auto-create an entity entry with basic metadata
- Add `wiki_sync()` tool to manually trigger sync of unindexed files
- Track "last scanned" path to avoid re-scanning unchanged files
**Files:** `core/tools/bus.py` (add hook), `core/wiki/tools.py` (add `wiki_sync` handler)

## Enhancement 6: Hotspot/Complexity Integration
**Problem:** No risk assessment data in the graph. AI doesn't know which parts are high-risk.
**Solution:**
- Add `_calculate_complexity()` to analyzer (cyclomatic complexity via ast)
- Add `_calculate_churn()` to analyzer (git log analysis)
- Add `hotspot_score` and `complexity` fields to Entity metadata
- Add `wiki_hotspots()` tool to list high-risk entities
**Files:** `core/wiki/initializer.py` (add complexity/churn analysis), `core/wiki/graph.py` (add fields), `core/wiki/tools.py` (new handler)

## Enhancement 7: Entity Deduplication
**Problem:** "security" and "Security" or "MemoryStore" and "memory_store" would be separate.
**Solution:**
- Add `dedup_entities()` method to Graph that merges near-duplicate entities
- Use name similarity (Levenshtein distance) to find candidates
- Merge metadata, edges, and keep the most recently updated entity
- Add `wiki_dedup()` tool to run deduplication
**Files:** `core/wiki/graph.py` (add `dedup()` method), `core/wiki/tools.py` (new handler)

## Enhancement 8: Graph Visualization
**Problem:** No way for humans to see what the graph contains.
**Solution:**
- Add `render_ascii()` to Graph that produces ASCII tree/edge diagram
- Add `render_mermaid()` to Graph that produces Mermaid flowchart
- Add `wiki_render_graph()` tool that outputs the diagram
- Support depth parameter (1 = direct neighbors, 2 = BFS, etc.)
**Files:** `core/wiki/graph.py` (add render methods), `core/wiki/tools.py` (new handler)

## Implementation Order
1. Import Graph Integration (Foundation for everything)
2. Entity Deduplication (Fix data quality)
3. Semantic Search (Improves discoverability)
4. Cross-Project Linking (Requires semantic search for auto-linking)
5. Hotspot/Complexity Integration (Requires dedup for accuracy)
6. On-the-Fly Entity Creation (Requires cross-project for multi-repo)
7. Conversation-Derived Entity Extraction (Requires all above)
8. Graph Visualization (Requires all above for meaningful output)

## Test Strategy
- All changes must pass existing 274 tests
- Add tests for new wiki features in `tests/test_wiki_*.py`
- Test dedup with known duplicate pairs
- Test semantic search with near-miss queries
- Test cross-project linking with mock projects
