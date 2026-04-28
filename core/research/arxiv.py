"""arXiv paper search and retrieval."""

from __future__ import annotations

import logging
import urllib.request
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ArxivPaper:
    """An arXiv paper."""
    id: str
    title: str
    authors: list[str]
    summary: str
    published: datetime
    categories: list[str]
    pdf_url: str
    links: list[str] = field(default_factory=list)


@dataclass
class ArxivConfig:
    """arXiv configuration."""
    base_url: str = "http://export.arxiv.org/api/query"
    max_results: int = 20
    timeout: int = 30


class ArxivClient:
    """arXiv client for paper search and retrieval."""

    def __init__(self, config: ArxivConfig | None = None):
        self._config = config or ArxivConfig()

    async def search(
        self,
        query: str,
        max_results: int = 20,
        sort_by: str = "relevance",
    ) -> list[ArxivPaper]:
        """Search arXiv papers."""
        params = urllib.parse.urlencode({
            "search_query": query,
            "start": 0,
            "max_results": max_results,
            "sortBy": sort_by,
        })
        url = f"{self._config.base_url}?{params}"
        logger.info(f"Searching arXiv: {query}")
        try:
            with urllib.request.urlopen(url, timeout=self._config.timeout) as response:
                data = response.read().decode("utf-8")
                return self._parse_response(data)
        except Exception as e:
            logger.error(f"arXiv search failed: {e}")
            return []

    async def get_paper(self, arxiv_id: str) -> ArxivPaper | None:
        """Get a specific paper by arXiv ID."""
        query = f"id_list:{arxiv_id}"
        results = await self.search(query, max_results=1)
        return results[0] if results else None

    async def download_pdf(self, paper: ArxivPaper, destination: str = "") -> str:
        """Download a paper's PDF."""
        if not destination:
            destination = f"/tmp/{paper.title[:50]}.pdf"
        try:
            urllib.request.urlretrieve(paper.pdf_url, destination)
            return destination
        except Exception as e:
            logger.error(f"Failed to download PDF: {e}")
            return ""

    def _parse_response(self, xml_data: str) -> list[ArxivPaper]:
        """Parse arXiv API XML response."""
        papers = []
        # Simple XML parsing - in production use feedparser
        import xml.etree.ElementTree as ET
        try:
            root = ET.fromstring(xml_data)
            ns = {
                "atom": "http://www.w3.org/2005/Atom",
                "arxiv": "http://arxiv.org/schemas/atom",
            }
            for entry in root.findall("atom:entry", ns):
                title = entry.find("atom:title", ns)
                summary = entry.find("atom:summary", ns)
                published = entry.find("atom:published", ns)
                authors = entry.findall("atom:author", ns)
                pdf_links = entry.findall(
                    "atom:link[@title='pdf']",
                    {"atom": "http://www.w3.org/Atom"},
                )
                categories = entry.findall(
                    "atom:category",
                    {"atom": "http://www.w3.org/Atom"},
                )
                arxiv_id = entry.find("atom:id", ns)
                if title is not None and arxiv_id is not None:
                    papers.append(ArxivPaper(
                        id=arxiv_id.text or "",
                        title=title.text or "",
                        summary=(summary.text or "") if summary is not None else "",
                        published=(
                            datetime.fromisoformat(published.text)
                            if published is not None and published.text
                            else datetime.now()
                        ),
                        authors=[
                            a.find("atom:name", ns).text or ""
                            for a in authors
                            if a.find("atom:name", ns) is not None
                        ],
                        pdf_url=pdf_links[0].get("href") if pdf_links else "",
                        links=[
                            c.get("term")
                            for c in categories
                            if c.get("term")
                        ],
                    ))
        except Exception as e:
            logger.error(f"Failed to parse arXiv response: {e}")
        return papers
