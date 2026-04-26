"""Semantic search for the wiki using text embeddings.

Provides embedding-based search for wiki pages, enabling
conceptual matching ("memory system" finds "MemoryStore")
without exact string matching.

Uses sentence-transformers if available, falls back to
TF-IDF with sklearn, and finally to a simple n-gram
overlap fallback with zero dependencies.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections import Counter
from pathlib import Path
from typing import Any

from core.wiki.wiki import Wiki


class EmbeddingProvider:
    """Multi-tier embedding provider with graceful fallback."""

    def __init__(self, storage_path: Path) -> None:
        self._storage = storage_path
        self._storage.mkdir(parents=True, exist_ok=True)
        self._embeddings: dict[str, list[float]] = {}
        self._load()

    def _load(self) -> None:
        """Load cached embeddings from disk."""
        cache_file = self._storage / "embeddings.json"
        if cache_file.exists():
            try:
                self._embeddings = {
                    k: v for k, v in json.loads(cache_file.read_text()).items()
                    if isinstance(v, list) and all(isinstance(x, float) for x in v)
                }
            except (json.JSONDecodeError, TypeError):
                self._embeddings = {}

    def _save(self) -> None:
        """Save embeddings to disk."""
        cache_file = self._storage / "embeddings.json"
        cache_file.write_text(json.dumps(self._embeddings, indent=2))

    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def _normalize(self, vec: list[float]) -> list[float]:
        """Normalize a vector to unit length."""
        norm = math.sqrt(sum(x * x for x in vec))
        if norm == 0:
            return vec
        return [x / norm for x in vec]

    def embed(self, text: str) -> list[float]:
        """Get embedding for text, using available provider."""
        text_lower = text.lower().strip()
        # Check cache first
        cache_key = hashlib.md5(text_lower.encode()).hexdigest()
        if cache_key in self._embeddings:
            return self._embeddings[cache_key]

        # Try sentence-transformers (highest quality)
        if 'USE_SENTENCE_TRANSFORMERS' in os.environ:
            try:
                from sentence_transformers import SentenceTransformer
                model_name = os.environ.get('SENTENCE_TRANSFORMER_MODEL', 'all-MiniLM-L6-v2')
                model = SentenceTransformer(model_name)
                embedding = model.encode(text).tolist()
                self._embeddings[cache_key] = embedding
                self._save()
                return embedding
            except ImportError:
                pass

        # Try OpenAI embeddings
        if 'OPENAI_API_KEY' in os.environ:
            try:
                import openai
                client = openai.OpenAI()
                response = client.embeddings.create(
                    model=os.environ.get('OPENAI_EMBED_MODEL', 'text-embedding-3-small'),
                    input=text
                )
                embedding = response.data[0].embedding
                self._embeddings[cache_key] = embedding
                self._save()
                return embedding
            except ImportError:
                pass

        # Try Google embeddings
        if 'GOOGLE_API_KEY' in os.environ:
            try:
                from google import genai
                model_name = os.environ.get('GOOGLE_EMBED_MODEL', 'text-embedding-004')
                client = genai.Client(api_key=os.environ['GOOGLE_API_KEY'])
                response = client.models.embed_content(
                    model=f"models/{model_name}",
                    content=text
                )
                embedding = response.embeddings[0].values
                self._embeddings[cache_key] = embedding
                self._save()
                return embedding
            except ImportError:
                pass

        # Fallback: TF-IDF with sklearn
        if 'USE_TFIDF' in os.environ or True:  # Always try TF-IDF fallback
            try:
                from sklearn.feature_extraction.text import TfidfVectorizer
                vectorizer = TfidfVectorizer()
                embedding = vectorizer.fit_transform([text]).toarray()[0].tolist()
                self._embeddings[cache_key] = embedding
                self._save()
                return embedding
            except ImportError:
                pass

        # Final fallback: simple n-gram hashing
        return self._ngram_embedding(text)

    def _ngram_embedding(self, text: str, n: int = 3, dim: int = 64) -> list[float]:
        """Simple n-gram based embedding as zero-dependency fallback."""
        text = text.lower().strip()
        # Generate n-grams
        ngrams = Counter()
        for i in range(len(text) - n + 1):
            ngrams[text[i:i+n]] += 1

        # Hash n-grams to fixed dimensions
        embedding = [0.0] * dim
        for ngram, count in ngrams.items():
            idx = hash(ngram) % dim
            embedding[idx] += count

        # Normalize
        norm = math.sqrt(sum(x * x for x in embedding)) or 1.0
        return [x / norm for x in embedding]


def semantic_search(wiki: Wiki, query: str, limit: int = 10) -> list[dict]:
    """Search wiki pages using semantic similarity.

    Args:
        wiki: The wiki instance.
        query: The search query.
        limit: Maximum results to return.

    Returns:
        List of dicts with 'page', 'score', 'reason' keys.
    """
    from core.wiki.wiki import WikiPage

    pages = wiki._pages.values()
    if not pages:
        return []

    # Get query embedding
    storage_path = wiki._base / "embeddings"
    provider = EmbeddingProvider(storage_path)
    query_emb = provider.embed(query)

    # Search each page
    results = []
    for page in pages:
        # Build searchable text from page content + title + tags
        search_text = f"{page.title} {page.page_type} {' '.join(page.tags)} {page.content}"
        if not search_text.strip():
            continue

        # Get page embedding (or compute on-the-fly)
        cache_key = hashlib.md5(page.id.encode()).hexdigest()
        page_emb = provider._embeddings.get(cache_key)
        if page_emb is None:
            page_emb = provider.embed(search_text)
            # Store in provider cache for this session
            provider._embeddings[cache_key] = page_emb

        # Compute similarity
        score = provider._cosine_similarity(query_emb, page_emb)

        # Boost for exact title/tag matches
        query_lower = query.lower()
        if query_lower in page.title.lower():
            score += 0.3
        for tag in page.tags:
            if query_lower in tag.lower():
                score += 0.2

        results.append({
            'page': page,
            'score': round(score, 4),
        })

    # Sort by score descending
    results.sort(key=lambda x: x['score'], reverse=True)
    return results[:limit]
