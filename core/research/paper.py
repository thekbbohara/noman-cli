"""Academic paper utilities for analysis and comparison.

Provides utilities for working with academic papers:
    - Paper metadata extraction
    - Citation analysis
    - Paper similarity comparison
    - Reference tracking
    - Paper summarization

Configuration (in ~/.noman/config.toml):
    [research.paper]
    max_context = 8000
    embedding_model = ""
"""

from __future__ import annotations

import logging
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PaperSummary:
    """Summary of an academic paper."""
    title: str
    authors: list[str]
    abstract: str
    year: int = 0
    venue: str = ""
    citations: int = 0
    references: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    pdf_path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return (
            f"{self.title}\n"
            f"  Authors: {', '.join(self.authors[:5])}\n"
            f"  Year: {self.year} | Venue: {self.venue}\n"
            f"  Citations: {self.citations}\n"
            f"  Abstract: {self.abstract[:200]}..."
        )


@dataclass
class PaperComparison:
    """Comparison between two papers."""
    paper_a: str
    paper_b: str
    similarity: float = 0.0
    shared_references: list[str] = field(default_factory=list)
    shared_authors: list[str] = field(default_factory=list)
    citation_overlap: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return (
            f"Paper Comparison:\n"
            f"  A: {self.paper_a}\n"
            b"  B: {self.paper_b}\n"
            f"  Similarity: {self.similarity:.2%}\n"
            f"  Shared references: {len(self.shared_references)}\n"
            f"  Shared authors: {len(self.shared_authors)}"
        )


class PaperAnalyzer:
    """Academic paper analysis utilities.

    Provides paper summarization, comparison, and reference analysis.

    Usage:
        analyzer = PaperAnalyzer()

        # Summarize a paper from text
        summary = analyzer.summarize(text_content)

        # Compare two papers
        comparison = analyzer.compare(summary_a, summary_b)
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
    ) -> None:
        """Initialize paper analyzer.

        Args:
            config: Configuration from config.toml [research.paper] section.
        """
        self._config = config or {}
        self._max_context = self._config.get("max_context", 8000)

    def summarize(
        self,
        text: str,
        title: str = "",
        authors: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PaperSummary:
        """Create a paper summary from text content.

        Args:
            text: Paper text content (abstract, introduction, etc.).
            title: Paper title.
            authors: List of author names.
            metadata: Additional metadata.

        Returns:
            PaperSummary object.
        """
        # Extract basic info from text
        abstract = ""
        year = 0
        venue = ""
        keywords: list[str] = []

        # Try to extract abstract (common pattern)
        if "abstract" in text.lower():
            parts = text.lower().split("abstract")
            if len(parts) > 1:
                abstract_part = parts[1]
                # Abstract typically ends before introduction or first section header
                for sep in ["\n\nintroduction", "\n\nmethodology", "\n\nrelated work", "\n\n"]:
                    if sep in abstract_part:
                        abstract = abstract_part.split(sep)[0].strip()
                        break
                if not abstract:
                    abstract = abstract_part[:2000]

        # Try to extract year
        import re
        year_matches = re.findall(r"\b(19[0-9]{2}|20[0-9]{2})\b", text)
        if year_matches:
            year = max(int(y) for y in year_matches)

        # Try to extract venue
        venue_patterns = [
            r"in\s+([\w\s]+(?:Conference|Journal|Symposium|Workshop|Proceedings))",
            r"published\s+in\s+([\w\s]+)",
        ]
        for pattern in venue_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                venue = match.group(1).strip()
                break

        return PaperSummary(
            title=title,
            authors=authors or [],
            abstract=abstract,
            year=year,
            venue=venue,
            keywords=keywords,
            metadata=metadata or {},
        )

    @staticmethod
    def compare_summaries(
        summary_a: PaperSummary,
        summary_b: PaperSummary,
    ) -> PaperComparison:
        """Compare two paper summaries.

        Args:
            summary_a: First paper summary.
            summary_b: Second paper summary.

        Returns:
            PaperComparison with similarity metrics.
        """
        # Calculate shared references
        refs_a = set(summary_a.references)
        refs_b = set(summary_b.references)
        shared_refs = refs_a & refs_b

        # Calculate shared authors
        authors_a = set(summary_a.authors)
        authors_b = set(summary_b.authors)
        shared_authors = authors_a & authors_b

        # Calculate keyword similarity
        kw_a = set(summary_a.keywords)
        kw_b = set(summary_b.keywords)
        keyword_similarity = len(kw_a & kw_b) / max(len(kw_a | kw_b), 1)

        # Calculate abstract similarity (simple word overlap)
        words_a = set(summary_a.abstract.lower().split())
        words_b = set(summary_b.abstract.lower().split())
        abstract_similarity = len(words_a & words_b) / max(len(words_a | words_b), 1)

        # Calculate citation overlap
        citation_overlap = (
            len(refs_a & refs_b) / max(len(refs_a | refs_b), 1)
            if refs_a or refs_b
            else 0.0
        )

        # Combined similarity score
        similarity = (
            abstract_similarity * 0.4 +
            keyword_similarity * 0.3 +
            citation_overlap * 0.3
        )

        return PaperComparison(
            paper_a=summary_a.title,
            paper_b=summary_b.title,
            similarity=similarity,
            shared_references=list(shared_refs),
            shared_authors=list(shared_authors),
            citation_overlap=citation_overlap,
        )

    @staticmethod
    def extract_metadata_from_pdf(pdf_path: str | Path) -> dict[str, Any]:
        """Extract metadata from a PDF file.

        Args:
            pdf_path: Path to the PDF file.

        Returns:
            Dictionary of metadata fields.
        """
        path = Path(pdf_path)
        result: dict[str, Any] = {}

        if not path.exists():
            return result

        try:
            import fitz  # PyMuPDF
            doc = fitz.open(str(path))
            info = doc.metadata or {}

            result = {
                "title": info.get("title", ""),
                "author": info.get("author", ""),
                "subject": info.get("subject", ""),
                "creator": info.get("creator", ""),
                "producer": info.get("producer", ""),
                "creationDate": info.get("creationDate", ""),
                "modDate": info.get("modDate", ""),
                "keywords": info.get("keywords", ""),
                "format": info.get("format", ""),
                "page_count": len(doc),
                "file_size": path.stat().st_size,
            }
            doc.close()
        except ImportError:
            logger.warning("PyMuPDF not installed for metadata extraction")
            result["file_size"] = path.stat().st_size

        return result

    @staticmethod
    def compute_similarity(text_a: str, text_b: str) -> float:
        """Compute similarity between two text strings.

        Uses simple word-overlap Jaccard similarity.

        Args:
            text_a: First text.
            text_b: Second text.

        Returns:
            Similarity score (0.0 to 1.0).
        """
        words_a = set(text_a.lower().split())
        words_b = set(text_b.lower().split())

        if not words_a or not words_b:
            return 0.0

        intersection = words_a & words_b
        union = words_a | words_b

        return len(intersection) / len(union)

    @staticmethod
    def compute_hashes(texts: list[str]) -> list[str]:
        """Compute content hashes for a list of texts.

        Args:
            texts: List of text strings.

        Returns:
            List of SHA-256 hex digests.
        """
        return [hashlib.sha256(t.encode()).hexdigest()[:16] for t in texts]

    @staticmethod
    def extract_abstract(text: str) -> str:
        """Extract abstract from paper text.

        Args:
            text: Full paper text.

        Returns:
            Extracted abstract string.
        """
        import re

        # Try common abstract patterns
        patterns = [
            r"(?i)abstract\s*\n\s*(.+?)(?=\n\s*\n\s*(?:introduction|related\s*work|background|methodology|approach))",
            r"(?i)abstract\s*\n\s*(.+?)(?=\n\s*\n\s*[A-Z][a-z]+(?:\s+[a-z]+)*\s*\n)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                return match.group(1).strip()

        # If no pattern matches, return first paragraph
        paragraphs = text.split("\n\n")
        if paragraphs:
            return paragraphs[0].strip()

        return ""

    @staticmethod
    def extract_keywords(text: str, top_k: int = 10) -> list[str]:
        """Extract keywords from paper text.

        Uses simple frequency-based keyword extraction.

        Args:
            text: Paper text.
            top_k: Number of keywords to return.

        Returns:
            List of keywords.
        """
        import re
        from collections import Counter

        # Common English stop words
        stop_words = {
            "the", "a", "an", "and", "or", "but", "in", "on", "at",
            "to", "for", "of", "with", "by", "is", "are", "was", "were",
            "be", "been", "being", "have", "has", "had", "do", "does",
            "did", "will", "would", "could", "should", "may", "might",
            "can", "shall", "this", "that", "these", "those", "it",
            "its", "from", "as", "into", "through", "during", "before",
            "after", "above", "below", "between", "under", "again",
            "further", "then", "once", "here", "there", "when", "where",
            "why", "how", "all", "each", "few", "more", "most", "other",
            "some", "such", "no", "nor", "not", "only", "own", "same",
            "so", "than", "too", "very", "just", "because", "if",
        }

        # Extract words (excluding stop words)
        words = re.findall(r"\b[a-zA-Z]{3,}\b", text.lower())
        filtered = [w for w in words if w not in stop_words]

        # Count frequencies
        freq = Counter(filtered)
        return [word for word, _ in freq.most_common(top_k)]
