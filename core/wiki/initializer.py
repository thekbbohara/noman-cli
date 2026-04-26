"""Project knowledge graph initializer.

Scans a project directory, extracts entities and relations, and
populates the wiki for that project. Called once per project.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from core.wiki.graph import EdgeType, Entity, EntityType, Graph
from core.wiki.wiki import Wiki, WikiPage


# File patterns that indicate technology/framework
TECH_PATTERNS = {
    "pyproject.toml": ("framework", "Python project configuration"),
    "package.json": ("framework", "Node.js project configuration"),
    "setup.py": ("framework", "Python package setup"),
    "setup.cfg": ("framework", "Python package config"),
    "Cargo.toml": ("framework", "Rust project configuration"),
    "go.mod": ("framework", "Go module configuration"),
    "Gemfile": ("framework", "Ruby gem configuration"),
    "pom.xml": ("framework", "Maven/Java project configuration"),
    "build.gradle": ("framework", "Gradle build configuration"),
    "CMakeLists.txt": ("framework", "CMake build configuration"),
    "Makefile": ("framework", "Make build system"),
    "docker-compose.yml": ("framework", "Docker Compose"),
    "docker-compose.yaml": ("framework", "Docker Compose"),
    "Dockerfile": ("framework", "Docker container"),
    "webpack.config.js": ("framework", "Webpack bundler"),
    "vite.config.js": ("framework", "Vite bundler"),
    "tailwind.config.js": ("framework", "Tailwind CSS"),
    ".eslintrc": ("framework", "ESLint linter"),
    ".prettierrc": ("framework", "Prettier formatter"),
    "pytest.ini": ("framework", "pytest test framework"),
    "tox.ini": ("framework", "tox test runner"),
    "pyrightconfig.json": ("framework", "Pyright type checker"),
    "ruff.toml": ("framework", "Ruff linter"),
    "mypy.ini": ("framework", "mypy type checker"),
    ".gitignore": ("config", "Git ignore patterns"),
    ".gitmodules": ("config", "Git submodules"),
    "requirements.txt": ("framework", "Python requirements"),
    "requirements-dev.txt": ("framework", "Python dev requirements"),
    "Pipfile": ("framework", "Pipenv package manager"),
    "poetry.lock": ("framework", "Poetry package manager"),
    "uv.lock": ("framework", "uv package manager"),
    "tsconfig.json": ("framework", "TypeScript configuration"),
    "next.config.js": ("framework", "Next.js configuration"),
    "next.config.mjs": ("framework", "Next.js configuration"),
    ".env.example": ("config", "Environment template"),
    ".env": ("config", "Environment variables"),
    "config.toml": ("config", "TOML configuration"),
    "config.json": ("config", "JSON configuration"),
    "dockerfile": ("framework", "Dockerfile"),
    "Makefile": ("framework", "Makefile"),
    "README.md": ("config", "Project documentation"),
    "CHANGELOG.md": ("config", "Change log"),
    "CONTRIBUTING.md": ("config", "Contribution guide"),
    "LICENSE": ("config", "License file"),
    "LICENSE.md": ("config", "License file"),
    "SECURITY.md": ("config", "Security policy"),
    "SUPERPROJECT.md": ("config", "Superproject documentation"),
}

# Language indicators by file extension
LANGUAGE_EXTENSIONS = {
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".jsx": "JavaScript",
    ".rs": "Rust",
    ".go": "Go",
    ".rb": "Ruby",
    ".java": "Java",
    ".cpp": "C++",
    ".c": "C",
    ".h": "C/C++ header",
    ".sql": "SQL",
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".vue": "Vue",
    ".json": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".toml": "TOML",
    ".md": "Markdown",
    ".txt": "Text",
}


def _safe_name(text: str) -> str:
    """Sanitize a name for entity ID."""
    return re.sub(r"[^a-zA-Z0-9_\-]", "_", text.lower().strip())


def _extract_name_from_pyproject(path: Path) -> str | None:
    """Try to extract project name from pyproject.toml."""
    try:
        content = path.read_text()
        # Check for [project] name
        m = re.search(r'\[project\].*?name\s*=\s*"([^"]+)"', content, re.DOTALL)
        if m:
            return m.group(1)
        # Check for [tool.poetry] name
        m = re.search(r'\[tool\.poetry\].*?name\s*=\s*"([^"]+)"', content, re.DOTALL)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def _extract_name_from_package_json(path: Path) -> str | None:
    """Try to extract project name from package.json."""
    try:
        data = json.loads(path.read_text())
        return data.get("name")
    except Exception:
        pass
    return None


def _scan_dependencies(content: str) -> list[str]:
    """Extract dependency names from various config files."""
    deps = []
    # Python requirements.txt
    for line in content.split("\n"):
        line = line.strip()
        if line and not line.startswith("#") and not line.startswith("-"):
            # Extract package name before version specifiers
            m = re.match(r'^([a-zA-Z0-9_\-]+)', line)
            if m:
                deps.append(m.group(1))
    # package.json
    try:
        data = json.loads(content)
        for section in ("dependencies", "devDependencies", "peerDependencies"):
            if section in data:
                deps.extend(data[section].keys())
    except Exception:
        pass
    # go.mod
    for m in re.finditer(r'^\s+(\S+)\s+', content, re.MULTILINE):
        deps.append(m.group(1).split("/")[0])
    return deps


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

        # Scan project
        entities: list[Entity] = []
        edges: list[tuple[str, str, EdgeType, str]] = []
        seen_ids: set[str] = set()

        # 1. Discover project name
        project_name = self._project_path.name
        pyproject = self._project_path / "pyproject.toml"
        if pyproject.exists():
            name = _extract_name_from_pyproject(pyproject)
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

        # 3. Scan directory structure
        file_count = 0
        dir_count = 0
        lang_counts: dict[str, int] = {}
        tech_types: dict[str, str] = {}  # tech_name -> type

        for item in self._project_path.rglob("*"):
            if item.is_file():
                file_count += 1
                # Track language distribution
                ext = item.suffix.lower()
                if ext in LANGUAGE_EXTENSIONS:
                    lang = LANGUAGE_EXTENSIONS[ext]
                    lang_counts[lang] = lang_counts.get(lang, 0) + 1

                # Check for tech/framework files
                fname = item.name.lower()
                if fname in TECH_PATTERNS:
                    tech_type, tech_desc = TECH_PATTERNS[fname]
                    tech_id = f"tech:{_safe_name(fname)}"
                    if tech_id not in seen_ids:
                        entities.append(Entity(
                            id=tech_id,
                            name=tech_desc,
                            entity_type=EntityType.FRAMEWORK if tech_type == "framework" else EntityType.CONFIG,
                            scope=str(self._project_path),
                            summary=f"Found in project: {item.relative_to(self._project_path)}",
                        ))
                        seen_ids.add(tech_id)
                        edges.append((project_id, tech_id, EdgeType.USES, f"Uses {tech_desc}"))

            elif item.is_dir():
                dir_count += 1
                # Add directory as concept if it's a meaningful source dir
                if item.name in ("src", "core", "lib", "cli", "tools", "tests", "app", "components", "services", "models", "adapters"):
                    concept_id = f"module:{_safe_name(str(item.relative_to(self._project_path)))}"
                    if concept_id not in seen_ids:
                        entities.append(Entity(
                            id=concept_id,
                            name=item.name,
                            entity_type=EntityType.CONCEPT,
                            scope=str(self._project_path),
                            summary=f"Directory: {item.relative_to(self._project_path)}",
                        ))
                        seen_ids.add(concept_id)
                        edges.append((project_id, concept_id, EdgeType.PART_OF, f"Part of {project_name}"))

        # 4. Scan key config files for dependencies
        config_files = [
            ("pyproject.toml", "Python config"),
            ("package.json", "Node.js deps"),
            ("requirements.txt", "Python requirements"),
            ("requirements-dev.txt", "Python dev requirements"),
            ("go.mod", "Go dependencies"),
            ("Cargo.toml", "Rust dependencies"),
            ("Gemfile", "Ruby gems"),
        ]
        for fname, desc in config_files:
            fpath = self._project_path / fname
            if fpath.exists():
                try:
                    content = fpath.read_text()
                    deps = _scan_dependencies(content)
                    # Create dependency entities for top deps only
                    for dep in deps[:20]:  # Limit to avoid explosion
                        dep_id = f"tool:{_safe_name(dep)}"
                        if dep_id not in seen_ids:
                            entities.append(Entity(
                                id=dep_id,
                                name=dep,
                                entity_type=EntityType.TOOL,
                                scope=str(self._project_path),
                                summary=f"Dependency from {fname}",
                            ))
                            seen_ids.add(dep_id)
                            edges.append((project_id, dep_id, EdgeType.USES, f"Depends on {dep}"))
                except Exception:
                    pass

        # 5. Add language entities
        for lang, count in sorted(lang_counts.items(), key=lambda x: x[1], reverse=True):
            lang_id = f"lang:{_safe_name(lang)}"
            if lang_id not in seen_ids:
                entities.append(Entity(
                    id=lang_id,
                    name=lang,
                    entity_type=EntityType.CONCEPT,
                    scope=str(self._project_path),
                    summary=f"Language used in {count} files",
                ))
                seen_ids.add(lang_id)
                edges.append((project_id, lang_id, EdgeType.USES, f"Uses {lang}"))

        # 6. Create source page
        source_entity = Entity(
            id=f"source:init:{_safe_name(str(self._project_path))}",
            name=f"Project init: {project_name}",
            entity_type=EntityType.PATTERN,
            scope=str(self._project_path),
            summary=f"Auto-generated knowledge graph for {project_name}",
        )
        entities.append(source_entity)

        for entity in entities:
            if entity.id != source_entity.id:
                edges.append((
                    source_entity.id, entity.id,
                    EdgeType.ORIGINATED_FROM,
                    f"Created by wiki init of {project_name}",
                ))

        # 7. Feed into wiki
        page_ids = self._wiki.ingest_source(
            source_id=f"init:{_safe_name(str(self._project_path))}",
            source_type="project_init",
            content=f"Project: {project_name}\nPath: {self._project_path}\nFiles: {file_count}\nDirectories: {dir_count}\nLanguages: {', '.join(f'{k}({v})' for k, v in sorted(lang_counts.items(), key=lambda x: x[1], reverse=True))}",
            entities=entities,
            relations=edges,
        )

        self._created_entities = entities
        self._created_edges = edges

        summary = (
            f"Wiki initialized for '{project_name}' at {self._project_path}\n"
            f"  Entities: {len(entities)}\n"
            f"  Edges: {len(edges)}\n"
            f"  Files scanned: {file_count}\n"
            f"  Languages: {', '.join(f'{k}({v})' for k, v in sorted(lang_counts.items(), key=lambda x: x[1], reverse=True))}\n"
            f"  Pages created: {len(page_ids)}"
        )
        return summary
