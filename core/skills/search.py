"""SkillSearch: BM25 + semantic skill search.

Provides dual-index search over skill metadata:
- BM25 keyword search over name, description, tags, keywords
- Semantic embedding search (optional, requires embedding provider)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SkillSearchResult:
    """A single search result.

    Attributes:
        skill_name: Skill name.
        score: Relevance score.
        rank: Rank among results (1-indexed).
        matched_fields: Which fields matched.
        snippet: Highlighted text snippet.
    """

    skill_name: str
    score: float
    rank: int = 0
    matched_fields: list[str] = field(default_factory=list)
    snippet: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "skill_name": self.skill_name,
            "score": self.score,
            "rank": self.rank,
            "matched_fields": self.matched_fields,
            "snippet": self.snippet,
        }


class SkillSearch:
    """BM25 + semantic skill search engine.

    Searches skills across:
    - Name (exact match, substring, word overlap)
    - Description (text search)
    - Tags (categorical match)
    - Keywords (synonym-aware search)

    Example:
        search = SkillSearch()
        search.add_skill("code-review", "reviews code", ["code", "review"])
        results = search.search("code review", limit=10)
    """

    # BM25 hyperparameters
    K1: float = 1.5  # Term frequency saturation
    B: float = 0.75  # Length normalization

    def __init__(self) -> None:
        self._index: dict[str, dict[str, Any]] = {}  # name -> {doc, tokens}
        self._vocab: dict[str, dict[str, int]] = {}   # term -> {doc_id: count}
        self._doc_freq: dict[str, int] = {}           # term -> doc count
        self._total_docs = 0
        self._avg_doc_length = 0.0
        self._semantic_index: list[tuple[str, list[float]]] = []  # (name, embedding)
        self._semantic_enabled = False

    @property
    def is_semantic_enabled(self) -> bool:
        """Check if semantic search is enabled."""
        return self._semantic_enabled

    def enable_semantic(self) -> None:
        """Enable semantic search mode."""
        self._semantic_enabled = True

    def disable_semantic(self) -> None:
        """Disable semantic search mode."""
        self._semantic_enabled = False

    # -- Indexing --

    def add_skill(
        self,
        name: str,
        description: str = "",
        tags: list[str] = None,
        keywords: list[str] = None,
        source: str = "",
    ) -> None:
        """Add a skill to the search index.

        Args:
            name: Skill name.
            description: Skill description.
            tags: Skill tags.
            keywords: Skill keywords.
            source: Skill source URL.
        """
        if tags is None:
            tags = []
        if keywords is None:
            keywords = []

        # Tokenize
        text = f"{name} {description} {' '.join(tags)} {' '.join(keywords)}"
        tokens = self._tokenize(text)

        doc = {
            "name": name,
            "description": description,
            "tags": tags,
            "keywords": keywords,
            "source": source,
            "tokens": tokens,
        }

        self._index[name] = doc

        # Update vocabulary
        for token in set(tokens):
            if token not in self._vocab:
                self._vocab[token] = {}
            self._vocab[token][name] = self._vocab[token].get(name, 0) + 1
            self._doc_freq[token] = self._doc_freq.get(token, 0) + 1

        self._total_docs = len(self._index)
        self._avg_doc_length = sum(len(doc["tokens"]) for doc in self._index.values()) / max(self._total_docs, 1)

    def remove_skill(self, name: str) -> None:
        """Remove a skill from the search index.

        Args:
            name: Skill name to remove.
        """
        if name in self._index:
            del self._index[name]
            self._total_docs = len(self._index)
            self._avg_doc_length = sum(len(doc["tokens"]) for doc in self._index.values()) / max(self._total_docs, 1)

    def clear(self) -> None:
        """Clear the entire search index."""
        self._index.clear()
        self._vocab.clear()
        self._doc_freq.clear()
        self._total_docs = 0
        self._avg_doc_length = 0.0

    def _tokenize(self, text: str) -> list[str]:
        """Tokenize text into lowercase terms."""
        import re
        return re.findall(r'[a-z_][a-z0-9_]*', text.lower())

    # -- Search --

    def search(
        self,
        query: str,
        limit: int = 20,
        semantic_weight: float = 0.3,
    ) -> list[SkillSearchResult]:
        """Search for skills matching a query.

        Combines BM25 scoring with optional semantic search.

        Args:
            query: Search query string.
            limit: Maximum results.
            semantic_weight: Weight for semantic scores (0.0-1.0).

        Returns:
            List of SkillSearchResult sorted by relevance.
        """
        bm25_results = self._bm25_search(query)

        if self._semantic_enabled:
            semantic_results = self._semantic_search(query)
            # Normalize and combine scores
            combined = self._combine_scores(bm25_results, semantic_results, semantic_weight)
        else:
            # Normalize BM25 scores
            scores = [r.score for r in bm25_results]
            max_score = max(scores) if scores else 1.0
            for r in bm25_results:
                r.score = r.score / max(max_score, 1.0)

            combined = bm25_results

        # Rank and limit
        combined.sort(key=lambda r: r.score, reverse=True)
        for i, r in enumerate(combined):
            r.rank = i + 1

        return combined[:limit]

    def _bm25_search(self, query: str) -> list[SkillSearchResult]:
        """Run BM25 search over the index.

        Args:
            query: Search query.

        Returns:
            List of scored results.
        """
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        scores: dict[str, float] = {}

        for doc_name, doc in self._index.items():
            score = 0.0
            doc_len = len(doc["tokens"])

            for token in query_tokens:
                # Term frequency in document
                tf = doc["tokens"].count(token)
                if tf == 0:
                    continue

                # Document frequency
                df = self._doc_freq.get(token, 0)
                if df == 0:
                    continue

                # BM25 formula
                idf = math.log(
                    (self._total_docs - df + 0.5) / (df + 0.5) + 1.0
                )
                dl_norm = doc_len / max(self._avg_doc_length, 1.0)
                tf_norm = tf * (self.K1 + 1) / (tf + self.K1 * (1 - self.B + self.B * dl_norm))
                score += idf * tf_norm

            if score > 0:
                # Field bonuses
                if query in doc["name"].lower():
                    score *= 2.0  # Exact name match bonus
                for tag in doc["tags"]:
                    if query in tag.lower():
                        score *= 1.5  # Tag match bonus

                scores[doc_name] = score

        results = [
            SkillSearchResult(
                skill_name=name,
                score=score,
                matched_fields=self._find_matches(query, doc),
            )
            for name, score in scores.items()
        ]
        results.sort(key=lambda r: r.score, reverse=True)
        return results

    def _find_matches(self, query: str, doc: dict[str, Any]) -> list[str]:
        """Find which fields matched the query.

        Args:
            query: Search query.
            doc: Document dict.

        Returns:
            List of matched field names.
        """
        matches: list[str] = []
        query_lower = query.lower()
        if query_lower in doc["name"].lower():
            matches.append("name")
        if query_lower in doc["description"].lower():
            matches.append("description")
        if any(query_lower in tag.lower() for tag in doc["tags"]):
            matches.append("tags")
        if any(query_lower in kw.lower() for kw in doc["keywords"]):
            matches.append("keywords")
        return matches

    def _semantic_search(self, query: str) -> list[tuple[str, float]]:
        """Run semantic search over the index.

        Uses simple cosine similarity on term frequency vectors.
        For real semantic search, integrate with an embedding provider.

        Args:
            query: Search query.

        Returns:
            List of (skill_name, similarity_score) tuples.
        """
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        # Build query vector
        query_vec: dict[str, float] = {}
        for token in query_tokens:
            query_vec[token] = query_vec.get(token, 0) + 1

        # Compute similarity with each indexed skill
        results: list[tuple[str, float]] = []
        for name, tokens in [(n, d["tokens"]) for n, d in self._index.items()]:
            doc_vec: dict[str, float] = {}
            for token in tokens:
                doc_vec[token] = doc_vec.get(token, 0) + 1

            # Cosine similarity
            dot_product = sum(query_vec.get(t, 0) * doc_vec.get(t, 0) for t in set(query_vec) & set(doc_vec))
            norm_q = math.sqrt(sum(v ** 2 for v in query_vec.values()))
            norm_d = math.sqrt(sum(v ** 2 for v in doc_vec.values()))

            if norm_q > 0 and norm_d > 0:
                similarity = dot_product / (norm_q * norm_d)
                results.append((name, similarity))

        return results

    def _combine_scores(
        self,
        bm25_results: list[SkillSearchResult],
        semantic_results: list[tuple[str, float]],
        semantic_weight: float,
    ) -> list[SkillSearchResult]:
        """Combine BM25 and semantic scores.

        Args:
            bm25_results: BM25 search results.
            semantic_results: Semantic search results.
            semantic_weight: Weight for semantic component.

        Returns:
            Combined results.
        """
        semantic_map: dict[str, float] = dict(semantic_results)

        # Normalize BM25 scores
        bm25_scores = [r.score for r in bm25_results]
        max_bm25 = max(bm25_scores) if bm25_scores else 1.0

        combined: dict[str, float] = {}
        for r in bm25_results:
            bm25_norm = r.score / max(max_bm25, 1.0)
            semantic_score = semantic_map.get(r.skill_name, 0.0)
            combined[r.skill_name] = (1 - semantic_weight) * bm25_norm + semantic_weight * semantic_score

        # Add semantic-only results
        for name, score in semantic_results:
            if name not in combined:
                combined[name] = semantic_weight * score

        return [
            SkillSearchResult(
                skill_name=name,
                score=score,
                matched_fields=["bm25"] if name in {r.skill_name for r in bm25_results} else ["semantic"],
            )
            for name, score in combined.items()
        ]

    # -- Serialization --

    def to_dict(self) -> dict[str, Any]:
        """Serialize the search index."""
        return {
            "vocab": {k: dict(v) for k, v in self._vocab.items()},
            "doc_freq": dict(self._doc_freq),
            "total_docs": self._total_docs,
            "avg_doc_length": self._avg_doc_length,
            "semantic_enabled": self._semantic_enabled,
            "skills": {name: doc for name, doc in self._index.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillSearch:
        """Create a search index from serialized data."""
        search = cls()
        search._vocab = {k: v for k, v in data.get("vocab", {}).items()}
        search._doc_freq = dict(data.get("doc_freq", {}))
        search._total_docs = data.get("total_docs", 0)
        search._avg_doc_length = data.get("avg_doc_length", 0.0)
        search._semantic_enabled = data.get("semantic_enabled", False)
        search._index = {name: doc for name, doc in data.get("skills", {}).items()}
        return search
