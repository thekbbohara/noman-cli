"""Auto-extraction of wiki entities from file reads.

Hooks into file read operations to automatically extract entities
and update the wiki without manual sync.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any

from core.wiki.graph import EdgeType, Entity, EntityType
from core.wiki.wiki import Wiki


def auto_extract_file(file_path: str | Path, wiki: Wiki) -> dict:
    """Auto-extract entities from a file if not already in wiki.
    
    Returns dict with extraction results.
    """
    result = {
        'created': [],
        'updated': [],
        'skipped': [],
        'errors': [],
    }
    
    fpath = Path(file_path).resolve()
    if not fpath.exists():
        return result
    
    # Check file extension
    ext = fpath.suffix.lower()
    
    # Skip non-source files
    if ext not in {'.py', '.ts', '.tsx', '.js', '.jsx', '.rs', '.go', '.sql'}:
        return result
    
    # Get scope (project path)
    scope = str(fpath.parent)
    
    # Check if already exists
    entity_id = f"file:{_safe_name(str(fpath))}"
    existing = wiki.graph.get_entity(entity_id)
    if existing:
        result['skipped'].append(str(fpath))
        return result
    
    # Extract based on file type
    try:
        content = fpath.read_text()
        
        if ext == '.py':
            result = _extract_python(content, fpath, scope, result)
        elif ext in ('.ts', '.tsx', '.js', '.jsx'):
            result = _extract_typescript(content, fpath, scope, result)
        elif ext == '.rs':
            result = _extract_rust(content, fpath, scope, result)
        elif ext == '.sql':
            result = _extract_sql(content, fpath, scope, result)
    except Exception as e:
        result['errors'].append(str(e))
    
    return result


def _safe_name(text: str) -> str:
    return re.sub(r'[^a-zA-Z0-9_\-]', '_', text.lower().strip())


def _extract_python(content: str, fpath: Path, scope: str, result: dict, wiki: Wiki = None) -> dict:
    """Extract entities from Python file."""
    if wiki is None:
        return result

    """Extract entities from Python file."""
    import ast
    
    entities = []
    classes = []
    functions = []
    imports = []
    
    try:
        tree = ast.parse(content)
        
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                classes.append({
                    'name': node.name,
                    'docstring': ast.get_docstring(node) or '',
                })
            elif isinstance(node, ast.FunctionDef):
                functions.append({
                    'name': node.name,
                    'docstring': ast.get_docstring(node) or '',
                })
        
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ''
                names = [alias.name for alias in node.names]
                if module:
                    imports.append({'module': module, 'names': names[:5]})
    except Exception:
        pass
    
    # Create module entity if not exists
    module_id = f"module:{_safe_name(str(fpath.parent))}"
    if not wiki.graph.get_entity(module_id):
        summary_parts = [f"Python file with {len(classes)} classes, {len(functions)} functions"]
        if imports:
            external = [imp for imp in imports 
                        if not imp['module'].startswith(('os', 'sys', 're', 'json', 'pathlib', 
                                                         'typing', 'dataclasses', 'enum', 'collections',
                                                         'asyncio', 'logging', 'abc', 'functools'))]
            if external:
                summary_parts.append(f"imports from {len(external)} external modules")
        
        entity = Entity(
            id=module_id,
            name=fpath.parent.name,
            entity_type=EntityType.CONCEPT,
            scope=scope,
            summary='; '.join(summary_parts),
            metadata={
                'file_count': 1,
                'class_count': len(classes),
                'function_count': len(functions),
                'complexity': len(classes) + len(functions),
            },
        )
        wiki.graph.upsert_entity(entity)
        wiki.upsert_page(wiki.entity_to_page(entity))
        result['created'].append(module_id)
    
    # Create class entities
    for cls in classes:
        class_id = f"class:{_safe_name(str(fpath.parent))}:{_safe_name(cls['name'])}"
        if not wiki.graph.get_entity(class_id):
            entity = Entity(
                id=class_id,
                name=cls['name'],
                entity_type=EntityType.CONCEPT,
                scope=scope,
                summary=cls.get('docstring', '')[:200] or f"Class in {fpath.parent.name}",
                metadata={
                    'type': 'class',
                    'file': str(fpath),
                },
            )
            wiki.graph.upsert_entity(entity)
            result['created'].append(class_id)
    
    # Create function entities
    for func in functions:
        func_id = f"function:{_safe_name(str(fpath.parent))}:{_safe_name(func['name'])}"
        if not wiki.graph.get_entity(func_id):
            entity = Entity(
                id=func_id,
                name=func['name'],
                entity_type=EntityType.CONCEPT,
                scope=scope,
                summary=func.get('docstring', '')[:150] or f"Function in {fpath.parent.name}",
                metadata={
                    'type': 'function',
                    'file': str(fpath),
                },
            )
            wiki.graph.upsert_entity(entity)
            result['created'].append(func_id)
    
    return result


def _extract_typescript(content: str, fpath: Path, scope: str, result: dict) -> dict:
    """Extract entities from TypeScript file."""
    classes = re.findall(r'class\s+(\w+)', content)
    interfaces = re.findall(r'interface\s+(\w+)', content)
    functions = re.findall(r'(?:export\s+)?(?:async\s+)?function\s+(\w+)', content)
    
    # Create module entity
    module_id = f"module:{_safe_name(str(fpath.parent))}"
    if not wiki.graph.get_entity(module_id):
        summary_parts = [f"TypeScript file with {len(classes)} classes, {len(interfaces)} interfaces"]
        entity = Entity(
            id=module_id,
            name=fpath.parent.name,
            entity_type=EntityType.CONCEPT,
            scope=scope,
            summary='; '.join(summary_parts),
            metadata={'file_count': 1, 'class_count': len(classes), 'interface_count': len(interfaces)},
        )
        wiki.graph.upsert_entity(entity)
        wiki.upsert_page(wiki.entity_to_page(entity))
        result['created'].append(module_id)
    
    for cls in classes:
        class_id = f"class:{_safe_name(str(fpath.parent))}:{_safe_name(cls)}"
        if not wiki.graph.get_entity(class_id):
            entity = Entity(
                id=class_id,
                name=cls,
                entity_type=EntityType.CONCEPT,
                scope=scope,
                summary=f"TypeScript class in {fpath.parent.name}",
                metadata={'type': 'class', 'file': str(fpath)},
            )
            wiki.graph.upsert_entity(entity)
            result['created'].append(class_id)
    
    return result


def _extract_rust(content: str, fpath: Path, scope: str, result: dict) -> dict:
    """Extract entities from Rust file."""
    structs = re.findall(r'struct\s+(\w+)', content)
    impls = re.findall(r'impl\s+(?:<[^>]+>\s+)?(\w+)', content)
    functions = re.findall(r'(?:pub\s+)?(?:async\s+)?fn\s+(\w+)', content)
    
    module_id = f"module:{_safe_name(str(fpath.parent))}"
    if not wiki.graph.get_entity(module_id):
        summary_parts = [f"Rust file with {len(structs)} structs, {len(impls)} impl blocks"]
        entity = Entity(
            id=module_id,
            name=fpath.parent.name,
            entity_type=EntityType.CONCEPT,
            scope=scope,
            summary='; '.join(summary_parts),
            metadata={'file_count': 1, 'struct_count': len(structs), 'impl_count': len(impls)},
        )
        wiki.graph.upsert_entity(entity)
        wiki.upsert_page(wiki.entity_to_page(entity))
        result['created'].append(module_id)
    
    return result


def _extract_sql(content: str, fpath: Path, scope: str, result: dict) -> dict:
    """Extract entities from SQL file."""
    tables = re.findall(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:`?)(\w+)(?:`?)\s*\(', content)
    
    module_id = f"module:{_safe_name(str(fpath.parent))}"
    if not wiki.graph.get_entity(module_id):
        entity = Entity(
            id=module_id,
            name=fpath.parent.name,
            entity_type=EntityType.DATABASE,
            scope=scope,
            summary=f"SQL file with {len(tables)} tables",
            metadata={'file_count': 1, 'table_count': len(tables)},
        )
        wiki.graph.upsert_entity(entity)
        wiki.upsert_page(wiki.entity_to_page(entity))
        result['created'].append(module_id)
    
    return result


def auto_extract_directory(project_path: str | Path, wiki) -> dict:
    """Auto-extract all source files in a directory.
    
    Useful for bulk extraction after a project is cloned.
    """
    result = {'created': [], 'updated': [], 'skipped': [], 'errors': []}
    project = Path(project_path)
    
    for src_dir in ['core', 'src', 'lib', 'app']:
        src_path = project / src_dir
        if not src_path.exists():
            continue
        
        for root, dirs, files in os.walk(src_path):
            # Skip noise
            dirs[:] = [d for d in dirs if d not in {
                '.venv', 'node_modules', '__pycache__', '.pytest_cache',
                '.ruff_cache', '.git', '.mypy_cache',
            }]
            
            for f in files:
                if f.endswith(('.py', '.ts', '.tsx', '.js', '.jsx', '.rs', '.sql')):
                    fpath = Path(root) / f
                    try:
                        file_result = auto_extract_file(fpath, wiki)
                        result['created'].extend(file_result['created'])
                        result['updated'].extend(file_result['updated'])
                        result['skipped'].extend(file_result['skipped'])
                        result['errors'].extend(file_result['errors'])
                    except Exception as e:
                        result['errors'].append(str(fpath) + ": " + str(e))
    
    return result

