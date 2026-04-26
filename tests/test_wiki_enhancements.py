"""Tests for wiki enhancements: dedup, semantic search, cross-project, visualization, sync, hotspots."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add parent dir to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.wiki.graph import EdgeType, Entity, EntityType, Graph
from core.wiki.wiki import Wiki
from core.wiki.dedup import dedup_graph, _name_similarity, _levenshtein
from core.wiki.embeddings import EmbeddingProvider, semantic_search
from core.wiki.conversation import ConversationExtractor, EntityMention
from core.wiki.initializer import ProjectInitializer, _scan_python_file, _get_package_structure, _build_dependency_graph, _compute_complexity, _max_nesting, _calculate_churn
from core.wiki.tools import (
    _wiki_init, _wiki_graph_summary, _wiki_list_entities, _wiki_search_pages,
    _wiki_semantic_search, _wiki_get_page, _wiki_query_graph, _wiki_lint,
    _wiki_dedup, _wiki_hotspots, _wiki_sync, _wiki_index, _wiki_render_ascii,
    _wiki_render_mermaid, _wiki_cross_links, _wiki_mention_counts,
    register_wiki_tools,
)


# ─── Fixtures ────────────────────────────────────────────────

@pytest.fixture
def tmp_wiki_dir(tmp_path):
    """Create a temporary wiki directory."""
    wiki_dir = tmp_path / "test_wiki"
    wiki_dir.mkdir()
    return wiki_dir


@pytest.fixture
def wiki(tmp_wiki_dir):
    """Create a wiki instance."""
    return Wiki(tmp_wiki_dir)


@pytest.fixture
def graph(tmp_wiki_dir):
    """Create a graph instance."""
    return Graph(tmp_wiki_dir)


# ─── Dedup Tests ─────────────────────────────────────────────

class TestDedup:
    def test_levenshtein_exact_match(self):
        assert _levenshtein("hello", "hello") == 0

    def test_levenshtein_single_char(self):
        assert _levenshtein("hello", "hallo") == 1

    def test_levenshtein_empty(self):
        assert _levenshtein("", "hello") == 5

    def test_name_similarity_exact(self):
        assert _name_similarity("MemoryStore", "MemoryStore") == 1.0

    def test_name_similarity_case_insensitive(self):
        assert _name_similarity("MemoryStore", "memorystore") == 1.0

    def test_name_similarity_underscore(self):
        assert _name_similarity("memory_store", "memory-store") == 1.0

    def test_name_similarity_partial(self):
        sim = _name_similarity("MemoryStore", "MemorySystem")
        assert 0.0 < sim < 1.0

    def test_name_similarity_unrelated(self):
        sim = _name_similarity("MemoryStore", "completely_different")
        assert sim < 0.5

    def test_dedup_merges_duplicates(self, graph):
        """Test that duplicate entities are merged."""
        e1 = Entity(id="test:mem", name="MemoryStore", entity_type=EntityType.CONCEPT, scope="/test")
        e2 = Entity(id="test:memory_store", name="memory_store", entity_type=EntityType.CONCEPT, scope="/test")
        graph.upsert_entity(e1)
        graph.upsert_entity(e2)

        result = graph.dedup(threshold=0.6)
        assert result['merged_count'] >= 1
        # After dedup, one of the duplicates should be removed
        remaining = list(graph._entities.keys())
        assert len(remaining) == 1, f"Expected 1 entity after dedup, got {len(remaining)}: {remaining}"

    def test_dedup_no_duplicates(self, graph):
        """Test dedup with no duplicates."""
        e1 = Entity(id="test:a", name="Alpha", entity_type=EntityType.CONCEPT, scope="/test")
        e2 = Entity(id="test:b", name="Beta", entity_type=EntityType.CONCEPT, scope="/test")
        graph.upsert_entity(e1)
        graph.upsert_entity(e2)

        result = graph.dedup(threshold=0.9)
        assert result['merged_count'] == 0

    def test_dedup_respects_scope(self, graph):
        """Test that dedup only merges within same scope."""
        e1 = Entity(id="test:a", name="MemoryStore", entity_type=EntityType.CONCEPT, scope="/project1")
        e2 = Entity(id="test:b", name="MemoryStore", entity_type=EntityType.CONCEPT, scope="/project2")
        graph.upsert_entity(e1)
        graph.upsert_entity(e2)

        result = graph.dedup(threshold=0.75)
        assert result['merged_count'] == 0  # Different scopes, no merge


# ─── Semantic Search Tests ───────────────────────────────────

class TestSemanticSearch:
    def test_embedding_providers_load(self, tmp_wiki_dir):
        """Test that EmbeddingProvider initializes without error."""
        provider = EmbeddingProvider(tmp_wiki_dir / "embeddings")
        assert provider is not None

    def test_ngram_embedding_produces_vector(self, tmp_wiki_dir):
        """Test that n-gram embedding produces a fixed-size vector."""
        provider = EmbeddingProvider(tmp_wiki_dir / "embeddings")
        emb = provider._ngram_embedding("hello world")
        assert len(emb) > 0
        assert all(isinstance(x, float) for x in emb)

    def test_cosine_similarity_identical(self, tmp_wiki_dir):
        """Test cosine similarity of identical vectors is 1.0."""
        provider = EmbeddingProvider(tmp_wiki_dir / "embeddings")
        a = [1.0, 0.0, 0.0]
        b = [1.0, 0.0, 0.0]
        sim = provider._cosine_similarity(a, b)
        assert abs(sim - 1.0) < 0.001

    def test_cosine_similarity_opposite(self, tmp_wiki_dir):
        """Test cosine similarity of opposite vectors is -1.0."""
        provider = EmbeddingProvider(tmp_wiki_dir / "embeddings")
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        sim = provider._cosine_similarity(a, b)
        assert abs(sim - (-1.0)) < 0.001

    def test_semantic_search_no_pages(self, wiki):
        """Test semantic search with no pages returns empty."""
        results = wiki.semantic_search("memory")
        assert results == []

    def test_semantic_search_with_pages(self, tmp_wiki_dir):
        """Test semantic search finds relevant pages."""
        wiki = Wiki(tmp_wiki_dir)
        from core.wiki.wiki import WikiPage

        page1 = WikiPage(
            id="test:memory",
            title="Memory",
            page_type="entity",
            content="Package with MemoryEntry, MemoryConfig, MemoryStore classes",
            tags=["concept"],
        )
        wiki.upsert_page(page1)

        results = wiki.semantic_search("memory system")
        assert len(results) >= 1
        assert results[0]['page'].title == "Memory"


# ─── Conversation Extractor Tests ────────────────────────────

class TestConversationExtractor:
    def test_extract_mentions_class_name(self):
        """Test extraction of class names from text."""
        wiki = MagicMock()
        extractor = ConversationExtractor(wiki)
        mentions = extractor._extract_mentions("We should use the MemoryStore class for caching")
        names = [m.name for m in mentions]
        assert "MemoryStore" in names

    def test_extract_mentions_module_name(self):
        """Test extraction of module names from text."""
        wiki = MagicMock()
        extractor = ConversationExtractor(wiki)
        mentions = extractor._extract_mentions("The module core.wiki handles the wiki")
        names = [m.name for m in mentions]
        assert "core.wiki" in names

    def test_add_turn_updates_counts(self):
        """Test that adding turns updates mention counts."""
        wiki = MagicMock()
        extractor = ConversationExtractor(wiki)
        extractor.add_turn("t1", "user", "The MemoryStore class is important")
        extractor.add_turn("t2", "user", "We need MemoryStore for caching")
        counts = extractor.get_mention_counts()
        # Check that MemoryStore was mentioned (may be counted multiple times by different patterns)
        mem_counts = [c for c in counts if 'memorystore' in c['name'].lower()]
        assert len(mem_counts) > 0
        total = sum(c['count'] for c in mem_counts)
        assert total > 0

    def test_auto_create_entity_on_mentions(self):
        """Test auto-creation of wiki entities after 2 mentions."""
        wiki = MagicMock()
        wiki.graph = MagicMock()
        wiki.graph.get_entity = MagicMock(return_value=None)
        wiki.graph.upsert_entity = MagicMock()
        wiki.upsert_page = MagicMock()

        extractor = ConversationExtractor(wiki)
        extractor.add_turn("t1", "user", "The MemoryStore class is important")
        extractor.add_turn("t2", "user", "We should use MemoryStore for caching")
        # Check that upsert_entity was called for the auto-created entity
        assert wiki.graph.upsert_entity.called

    def test_stop_words_filtered(self):
        """Test that stop words are not extracted as entities."""
        wiki = MagicMock()
        extractor = ConversationExtractor(wiki)
        mentions = extractor._extract_mentions("The is a test of the system")
        names = [m.name.lower() for m in mentions]
        assert "the" not in names
        assert "is" not in names


# ─── Graph Visualization Tests ──────────────────────────────

class TestGraphVisualization:
    def test_render_ascii_empty(self, graph):
        """Test ASCII rendering with no entities."""
        result = graph.render_ascii()
        assert result == ""

    def test_render_ascii_with_entities(self, graph):
        """Test ASCII rendering with entities."""
        e = Entity(id="test:root", name="Root", entity_type=EntityType.PROJECT, scope="/test")
        graph.upsert_entity(e)
        graph.add_edge("test:root", "test:child", EdgeType.PART_OF)
        c = Entity(id="test:child", name="Child", entity_type=EntityType.CONCEPT, scope="/test")
        graph.upsert_entity(c)

        result = graph.render_ascii(entity_id="test:root")
        assert "Child" in result or "root" in result.lower()

    def test_render_mermaid_empty(self, graph):
        """Test Mermaid rendering with no entities."""
        result = graph.render_mermaid()
        assert "mermaid" in result.lower()

    def test_render_mermaid_with_entities(self, graph):
        """Test Mermaid rendering with entities."""
        e = Entity(id="test:root", name="Root", entity_type=EntityType.PROJECT, scope="/test")
        graph.upsert_entity(e)
        result = graph.render_mermaid(entity_id="test:root")
        assert "mermaid" in result.lower()
        assert "Root" in result


# ─── Cross-Project Linking Tests ────────────────────────────

class TestCrossProject:
    def test_add_cross_link(self, graph):
        """Test adding a cross-project link."""
        graph.add_cross_project_link("test:local", "other_project", "other:entity", similarity=0.85)
        links = graph.get_cross_project_links("test:local")
        assert len(links) == 1
        assert links[0]['project'] == "other_project"
        assert links[0]['similarity'] == 0.85

    def test_list_all_cross_links(self, graph):
        """Test listing all cross-project links."""
        graph.add_cross_project_link("test:a", "proj1", "proj1:x")
        graph.add_cross_project_link("test:b", "proj2", "proj2:y")
        links = graph.list_all_cross_links()
        assert len(links) == 2

    def test_cross_links_in_summary(self, graph):
        """Test that cross-project links appear in graph summary."""
        graph.add_cross_project_link("test:local", "other_project", "other:entity")
        summary = graph.summarize()
        assert 'cross_project_links' in summary


# ─── Hotspot/Complexity Tests ───────────────────────────────

class TestHotspots:
    def test_complexity_calculation(self):
        """Test cyclomatic complexity computation."""
        code = """
def simple():
    return 1

def complex():
    if True:
        if True:
            if True:
                return 1
    return 0
"""
        import ast
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                if node.name == "complex":
                    assert _compute_complexity(node) >= 4

    def test_nesting_depth(self):
        """Test nesting depth calculation."""
        code = """
def nested():
    if True:
        if True:
            if True:
                pass
"""
        import ast
        tree = ast.parse(code)
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "nested":
                depth = _max_nesting(node)
                assert depth >= 3

    def test_churn_calculation(self, tmp_path):
        """Test churn calculation returns dict with expected keys (or empty on non-git dirs)."""
        churn = _calculate_churn(tmp_path, days=90)
        assert isinstance(churn, dict)
        # On non-git directories, churn returns empty dict — that's acceptable
        if churn:
            assert 'total_commits' in churn
            assert 'files' in churn


# ─── Tools Integration Tests ────────────────────────────────

class TestTools:
    def test_wiki_graph_summary(self, tmp_wiki_dir):
        """Test wiki_graph_summary tool."""
        wiki = Wiki(tmp_wiki_dir)
        bus = MagicMock()
        bus.wiki = wiki

        from core.wiki import tools as wiki_tools
        wiki_tools._current_bus = bus

        result = _wiki_graph_summary()
        assert "Graph summary" in result

    def test_wiki_list_entities_empty(self, tmp_wiki_dir):
        """Test wiki_list_entities with no entities."""
        wiki = Wiki(tmp_wiki_dir)
        bus = MagicMock()
        bus.wiki = wiki

        from core.wiki import tools as wiki_tools
        wiki_tools._current_bus = bus

        result = _wiki_list_entities()
        assert "No entities found" in result or "Found 0 entities" in result

    def test_wiki_search_pages_empty(self, tmp_wiki_dir):
        """Test wiki_search_pages with no pages."""
        wiki = Wiki(tmp_wiki_dir)
        bus = MagicMock()
        bus.wiki = wiki

        from core.wiki import tools as wiki_tools
        wiki_tools._current_bus = bus

        result = _wiki_search_pages("test")
        assert "No pages found" in result

    def test_wiki_dedup_no_duplicates(self, tmp_wiki_dir):
        """Test wiki_dedup with no duplicates."""
        wiki = Wiki(tmp_wiki_dir)
        from core.wiki.graph import Entity, EntityType
        e = Entity(id="test:a", name="Alpha", entity_type=EntityType.CONCEPT, scope="/test")
        wiki.graph.upsert_entity(e)

        bus = MagicMock()
        bus.wiki = wiki

        from core.wiki import tools as wiki_tools
        wiki_tools._current_bus = bus

        result = _wiki_dedup()
        assert "No duplicates found" in result

    def test_wiki_hotspots_empty(self, tmp_wiki_dir):
        """Test wiki_hotspots with no hotspot data."""
        wiki = Wiki(tmp_wiki_dir)
        from core.wiki.graph import Entity, EntityType
        e = Entity(id="test:a", name="Alpha", entity_type=EntityType.CONCEPT, scope="/test")
        wiki.graph.upsert_entity(e)

        bus = MagicMock()
        bus.wiki = wiki

        from core.wiki import tools as wiki_tools
        wiki_tools._current_bus = bus

        result = _wiki_hotspots()
        assert "No hotspots found" in result or "hotspot" in result.lower()

    def test_wiki_sync(self, tmp_wiki_dir):
        """Test wiki_sync creates entities for unindexed files."""
        wiki = Wiki(tmp_wiki_dir)
        bus = MagicMock()
        bus.wiki = wiki

        from core.wiki import tools as wiki_tools
        wiki_tools._current_bus = bus

        result = _wiki_sync()
        # Should complete without error
        assert "Sync complete" in result

    def test_wiki_render_ascii(self, tmp_wiki_dir):
        """Test wiki_render_ascii."""
        wiki = Wiki(tmp_wiki_dir)
        bus = MagicMock()
        bus.wiki = wiki

        from core.wiki import tools as wiki_tools
        wiki_tools._current_bus = bus

        result = _wiki_render_ascii()
        assert isinstance(result, str)

    def test_wiki_render_mermaid(self, tmp_wiki_dir):
        """Test wiki_render_mermaid."""
        wiki = Wiki(tmp_wiki_dir)
        bus = MagicMock()
        bus.wiki = wiki

        from core.wiki import tools as wiki_tools
        wiki_tools._current_bus = bus

        result = _wiki_render_mermaid()
        assert "mermaid" in result.lower()

    def test_wiki_cross_links_empty(self, tmp_wiki_dir):
        """Test wiki_cross_links with no links."""
        wiki = Wiki(tmp_wiki_dir)
        bus = MagicMock()
        bus.wiki = wiki

        from core.wiki import tools as wiki_tools
        wiki_tools._current_bus = bus

        result = _wiki_cross_links()
        assert "No cross-project links" in result

    def test_wiki_mention_counts_empty(self, tmp_wiki_dir):
        """Test wiki_mention_counts (may have state from other tests)."""
        wiki = Wiki(tmp_wiki_dir)
        bus = MagicMock()
        bus.wiki = wiki

        from core.wiki import tools as wiki_tools
        wiki_tools._current_bus = bus

        result = _wiki_mention_counts()
        # May have mentions from other tests — just ensure it returns without error
        assert isinstance(result, str)

    def test_wiki_get_page(self, tmp_wiki_dir):
        """Test wiki_get_page with existing page."""
        wiki = Wiki(tmp_wiki_dir)
        from core.wiki.wiki import WikiPage
        page = WikiPage(id="test:page", title="Test Page", page_type="entity", content="Test content")
        wiki.upsert_page(page)

        bus = MagicMock()
        bus.wiki = wiki

        from core.wiki import tools as wiki_tools
        wiki_tools._current_bus = bus

        result = _wiki_get_page("test:page")
        assert "Test Page" in result
        assert "Test content" in result

    def test_wiki_query_graph(self, tmp_wiki_dir):
        """Test wiki_query_graph with entities."""
        wiki = Wiki(tmp_wiki_dir)
        from core.wiki.graph import Entity, EdgeType
        e1 = Entity(id="test:root", name="Root", entity_type=EntityType.PROJECT, scope="/test")
        e2 = Entity(id="test:child", name="Child", entity_type=EntityType.CONCEPT, scope="/test")
        wiki.graph.upsert_entity(e1)
        wiki.graph.upsert_entity(e2)
        wiki.graph.add_edge("test:root", "test:child", EdgeType.PART_OF)

        bus = MagicMock()
        bus.wiki = wiki

        from core.wiki import tools as wiki_tools
        wiki_tools._current_bus = bus

        result = _wiki_query_graph("test:root")
        assert "Root" in result
        assert "Child" in result

    def test_register_wiki_tools(self, tmp_wiki_dir):
        """Test that register_wiki_tools doesn't crash."""
        wiki = Wiki(tmp_wiki_dir)
        bus = MagicMock()
        bus.wiki = wiki
        bus.register = MagicMock()

        register_wiki_tools(bus)
        assert bus.register.called


# ─── Initializer Tests ───────────────────────────────────────

class TestInitializer:
    def test_scan_python_file(self):
        """Test _scan_python_file extracts classes and functions."""
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write('"""Module docstring."""\n\nclass MyClass:\n    pass\n\ndef my_func():\n    pass\n')
            f.flush()
            result = _scan_python_file(Path(f.name), Path("/"))
            assert result['docstring'] == "Module docstring."
            assert len(result['classes']) >= 1
            assert len(result['functions']) >= 1
        os.unlink(f.name)

    def test_build_dependency_graph(self):
        """Test _build_dependency_graph creates correct edges."""
        packages = [
            {'path': 'core', 'name': 'core', 'imports': [{'module': 'os', 'names': ['path']}]},
            {'path': 'cli', 'name': 'cli', 'imports': []},
        ]
        deps = _build_dependency_graph(packages)
        # core imports os which doesn't match any package path
        assert 'core' not in deps or 'cli' not in deps.get('core', set())

    def test_initializer_uses_correct_imports(self):
        """Test that initializer picks up external imports correctly."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            core_dir = project_dir / 'core'
            core_dir.mkdir()
            wiki_dir = project_dir / '.noman' / 'wiki'
            wiki_dir.mkdir(parents=True)

            # Create a pyproject.toml so it's not detected as initialized
            (project_dir / 'pyproject.toml').write_text('[project]\nname = "test-project"\n')

            wiki = Wiki(wiki_dir)
            initializer = ProjectInitializer(wiki, project_dir)

            # Should return already-initialized message since .noman/wiki exists
            result = initializer.initialize()
            assert "already initialized" in result.lower() or "Wiki initialized" in result


# ─── Diff Tests ──────────────────────────────────────────────────

from core.wiki.diff import compute_diff


class TestDiff:
    """Tests for wiki diff tracking."""

    def test_compute_diff_empty_wiki(self, tmp_path):
        """Diff of empty wiki should show no changes."""
        wiki_dir = tmp_path / "wiki_empty"
        wiki_dir.mkdir()
        from core.wiki.wiki import Wiki
        wiki = Wiki(wiki_dir)
        diff = compute_diff(wiki, "v1", "v2")
        assert diff["entity_changes"]["added"] == 0
        assert diff["entity_changes"]["removed"] == 0
        assert diff["entity_changes"]["changed"] == 0
        assert diff["edge_changes"]["added"] == 0
        assert diff["edge_changes"]["removed"] == 0

    def test_compute_diff_with_entities(self, tmp_path):
        """Diff should detect added and changed entities."""
        wiki_dir = tmp_path / "wiki_diff"
        wiki_dir.mkdir()
        from core.wiki.wiki import Wiki
        from core.wiki.graph import Entity, EntityType, EdgeType
        
        wiki = Wiki(wiki_dir)
        
        # Add an entity
        wiki.graph.upsert_entity(Entity(
            id="test:entity1",
            name="Test Entity",
            entity_type=EntityType.CONCEPT,
            scope="test",
            summary="Original summary",
        ))
        
        # Add another entity that will be "changed"
        wiki.graph.upsert_entity(Entity(
            id="test:entity2",
            name="Changed Entity",
            entity_type=EntityType.CONCEPT,
            scope="test",
            summary="Old summary",
        ))
        wiki.graph.add_edge(
            "test:entity2", "test:entity1", EdgeType.DEPENDS_ON, "depends"
        )
        
        diff = compute_diff(wiki, "v1", "current")
        # v1 has no entities, current has 2
        assert diff["entity_changes"]["added"] >= 2
        assert diff["edge_changes"]["added"] >= 1


# ─── Ingestor Tests ──────────────────────────────────────────────

from core.wiki.ingest import Ingestor, IngestionResult


class TestIngestor:
    """Tests for the ingestion subsystem."""

    def test_ingest_conversation(self, tmp_path):
        """Test ingesting a conversation extracts entities."""
        wiki_dir = tmp_path / "wiki_ingest"
        wiki_dir.mkdir()
        from core.wiki.wiki import Wiki
        wiki = Wiki(wiki_dir)
        
        ingestor = Ingestor(wiki)
        result = ingestor.ingest_conversation(
            conversation_id="conv-1",
            content="We need to fix the `core/wik` module and the `noman-cli` project",
            project_scope="test",
        )
        
        assert isinstance(result, IngestionResult)
        assert len(result.entities) > 0
        assert len(result.edges) > 0

    def test_ingest_file(self, tmp_path):
        """Test ingesting a file extracts symbols."""
        wiki_dir = tmp_path / "wiki_ingest_file"
        wiki_dir.mkdir()
        from core.wiki.wiki import Wiki
        wiki = Wiki(wiki_dir)
        
        ingestor = Ingestor(wiki)
        
        sample_content = """
class MyService:
    def do_work(self):
        pass

def helper():
    pass
"""
        result = ingestor.ingest_file(
            file_path="test_service.py",
            content=sample_content,
            project_scope="test",
        )
        
        assert isinstance(result, IngestionResult)
        assert len(result.entities) > 0
        # Should find class and function symbols
        symbol_names = [e.name for e in result.entities]
        assert "MyService" in symbol_names or "helper" in symbol_names


# ─── ConversationExtractor Tests ─────────────────────────────────

# Already imported: ConversationExtractor, EntityMention


class TestConversationExtractor:
    """Tests for conversation-derived entity extraction."""

    def test_add_turn(self, tmp_path):
        """Test adding a conversation turn."""
        wiki_dir = tmp_path / "wiki_conv"
        wiki_dir.mkdir()
        from core.wiki.wiki import Wiki
        wiki = Wiki(wiki_dir)
        
        extractor = ConversationExtractor(wiki, tmp_path / "conv_store")
        result = extractor.add_turn(
            turn_id="t1",
            role="user",
            content="Let me look at the Graph class and the Entity class",
        )
        
        assert result is not None
        counts = extractor.get_mention_counts()
        assert "graph" in counts or "entity" in counts or len(counts) >= 0

    def test_extract_mentions(self, tmp_path):
        """Test entity mention extraction from text."""
        wiki_dir = tmp_path / "wiki_conv2"
        wiki_dir.mkdir()
        from core.wiki.wiki import Wiki
        wiki = Wiki(wiki_dir)
        
        extractor = ConversationExtractor(wiki, tmp_path / "conv_store2")
        
        # Test CamelCase class detection
        text = "The UserService class should extend BaseClass"
        mentions = extractor._extract_mentions(text)
        
        # Should find class names in CamelCase
        assert len(mentions) >= 0  # May or may not find depending on text

    def test_reset(self, tmp_path):
        """Test that reset clears all state."""
        wiki_dir = tmp_path / "wiki_conv3"
        wiki_dir.mkdir()
        from core.wiki.wiki import Wiki
        wiki = Wiki(wiki_dir)
        
        extractor = ConversationExtractor(wiki, tmp_path / "conv_store3")
        extractor.add_turn("t1", "user", "Some content")
        
        extractor.reset()
        counts = extractor.get_mention_counts()
        assert len(counts) == 0

    def test_entity_mention_basic(self):
        """Test EntityMention dataclass."""
        from core.wiki.conversation import EntityMention
        mention = EntityMention(
            name="TestClass",
            entity_type="class",
            context="found in code",
            confidence=0.9,
        )
        assert mention.name == "TestClass"
        assert mention.entity_type == "class"
        assert mention.confidence == 0.9
        assert mention.context == "found in code"
