"""Project knowledge graph initializer — smart source code aware version.

Scans a project directory, parses source code to extract meaningful entities
(modules, classes, functions, imports), builds import/dependency edges, and
populates the wiki with a compact but useful knowledge graph.
"""

from __future__ import annotations

import ast
import json
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


from core.wiki.graph import EdgeType, Entity, EntityType, Graph
from core.wiki.wiki import Wiki, WikiPage


# Directories to skip (noise)
SKIP_DIRS = {
    '.venv', 'node_modules', '__pycache__', '.pytest_cache', '.ruff_cache',
    '.git', '.mypy_cache', '.worktrees', '.github', '.vscode', '.idea',
    'dist', 'build', 'target', 'out', '.next', '.nuxt',
}

# Directories to treat as meaningful source dirs
SOURCE_DIRS = {
    'core', 'lib', 'src', 'app', 'cli', 'tools', 'services', 'models',
    'adapters', 'utils', 'components', 'pages', 'api', 'tests', 'scripts',
}

# File extensions to parse for code structure
CODE_EXTENSIONS = {'.py', '.ts', '.tsx', '.js', '.jsx', '.rs', '.go', '.java'}

# Python-specific patterns
PYTHON_IMPORT_RE = re.compile(r'^\s*(?:from\s+([\w.]+)\s+)?import\s+(.+)$')
PYTHON_CLASS_RE = re.compile(r'^class\s+(\w+)')
PYTHON_FUNC_RE = re.compile(r'^def\s+(\w+)')


def _safe_name(text: str) -> str:
    """Sanitize a name for entity ID."""
    return re.sub(r'[^a-zA-Z0-9_\-]', '_', text.lower().strip())


def _scan_python_file(filepath: Path, project_path: Path) -> dict:
    """Parse a Python file and extract classes, functions, imports."""
    result = {
        'classes': [],
        'functions': [],
        'imports': [],
        'docstring': '',
    }
    try:
        content = filepath.read_text()
        tree = ast.parse(content)
        
        # Extract classes
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                bases = []
                for base in node.bases:
                    if isinstance(base, ast.Name):
                        bases.append(base.id)
                    elif isinstance(base, ast.Attribute):
                        bases.append(base.attr)
                
                # Get docstring
                ds = ast.get_docstring(node)
                
                result['classes'].append({
                    'name': node.name,
                    'bases': bases,
                    'docstring': ds[:200] if ds else '',
                })
        
        # Extract top-level functions
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.FunctionDef):
                ds = ast.get_docstring(node)
                result['functions'].append({
                    'name': node.name,
                    'docstring': ds[:150] if ds else '',
                })
        
        # Extract imports
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ''
                names = [alias.name for alias in node.names]
                if module and names:
                    result['imports'].append({
                        'module': module,
                        'names': names[:10],  # Limit for readability
                    })
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    result['imports'].append({
                        'module': alias.name,
                        'names': [],
                    })
        
        # Extract module docstring
        ds = ast.get_docstring(tree)
        if ds:
            result['docstring'] = ds[:300]
            
    except Exception:
        pass
    
    return result


def _get_package_structure(src_path: Path, project_path: Path) -> list[dict]:
    """Get package/module structure from source directories."""
    packages = []
    
    for root, dirs, files in os.walk(src_path):
        # Skip noise
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        
        root_path = Path(root)
        rel = root_path.relative_to(project_path)
        if str(rel).startswith('.'):
            continue
        
        # Only process directories with Python files
        py_files = [f for f in files if f.endswith('.py') and not f.startswith('__')]
        if not py_files:
            continue
        
        # Get __init__.py docstring if available
        init_file = root_path / '__init__.py'
        init_doc = ''
        if init_file.exists():
            try:
                content = init_file.read_text()
                tree = ast.parse(content)
                ds = ast.get_docstring(tree)
                if ds:
                    init_doc = ds[:300]
            except Exception:
                pass
        
        # Get classes and functions in this package
        all_classes = []
        all_functions = []
        all_imports = []
        
        for f in py_files[:20]:  # Limit files per package
            fpath = root_path / f
            parsed = _scan_python_file(fpath, project_path)
            all_classes.extend(parsed['classes'])
            all_functions.extend(parsed['functions'])
            all_imports.extend(parsed['imports'])
        
        # Deduplicate imports
        seen_imports = set()
        unique_imports = []
        for imp in all_imports:
            key = f"{imp['module']}:{','.join(imp['names'])}"
            if key not in seen_imports:
                seen_imports.add(key)
                unique_imports.append(imp)
        
        packages.append({
            'path': str(rel),
            'name': rel.parts[-1],
            'classes': all_classes[:30],  # Limit
            'functions': all_functions[:30],
            'imports': unique_imports[:20],
            'docstring': init_doc,
            'file_count': len(py_files),
        })
    
    return packages


def _build_dependency_graph(packages: list[dict]) -> dict:
    """Build import dependencies between packages."""
    deps = defaultdict(set)
    
    for pkg in packages:
        pkg_key = pkg['path']
        for imp in pkg['imports']:
            # Check if import comes from another package
            for other_pkg in packages:
                other_key = other_pkg['path']
                if imp['module'].startswith(other_key):
                    deps[pkg_key].add(other_key)
    
    return dict(deps)


class ProjectInitializer:
    """Scan a project and build its knowledge graph."""

    def __init__(self, wiki: Wiki, project_path: str | Path) -> None:
        self._wiki = wiki
        self._project_path = Path(project_path).resolve()
        self._graph = wiki.graph
        self._created_entities: list[Entity] = []
        self._created_edges: list[tuple[str, str, EdgeType, str]] = []

    def initialize(self) -> str:
        """Scan the project and populate the wiki. Returns summary."""
        # Check if already initialized
        wiki_dir = self._project_path / ".noman" / "wiki"
        if wiki_dir.exists() and (wiki_dir / "index.json").exists():
            index = json.loads((wiki_dir / "index.json").read_text())
            if index:
                return f"Wiki already initialized for this project ({len(index)} pages). Call wiki_lint to check health."

        entities: list[Entity] = []
        edges: list[tuple[str, str, EdgeType, str]] = []
        seen_ids: set[str] = set()

        # 1. Discover project name
        project_name = self._project_path.name
        pyproject = self._project_path / "pyproject.toml"
        if pyproject.exists():
            name = self._extract_name_from_pyproject(pyproject)
            if name:
                project_name = name

        # 2. Create project entity
        project_id = f"project:{_safe_name(project_name)}"
        project_entity = Entity(
            id=project_id,
            name=project_name,
            entity_type=EntityType.PROJECT,
            scope=str(self._project_path),
            summary=f"Project at {self._project_path}",
        )
        entities.append(project_entity)
        seen_ids.add(project_id)

        # 3. Parse source code from core/src/lib dirs
        packages = []
        for src_dir in ['core', 'src', 'lib', 'app']:
            src_path = self._project_path / src_dir
            if src_path.exists():
                pkgs = _get_package_structure(src_path, self._project_path)
                packages.extend(pkgs)

        # 4. Build dependency graph
        dep_graph = _build_dependency_graph(packages)

        # 5. Create package entities with meaningful summaries
        for pkg in packages:
            pkg_id = f"module:{_safe_name(pkg['path'])}"
            if pkg_id not in seen_ids:
                # Build summary
                summary_parts = [f"Package with {pkg['file_count']} Python files"]
                if pkg['classes']:
                    summary_parts.append(f"defines {len(pkg['classes'])} classes")
                    summary_parts.append(f"({', '.join(c['name'] for c in pkg['classes'][:5])})")
                if pkg['imports']:
                    # Find external imports (not from stdlib)
                    external = [imp for imp in pkg['imports'] 
                                if not imp['module'].startswith(('os', 'sys', 're', 'json', 'pathlib', 
                                                               'typing', 'dataclasses', 'enum', 'collections',
                                                               'asyncio', 'logging', 'abc', 'functools',
                                                               'itertools', 'math', 'io', 'datetime',
                                                               'unittest', 'contextlib', 'inspect',
                                                               'argparse', 'subprocess', 'threading',
                                                               'multiprocessing', 'concurrent'))]
                    if external:
                        summary_parts.append(f"imports from {len(external)} modules")
                
                # Add dependency info
                if pkg['path'] in dep_graph:
                    deps = dep_graph[pkg['path']]
                    summary_parts.append(f"depends on {len(deps)} packages")
                
                entities.append(Entity(
                    id=pkg_id,
                    name=pkg['name'],
                    entity_type=EntityType.CONCEPT,
                    scope=str(self._project_path),
                    summary='; '.join(summary_parts),
                ))
                seen_ids.add(pkg_id)
                edges.append((project_id, pkg_id, EdgeType.PART_OF, f"Part of {project_name}"))

        # 6. Create dependency edges
        for src, targets in dep_graph.items():
            src_pkg = next((p for p in packages if p['path'] == src), None)
            if src_pkg:
                for target in targets:
                    target_pkg = next((p for p in packages if p['path'] == target), None)
                    if target_pkg:
                        src_id = f"module:{_safe_name(src)}"
                        target_id = f"module:{_safe_name(target)}"
                        edges.append((src_id, target_id, EdgeType.DEPENDS_ON, f"Imports from {target}"))

        # 7. Create key module entities for top-level source dirs
        for dir_name in ['core', 'cli', 'tests', 'scripts']:
            dir_path = self._project_path / dir_name
            if dir_path.exists():
                dir_id = f"module:{_safe_name(dir_name)}"
                if dir_id not in seen_ids:
                    entities.append(Entity(
                        id=dir_id,
                        name=dir_name,
                        entity_type=EntityType.CONCEPT,
                        scope=str(self._project_path),
                        summary=f"Directory containing source code",
                    ))
                    seen_ids.add(dir_id)
                    edges.append((project_id, dir_id, EdgeType.PART_OF, f"Part of {project_name}"))

        # 8. Identify architectural patterns
        self._identify_patterns(packages, entities, edges, seen_ids, project_id)

        # 9. Create source page
        source_entity = Entity(
            id=f"source:init:{_safe_name(str(self._project_path))}",
            name=f"Project init: {project_name}",
            entity_type=EntityType.PATTERN,
            scope=str(self._project_path),
            summary=f"Knowledge graph for {project_name}",
        )
        entities.append(source_entity)

        for entity in entities:
            if entity.id != source_entity.id:
                edges.append((
                    source_entity.id, entity.id,
                    EdgeType.ORIGINATED_FROM,
                    f"Created by wiki init of {project_name}",
                ))

        # 10. Feed into wiki
        page_ids = self._wiki.ingest_source(
            source_id=f"init:{_safe_name(str(self._project_path))}",
            source_type="project_init",
            content=f"Project: {project_name}\nPath: {self._project_path}\nPackages parsed: {len(packages)}\nDependencies mapped: {sum(len(v) for v in dep_graph.values())}",
            entities=entities,
            relations=edges,
        )

        self._created_entities = entities
        self._created_edges = edges

        summary = (
            f"Wiki initialized for '{project_name}' at {self._project_path}\n"
            f"  Entities: {len(entities)}\n"
            f"  Edges: {len(edges)}\n"
            f"  Packages parsed: {len(packages)}\n"
            f"  Dependencies mapped: {sum(len(v) for v in dep_graph.values())}\n"
            f"  Pages created: {len(page_ids)}"
        )
        return summary

    def _extract_name_from_pyproject(self, path: Path) -> str | None:
        """Try to extract project name from pyproject.toml."""
        try:
            content = path.read_text()
            m = re.search(r'\[project\].*?name\s*=\s*"([^"]+)"', content, re.DOTALL)
            if m:
                return m.group(1)
            m = re.search(r'\[tool\.poetry\].*?name\s*=\s*"([^"]+)"', content, re.DOTALL)
            if m:
                return m.group(1)
        except Exception:
            pass
        return None

    def _identify_patterns(
        self, packages: list[dict], entities: list[Entity], 
        edges: list[tuple[str, str, EdgeType, str]], 
        seen_ids: set[str], project_id: str
    ) -> None:
        """Identify and create architectural pattern entities."""
        # Check for service layer pattern
        service_dirs = [p for p in packages if 'service' in p['name'].lower() or 'services' in p['path']]
        if service_dirs:
            pattern_id = "pattern:service_layer"
            if pattern_id not in seen_ids:
                entities.append(Entity(
                    id=pattern_id,
                    name="Service Layer",
                    entity_type=EntityType.PATTERN,
                    scope=str(self._project_path),
                    summary="Architecture pattern: business logic in service classes",
                ))
                seen_ids.add(pattern_id)
                edges.append((project_id, pattern_id, EdgeType.USES, "Uses service layer pattern"))
                for pkg in service_dirs:
                    edges.append((f"module:{_safe_name(pkg['path'])}", pattern_id, EdgeType.IMPLEMENTS, "Implements service layer"))

        # Check for adapter pattern
        adapter_dirs = [p for p in packages if 'adapter' in p['name'].lower() or 'adapters' in p['path']]
        if adapter_dirs:
            pattern_id = "pattern:adapter"
            if pattern_id not in seen_ids:
                entities.append(Entity(
                    id=pattern_id,
                    name="Adapter Pattern",
                    entity_type=EntityType.PATTERN,
                    scope=str(self._project_path),
                    summary="Architecture pattern: interfaces for interchangeable components",
                ))
                seen_ids.add(pattern_id)
                edges.append((project_id, pattern_id, EdgeType.USES, "Uses adapter pattern"))
                for pkg in adapter_dirs:
                    edges.append((f"module:{_safe_name(pkg['path'])}", pattern_id, EdgeType.IMPLEMENTS, "Implements adapter pattern"))

        # Check for ORM/model pattern
        model_dirs = [p for p in packages if 'model' in p['name'].lower() or 'models' in p['path']]
        if model_dirs:
            pattern_id = "pattern:orm_models"
            if pattern_id not in seen_ids:
                entities.append(Entity(
                    id=pattern_id,
                    name="ORM Models",
                    entity_type=EntityType.PATTERN,
                    scope=str(self._project_path),
                    summary="Architecture pattern: data models with persistence",
                ))
                seen_ids.add(pattern_id)
                edges.append((project_id, pattern_id, EdgeType.USES, "Uses ORM model pattern"))
                for pkg in model_dirs:
                    edges.append((f"module:{_safe_name(pkg['path'])}", pattern_id, EdgeType.IMPLEMENTS, "Implements ORM models"))

        # Check for CLI pattern
        cli_dirs = [p for p in packages if 'cli' in p['name'].lower() or 'command' in p['path']]
        if cli_dirs:
            pattern_id = "pattern:cli"
            if pattern_id not in seen_ids:
                entities.append(Entity(
                    id=pattern_id,
                    name="CLI Application",
                    entity_type=EntityType.PATTERN,
                    scope=str(self._project_path),
                    summary="Architecture pattern: command-line interface",
                ))
                seen_ids.add(pattern_id)
                edges.append((project_id, pattern_id, EdgeType.USES, "Uses CLI pattern"))
                for pkg in cli_dirs:
                    edges.append((f"module:{_safe_name(pkg['path'])}", pattern_id, EdgeType.IMPLEMENTS, "Implements CLI"))
