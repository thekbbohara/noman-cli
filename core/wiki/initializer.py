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
import subprocess
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
    """Parse a Python file and extract classes, functions, imports, complexity."""
    result = {
        'classes': [],
        'functions': [],
        'imports': [],
        'docstring': '',
        'complexity': 0,
        'nesting_depth': 0,
    }
    try:
        content = filepath.read_text()
        tree = ast.parse(content)

        # Extract classes with inheritance info
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                bases = []
                for base in node.bases:
                    if isinstance(base, ast.Name):
                        bases.append(base.id)
                    elif isinstance(base, ast.Attribute):
                        bases.append(base.attr)

                ds = ast.get_docstring(node)

                result['classes'].append({
                    'name': node.name,
                    'bases': bases,
                    'docstring': ds[:200] if ds else '',
                    'complexity': _compute_complexity(node),
                })

        # Extract top-level functions with complexity
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.FunctionDef):
                ds = ast.get_docstring(node)
                result['functions'].append({
                    'name': node.name,
                    'docstring': ds[:150] if ds else '',
                    'complexity': _compute_complexity(node),
                    'nesting_depth': _max_nesting(node),
                })

        # Extract imports
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ''
                names = [alias.name for alias in node.names]
                if module and names:
                    result['imports'].append({
                        'module': module,
                        'names': names[:10],
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

        # Compute overall file complexity
        result['complexity'] = sum(_compute_complexity(n) for n in ast.walk(tree)
                                   if isinstance(n, (ast.FunctionDef, ast.ClassDef)))

    except Exception:
        pass

    return result


def _compute_complexity(node: ast.AST) -> int:
    """Compute cyclomatic complexity of a function/class node."""
    complexity = 1
    for child in ast.walk(node):
        if isinstance(child, (ast.If, ast.While, ast.For, ast.ExceptHandler)):
            complexity += 1
        elif isinstance(child, ast.BoolOp):
            complexity += len(child.values) - 1
        elif isinstance(child, (ast.comprehension,)):
            complexity += 1
            if child.ifs:
                complexity += len(child.ifs)
    return complexity


def _max_nesting(node: ast.AST, depth: int = 0) -> int:
    """Compute maximum nesting depth of a node."""
    max_depth = depth
    for child in ast.iter_child_nodes(node):
        nesting = 0
        if isinstance(child, (ast.If, ast.For, ast.While, ast.With, ast.Try, ast.FunctionDef, ast.AsyncFunctionDef)):
            nesting = 1
        child_depth = _max_nesting(child, depth + nesting)
        max_depth = max(max_depth, child_depth)
    return max_depth


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

        # Get classes, functions, imports, and complexity in this package
        all_classes = []
        all_functions = []
        all_imports = []
        total_complexity = 0

        for f in py_files[:20]:  # Limit files per package
            fpath = root_path / f
            parsed = _scan_python_file(fpath, project_path)
            all_classes.extend(parsed['classes'])
            all_functions.extend(parsed['functions'])
            all_imports.extend(parsed['imports'])
            total_complexity += parsed['complexity']

        # Deduplicate imports
        seen_imports = set()
        unique_imports = []
        for imp in all_imports:
            key = f"{imp['module']}:{','.join(imp['names'])}"
            if key not in seen_imports:
                seen_imports.add(key)
                unique_imports.append(imp)

        # Find external imports (not stdlib, not internal)
        external_imports = []
        internal_modules = set()
        for pkg in packages:
            internal_modules.add(pkg['name'])
            internal_modules.add(pkg['path'])

        for imp in unique_imports:
            if imp['module'].startswith(('os', 'sys', 're', 'json', 'pathlib',
                                         'typing', 'dataclasses', 'enum', 'collections',
                                         'asyncio', 'logging', 'abc', 'functools',
                                         'itertools', 'math', 'io', 'datetime',
                                         'unittest', 'contextlib', 'inspect',
                                         'argparse', 'subprocess', 'threading',
                                         'multiprocessing', 'concurrent')):
                continue
            # Check if it's an internal module
            is_internal = False
            for internal in internal_modules:
                if imp['module'].startswith(internal):
                    is_internal = True
                    break
            if not is_internal and imp['module'] not in internal_modules:
                external_imports.append(imp)

        # Detect inheritance patterns
        inheritance_pairs = []
        class_names = {c['name'] for c in all_classes}
        for cls in all_classes:
            for base in cls.get('bases', []):
                if base in class_names and base != cls['name']:
                    inheritance_pairs.append((cls['name'], base))

        packages.append({
            'path': str(rel),
            'name': rel.parts[-1],
            'classes': all_classes[:30],
            'functions': all_functions[:30],
            'imports': unique_imports[:20],
            'external_imports': external_imports,
            'inheritance': inheritance_pairs,
            'docstring': init_doc,
            'file_count': len(py_files),
            'total_complexity': total_complexity,
            'avg_complexity': total_complexity / max(len(all_classes + all_functions), 1),
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


def _calculate_churn(project_path: Path, days: int = 90) -> dict:
    """Calculate git churn metrics for files in the project."""
    result = defaultdict(int)
    try:
        output = subprocess.run(
            ['git', '-C', str(project_path), 'log', '--format=%H', f'--since={days} days ago'],
            capture_output=True, text=True, timeout=30
        )
        if output.returncode != 0:
            return {}

        commits = output.stdout.strip().split('\n')
        for commit in commits:
            if not commit:
                continue
            diff_output = subprocess.run(
                ['git', '-C', str(project_path), 'diff-tree', '--no-commit-id', '--name-only', '-r', commit],
                capture_output=True, text=True, timeout=10
            )
            if diff_output.returncode == 0:
                for file_path in diff_output.stdout.strip().split('\n'):
                    if file_path:
                        result[file_path] += 1
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    total_commits = len([c for c in result.values() if c > 0])
    return {
        'total_commits': total_commits,
        'files': dict(result),
    }




def _scan_typescript_file(filepath: Path, project_path: Path) -> dict:
    """Parse TypeScript file for classes, interfaces, functions."""
    result = {
        'classes': [],
        'interfaces': [],
        'functions': [],
        'imports': [],
        'types': [],
    }
    try:
        text = filepath.read_text()
        
        # Extract classes
        for m in re.finditer(r'class\s+(\w+)(?:\s+extends\s+(\w+))?(?:\s+implements\s+([\w,\s]+))?', text):
            bases = []
            if m.group(2):
                bases.append(m.group(2))
            if m.group(3):
                bases.extend(b.strip() for b in m.group(3).split(','))
            result['classes'].append({
                'name': m.group(1),
                'bases': bases,
                'docstring': '',
            })
        
        # Extract interfaces
        for m in re.finditer(r'interface\s+(\w+)', text):
            result['interfaces'].append({'name': m.group(1)})
        
        # Extract functions
        for m in re.finditer(r'(?:export\s+)?(?:async\s+)?function\s+(\w+)', text):
            result['functions'].append({'name': m.group(1)})
        
        # Extract imports
        for m in re.finditer(r'from\s+[\x27\x22]([^\x27\x22]+)[\x27\x22]\s*import\s+(.+)', text):
            module = m.group(1)
            names = [n.strip().split(' as ')[-1] for n in m.group(2).split(',')]
            result['imports'].append({'module': module, 'names': names[:10]})
        
    except Exception:
        pass
    return result


def _scan_rust_file(filepath: Path, project_path: Path) -> dict:
    """Parse Rust file for structs, impl blocks, functions."""
    result = {
        'structs': [],
        'impls': [],
        'functions': [],
        'imports': [],
    }
    try:
        text = filepath.read_text()
        
        # Extract structs
        for m in re.finditer(r'struct\s+(\w+)', text):
            result['structs'].append({'name': m.group(1)})
        
        # Extract impl blocks
        for m in re.finditer(r'impl\s+(?:<[^>]+>\s+)?(\w+)', text):
            result['impls'].append({'name': m.group(1)})
        
        # Extract functions
        for m in re.finditer(r'(?:pub\s+)?(?:async\s+)?fn\s+(\w+)', text):
            result['functions'].append({'name': m.group(1)})
        
        # Extract imports
        for m in re.finditer(r'use\s+([\w:]+)::', text):
            result['imports'].append({'module': m.group(1)})
        
    except Exception:
        pass
    return result


def _scan_sql_file(filepath: Path, project_path: Path) -> dict:
    """Parse SQL file for tables, columns, indexes."""
    result = {
        'tables': [],
        'columns': [],
        'indexes': [],
    }
    try:
        text = filepath.read_text()
        
        # Extract tables
        for m in re.finditer(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:`?)(\w+)(?:`?)\s*\(', text):
            result['tables'].append({'name': m.group(1)})
        
        # Extract columns
        for m in re.finditer(r'(\w+)\s+(VARCHAR|TEXT|INTEGER|BOOLEAN|FLOAT|DATETIME|JSON)', text):
            result['columns'].append({
                'table': m.group(1),
                'type': m.group(2),
            })
        
        # Extract indexes
        for m in re.finditer(r'CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:`?)(\w+)(?:`?)', text):
            result['indexes'].append({'name': m.group(1)})
        
    except Exception:
        pass
    return result


def _detect_call_chains(packages: list[dict]) -> list[dict]:
    """Detect call chains between high-complexity functions."""
    chains = []
    
    # Build function registry
    func_registry = {}
    for pkg in packages:
        for func in pkg.get('functions', []):
            key = f"{pkg['path']}:{func['name']}"
            func_registry[key] = {
                'name': func['name'],
                'file': pkg['path'],
                'package': pkg['name'],
                'complexity': func.get('complexity', 0),
                'callers': [],
                'callees': [],
            }
    
    # Find cross-package function calls
    for pkg in packages:
        for imp in pkg.get('imports', []):
            # Check if import is from another package's function
            for other_pkg in packages:
                if imp['module'].startswith(other_pkg['path']):
                    for func_name in imp.get('names', []):
                        # Check if this function exists in the other package
                        for other_func in other_pkg.get('functions', []):
                            if func_name == other_func['name']:
                                caller = f"{pkg['path']}:{imp.get('names', ['unknown'])[0]}"
                                callee = f"{other_pkg['path']}:{other_func['name']}"
                                chains.append({
                                    'caller': caller,
                                    'callee': callee,
                                    'type': 'call',
                                    'weight': 1.0,
                                })
    
    return chains[:50]  # Limit




def _extract_type_annotations(filepath: Path) -> dict[str, str]:
    """Extract type annotations from Python file.
    
    Returns dict of {variable_name: type_expression}.
    """
    annotations = {}
    try:
        text = filepath.read_text()
        import ast
        
        tree = ast.parse(text)
        
        for node in ast.walk(tree):
            if isinstance(node, ast.AnnAssign):
                # Annotated assignment: x: int = 5
                if isinstance(node.target, ast.Name):
                    type_str = ast.dump(node.annotation) if node.annotation else ""
                    annotations[node.target.id] = type_str
            
            elif isinstance(node, ast.FunctionDef):
                # Function parameter types
                for arg in node.args.args:
                    if arg.annotation:
                        type_str = ast.dump(arg.annotation)
                        annotations[f"{node.name}.{arg.arg}"] = type_str
                
                # Return type
                if node.returns:
                    type_str = ast.dump(node.returns)
                    annotations[f"{node.name}.__return__"] = type_str
                
                # Class attribute types
                for base in node.bases:
                    if isinstance(base, ast.Name):
                        annotations[f"{node.name}.__bases__"] = base.id
        
        # Class attribute annotations
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                        type_str = ast.dump(item.annotation) if item.annotation else ""
                        annotations[f"{node.name}.{item.target.id}"] = type_str
    
    except Exception:
        pass
    
    return annotations


def _infer_type_relationships(packages: list[dict]) -> list[dict]:
    """Infer relationships from type annotations.
    
    For example, if class A has a field of type B, create an IMPLIES edge.
    """
    relationships = []
    
    # Build class registry
    classes = {}
    for pkg in packages:
        for cls in pkg.get('classes', []):
            key = f"{pkg['path']}:{cls['name']}"
            classes[key] = {
                'name': cls['name'],
                'package': pkg['name'],
                'bases': cls.get('bases', []),
            }
    
    # Find inheritance and field-type relationships
    for key, cls_info in classes.items():
        # Inheritance
        for base in cls_info.get('bases', []):
            if base in classes:
                relationships.append({
                    'source': key,
                    'target': base,
                    'type': 'extends',
                    'weight': 1.0,
                })
        
        # Field types (simplified)
        pkg = next((p for p in packages if p['name'] == cls_info['package']), None)
        if pkg:
            for imp in pkg.get('imports', []):
                if imp['module'].startswith('typing') and any(n in imp['names'] for n in ['List', 'Dict', 'Optional', 'Union']):
                    relationships.append({
                        'source': key,
                        'target': f"module:{imp['module']}",
                        'type': 'uses_type',
                        'weight': 0.5,
                    })
    
    return relationships[:100]

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

        # 5. Calculate churn
        churn_data = _calculate_churn(self._project_path)

        # 5b. Infer type relationships from annotations
        type_relationships = _infer_type_relationships(packages)

        # 6. Create package entities with rich metadata
        for pkg in packages:
            pkg_id = f"module:{_safe_name(pkg['path'])}"
            if pkg_id not in seen_ids:
                # Build summary
                summary_parts = [f"Package with {pkg['file_count']} Python files"]
                if pkg['classes']:
                    summary_parts.append(f"defines {len(pkg['classes'])} classes")
                    summary_parts.append(f"({', '.join(c['name'] for c in pkg['classes'][:5])})")
                if pkg['functions']:
                    summary_parts.append(f"defines {len(pkg['functions'])} functions")
                    summary_parts.append(f"({', '.join(f['name'] for f in pkg['functions'][:5])})")
                if pkg['external_imports']:
                    summary_parts.append(f"imports from {len(pkg['external_imports'])} external modules")
                    for imp in pkg['external_imports'][:3]:
                        summary_parts.append(f"  → {imp['module']}")

                # Add complexity metrics
                if pkg['total_complexity'] > 0:
                    summary_parts.append(f"complexity: {pkg['total_complexity']}")

                # Add dependency info
                if pkg['path'] in dep_graph:
                    deps = dep_graph[pkg['path']]
                    summary_parts.append(f"depends on {len(deps)} packages")

                # Create entity with metadata
                entity = Entity(
                    id=pkg_id,
                    name=pkg['name'],
                    entity_type=EntityType.CONCEPT,
                    scope=str(self._project_path),
                    summary='; '.join(summary_parts),
                    metadata={
                        'file_count': pkg['file_count'],
                        'class_count': len(pkg['classes']),
                        'function_count': len(pkg['functions']),
                        'complexity': pkg['total_complexity'],
                        'external_imports': [i['module'] for i in pkg['external_imports']],
                        'inheritance': pkg.get('inheritance', []),
                    },
                )
                entities.append(entity)
            # Extract type annotations
            type_annotations = {}
            for py_file in pkg.get('_files', []):
                fpath = Path(py_file)
                if fpath.exists():
                    annotations = _extract_type_annotations(fpath)
                    type_annotations.update(annotations)
            
            # Build summary with type info
            summary_parts = [f"Package with {pkg['file_count']} Python files"]
            if pkg['classes']:
                summary_parts.append(f"defines {len(pkg['classes'])} classes")
                summary_parts.append(f"({', '.join(c['name'] for c in pkg['classes'][:5])})")
            if pkg['functions']:
                summary_parts.append(f"defines {len(pkg['functions'])} functions")
                summary_parts.append(f"({', '.join(f['name'] for f in pkg['functions'][:5])})")
            if pkg['external_imports']:
                summary_parts.append(f"imports from {len(pkg['external_imports'])} external modules")
                for imp in pkg['external_imports'][:3]:
                    summary_parts.append(f"  → {imp['module']}")

            # Add complexity metrics
            if pkg['total_complexity'] > 0:
                summary_parts.append(f"complexity: {pkg['total_complexity']}")

            # Add dependency info
            dep_info = ""
            if pkg['path'] in dep_graph:
                deps = dep_graph[pkg['path']]
                summary_parts.append(f"depends on {len(deps)} packages")
                dep_info = f"depends on {len(deps)} packages"

            # Create entity with metadata
            entity = Entity(
                id=pkg_id,
                name=pkg['name'],
                entity_type=EntityType.CONCEPT,
                scope=str(self._project_path),
                summary='; '.join(summary_parts),
                metadata={
                    'file_count': pkg['file_count'],
                    'class_count': len(pkg['classes']),
                    'function_count': len(pkg['functions']),
                    'complexity': pkg['total_complexity'],
                    'external_imports': [i['module'] for i in pkg['external_imports']],
                    'inheritance': pkg.get('inheritance', []),
                    'type_annotations': type_annotations,
                    'call_chains': call_chains,
                    'type_relationships': type_relationships,
                },
            )
            entities.append(entity)
            seen_ids.add(pkg_id)
            edges.append((project_id, pkg_id, EdgeType.PART_OF, f"Part of {project_name}"))


        # Add type relationship edges
        if 'type_relationships' in locals():
            for rel in type_relationships[:50]:
                src_parts = rel['source'].split(':')
                tgt_parts = rel['target'].split(':')
                if len(src_parts) >= 2 and len(tgt_parts) >= 2:
                    src_id = f"module:{_safe_name(src_parts[1])}"
                    tgt_id = f"module:{_safe_name(tgt_parts[1])}"
                    if src_id in seen_ids and tgt_id in seen_ids:
                        edges.append((src_id, tgt_id, EdgeType.DEPENDS_ON, f"Type relationship: {rel['type']}"))


        # 7. Create dependency edges
        for src, targets in dep_graph.items():
            src_pkg = next((p for p in packages if p['path'] == src), None)
            if src_pkg:
                for target in targets:
                    target_pkg = next((p for p in packages if p['path'] == target), None)
                    if target_pkg:
                        src_id = f"module:{_safe_name(src)}"
                        target_id = f"module:{_safe_name(target)}"
                        edges.append((src_id, target_id, EdgeType.DEPENDS_ON, f"Imports from {target}"))

        # 8. Create inheritance edges
        for pkg in packages:
            for class_name, base_name in pkg.get('inheritance', []):
                # Find the module entity for this class
                src_id = f"module:{_safe_name(pkg['path'])}"
                # Create a class-level entity
                class_id = f"class:{_safe_name(pkg['path'])}:{_safe_name(class_name)}"
                if class_id not in seen_ids:
                    entities.append(Entity(
                        id=class_id,
                        name=class_name,
                        entity_type=EntityType.CONCEPT,
                        scope=str(self._project_path),
                        summary=f"Class in {pkg['name']}; extends {base_name}",
                        metadata={'package': pkg['name'], 'type': 'class'},
                    ))
                    seen_ids.add(class_id)
                    edges.append((pkg_id if pkg_id in seen_ids else project_id, class_id, EdgeType.PART_OF, ""))
                edges.append((class_id, f"class:{_safe_name(pkg['path'])}:{_safe_name(base_name)}", EdgeType.EXTENDS, ""))

        # 9. Create key module entities for top-level source dirs
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

        # 10. Identify architectural patterns
        self._identify_patterns(packages, entities, edges, seen_ids, project_id)

        # 11. Create source page
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

        # 12. Feed into wiki
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
