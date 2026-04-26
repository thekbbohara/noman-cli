"""
Semantic matching for skill loading.

Uses sentence-transformers for lightweight embedding-based matching.
Falls back gracefully if no embedding provider is available.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .skill_index import SkillBM25Index, SkillEntry

# ---------------------------------------------------------------------------
# Embedding provider abstraction
# ---------------------------------------------------------------------------


@dataclass
class SemanticMatchResult:
    """Result from semantic matching."""
    skill_id: str
    score: float  # 0.0 - 1.0 (cosine similarity)
    reason: str = ""


class EmbeddingProvider:
    """
    Lightweight embedding provider abstraction.
    
    Supports:
    - sentence-transformers (local)
    - OpenAI embeddings API
    - Google Gemini embeddings
    
    Falls back to zero-score if none available.
    """

    def __init__(self):
        self._available = False
        self._model = None
        self._provider_type = None
        self._embeddings: dict[str, list[float]] = {}
        self._init()

    def _init(self):
        """Try to initialize an embedding provider."""
        # Try sentence-transformers first (local, no API key needed)
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer('all-MiniLM-L6-v2')
            self._provider_type = 'sentence-transformers'
            self._available = True
            return
        except ImportError:
            pass

        # Try OpenAI
        try:
            import os
            if os.environ.get('OPENAI_API_KEY'):
                self._provider_type = 'openai'
                self._available = False  # Needs async init, defer
                return
        except Exception:
            pass

        # Try Google
        try:
            import os
            if os.environ.get('GOOGLE_API_KEY'):
                self._provider_type = 'google'
                self._available = False  # Deferred
                return
        except Exception:
            pass

    def embed(self, text: str) -> list[float]:
        """Embed a single text string."""
        if not self._available:
            return [0.0] * 384  # all-MiniLM-L6-v2 dim

        if self._provider_type == 'sentence-transformers':
            import numpy as np
            vec = self._model.encode(text, normalize_embeddings=True)
            return vec.tolist()

        # Deferred providers handled by _embed_lazy
        return [0.0] * 384

    def _embed_lazy(self, text: str) -> list[float]:
        """Defer initialization for providers that need async."""
        if self._provider_type == 'openai':
            return self._embed_openai(text)
        elif self._provider_type == 'google':
            return self._embed_google(text)
        return [0.0] * 384

    def _embed_openai(self, text: str) -> list[float]:
        """Embed via OpenAI API."""
        try:
            from openai import OpenAI
            client = OpenAI()
            response = client.embeddings.create(
                model="text-embedding-3-small",
                input=text,
            )
            vec = response.data[0].embedding
            # L2-normalize
            norm = math.sqrt(sum(v * v for v in vec))
            if norm > 0:
                return [v / norm for v in vec]
            return vec
        except Exception:
            return [0.0] * 1536

    def _embed_google(self, text: str) -> list[float]:
        """Embed via Google embeddings API."""
        try:
            import google.generativeai as genai
            # Use text-embedding-004
            response = genai.embed_content(
                model="models/text-embedding-004",
                content=text,
                task_type="retrieval_query"
            )
            vec = response['embedding']
            norm = math.sqrt(sum(v * v for v in vec))
            if norm > 0:
                return [v / norm for v in vec]
            return vec
        except Exception:
            return [0.0] * 768

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts at once (more efficient for local models)."""
        if not self._available:
            return [[0.0] * 384 for _ in texts]

        if self._provider_type == 'sentence-transformers':
            import numpy as np
            vectors = self._model.encode(texts, normalize_embeddings=True)
            return [v.tolist() for v in vectors]

        return [self.embed(t) for t in texts]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if not a or not b:
        return 0.0
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class SkillSemanticMatcher:
    """
    Embeds task context and matches against skill embeddings.
    
    Provides semantic relevance scoring on top of BM25 lexical matching.
    Falls back to zero scores if no embedding provider available.
    """

    def __init__(self, index: SkillBM25Index):
        self.index = index
        self.provider = EmbeddingProvider()
        self._skill_embeddings: dict[str, list[float]] = {}
        self._cache_enabled = True

    def _build_cache(self):
        """Build embedding cache for all skills."""
        if self._cache_enabled and not self._skill_embeddings:
            texts = []
            for skill_id in self.index.get_all_ids():
                entry = self.index.get_skill(skill_id)
                if entry:
                    texts.append(entry.to_text())

            if self.provider._available:
                embeddings = self.provider.embed_batch(texts)
                for skill_id, emb in zip(self.index.get_all_ids(), embeddings):
                    self._skill_embeddings[skill_id] = emb
            else:
                # No embedding provider — use BM25 only
                self._cache_enabled = False

    def score_skills(self, query: str, top_n: int = 10) -> list[SemanticMatchResult]:
        """
        Score all skills against a query using embeddings.
        Returns ranked list of SemanticMatchResult.
        """
        self._build_cache()

        if not self._cache_enabled:
            # No embeddings — return empty (BM25 handles this)
            return []

        query_emb = self.provider.embed(query)
        if not query_emb or all(v == 0 for v in query_emb):
            return []

        results = []
        for skill_id in self.index.get_all_ids():
            skill_emb = self._skill_embeddings.get(skill_id)
            if not skill_emb:
                continue

            score = _cosine_similarity(query_emb, skill_emb)
            if score > 0:
                name = self.index.get_skill_name(skill_id) or skill_id
                desc = self.index.get_skill_description(skill_id) or ""
                results.append(SemanticMatchResult(
                    skill_id=skill_id,
                    score=round(score, 4),
                    reason=f"semantic match: {name}"
                ))

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_n]

    def get_provider_status(self) -> dict[str, str]:
        """Return embedding provider status for diagnostics."""
        if not self.provider._available:
            return {
                "provider": self.provider._provider_type or "none",
                "available": str(self.provider._available),
                "note": "Local embedding not available — use BM25 only"
            }
        return {
            "provider": self.provider._provider_type or "unknown",
            "available": str(self.provider._available),
            "note": "Embedding provider ready"
        }
