"""Context management with skeleton maps, PageRank, and JIT loading."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class SymbolSkeleton:
    """Compressed symbol representation."""

    name: str
    kind: str  # function, class, method, constant
    file_path: str
    signature: str
    line_number: int
    docstring_first_line: str | None = None


@dataclass
class SkeletonFile:
    """Skeleton map for a single file."""

    file_path: str
    symbols: list[SymbolSkeleton] = field(default_factory=list)
    mtime: float = 0.0
    token_count: int = 0


class SkeletonCache:
    """Cache for skeleton maps."""

    def __init__(self) -> None:
        self._cache: dict[str, SkeletonFile] = {}

    def get(self, file_path: str) -> SkeletonFile | None:
        return self._cache.get(file_path)

    def set(self, file_path: str, skeleton: SkeletonFile) -> None:
        self._cache[file_path] = skeleton

    def invalidate(self, file_path: str) -> None:
        self._cache.pop(file_path, None)

    def clear(self) -> None:
        self._cache.clear()


@dataclass
class SymbolIndex:
    """Symbol index with PageRank scores."""

    symbols: list[SymbolSkeleton] = field(default_factory=list)
    centrality: dict[str, float] = field(default_factory=dict)

    def top_n(self, n: int) -> list[SymbolSkeleton]:
        if n >= len(self.symbols):
            return self.symbols
        return self.symbols[:n]

    def by_file(self, file_path: str) -> list[SymbolSkeleton]:
        return [s for s in self.symbols if s.file_path == file_path]


@dataclass
class ContextView:
    """Assembled context for a single turn."""

    skeleton: list[SymbolSkeleton] = field(default_factory=list)
    full_files: dict[str, str] = field(default_factory=dict)
    token_count: int = 0
    budget: int = 0

    def truncated_to(self, budget: int) -> ContextView:
        if self.token_count <= budget:
            return self
        # Truncate skeleton to fit budget (~5 tokens per symbol)
        max_symbols = budget // 5
        return ContextView(
            skeleton=self.skeleton[:max_symbols],
            full_files={},
            token_count=len(self.skeleton[:max_symbols]) * 5,
            budget=budget,
        )


class ContextManager:
    """Manages context with skeleton maps, PageRank, and JIT loading."""

    def __init__(self, root_dir: str | Path) -> None:
        self.root = Path(root_dir).resolve()
        self.skeleton_cache = SkeletonCache()
        self.symbol_index = SymbolIndex()
        self.jit_cache: dict[str, str] = {}

    def index_repo(self, extensions: list[str] | None = None) -> None:
        """Walk repo and build skeleton index."""
        extensions = extensions or [".py", ".ts", ".js", ".go", ".rs"]
        symbols: list[SymbolSkeleton] = []

        for ext in extensions:
            for path in self.root.rglob(f"*{ext}"):
                if self._should_skip(path):
                    continue
                file_skeletons = self._extract_skeletons(path)
                symbols.extend(file_skeletons)

        self.symbol_index.symbols = symbols
        self._compute_centrality()
        logger.info(f"Indexed {len(symbols)} symbols from {self.root}")

    def _should_skip(self, path: Path) -> bool:
        skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "overlay", "user"}
        return any(part in skip_dirs for part in path.parts)

    def _extract_skeletons(self, path: Path) -> list[SymbolSkeleton]:
        """Extract skeleton from a single file."""
        skeletons: list[SymbolSkeleton] = []
        try:
            content = path.read_text(errors="ignore")
            lines = content.split("\n")
        except Exception:
            return skeletons

        current_class: str | None = None
        in_docstring = False

        for i, line in enumerate(lines, 1):
            stripped = line.strip()

            # Class definition
            if stripped.startswith("class ") and ":" in stripped:
                name = stripped.split("class ")[1].split("(")[0].split(":")[0]
                skeletons.append(SymbolSkeleton(
                    name=name,
                    kind="class",
                    file_path=str(path.relative_to(self.root)),
                    signature=stripped[:80],
                    line_number=i,
                ))
                current_class = name
                continue

            # Function/method
            if stripped.startswith("def ") and ":" in stripped:
                name = stripped.split("def ")[1].split("(")[0]
                kind = "method" if current_class else "function"
                skeletons.append(SymbolSkeleton(
                    name=name,
                    kind=kind,
                    file_path=str(path.relative_to(self.root)),
                    signature=stripped[:80],
                    line_number=i,
                ))
                continue

            # Constant
            if "=" in stripped and not stripped.startswith("#"):
                parts = stripped.split("=")
                if len(parts) == 2 and parts[0].strip().isidentifier():
                    name = parts[0].strip()
                    if name.isupper():
                        skeletons.append(SymbolSkeleton(
                            name=name,
                            kind="constant",
                            file_path=str(path.relative_to(self.root)),
                            signature=stripped[:80],
                            line_number=i,
                        ))

        return skeletons

    def _compute_centrality(self) -> None:
        """Compute simple centrality scores based on import relationships."""
        # Simplified: more imports = more central
        centrality: dict[str, float] = {}

        for sym in self.symbol_index.symbols:
            key = f"{sym.file_path}:{sym.name}"
            centrality[key] = 1.0

        # Simple ranking by kind priority
        kind_priority = {"class": 3.0, "function": 2.0, "method": 2.0, "constant": 1.0}
        for sym in self.symbol_index.symbols:
            key = f"{sym.file_path}:{sym.name}"
            centrality[key] = centrality.get(key, 1.0) * kind_priority.get(sym.kind, 1.0)

        self.symbol_index.centrality = centrality

    def get_context(self, budget: int) -> ContextView:
        """Get context assembled for token budget."""
        symbols = self.symbol_index.top_n(budget // 5)

        return ContextView(
            skeleton=symbols,
            token_count=len(symbols) * 5,
            budget=budget,
        )

    def read_lines(
        self, file_path: str, start: int = 1, end: int | None = None
    ) -> str:
        """JIT load specific lines from a file."""
        key = f"{file_path}:{start}:{end}"

        if key in self.jit_cache:
            return self.jit_cache[key]

        full_path = self.root / file_path
        try:
            lines = full_path.read_text(errors="ignore").split("\n")
        except Exception:
            return ""

        end = end or len(lines)
        result = "\n".join(lines[start-1:end])

        self.jit_cache[key] = result
        return result

    def read_symbol(self, name: str, file_path: str) -> str | None:
        """JIT load full content around a symbol."""
        skeleton = self.symbol_index.by_file(file_path)
        sym = next((s for s in skeleton if s.name == name), None)

        if not sym:
            return None

        # Read 20 lines around symbol
        start = max(1, sym.line_number - 10)
        end = sym.line_number + 10
        return self.read_lines(file_path, start, end)

    def invalidate(self, file_path: str) -> None:
        """Mark a file as changed (needs re-indexing)."""
        self.skeleton_cache.invalidate(file_path)
        # Clear JIT cache for this file
        keys_to_remove = [k for k in self.jit_cache if k.startswith(file_path)]
        for key in keys_to_remove:
            self.jit_cache.pop(key, None)
