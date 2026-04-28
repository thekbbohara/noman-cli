"""LLM Wiki integration for tracking LLM model knowledge.

Provides integration with LLM-focused wikis and knowledge bases:
    - Model information and specs
    - Architecture details
    - Benchmark results
    - Model comparisons
    - Knowledge graph queries

Configuration (in ~/.noman/config.toml):
    [research.llm_wiki]
    api_base = "https://llm-wiki.example.com/api"
    timeout = 30
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_API_BASE = "https://llm-wiki.example.com/api"


@dataclass
class LLMModelInfo:
    """Information about an LLM model."""
    name: str
    provider: str
    model_type: str  # e.g., 'llm', 'vision', 'embedding'
    context_window: int = 0
    parameters: str = ""
    release_date: str = ""
    capabilities: list[str] = field(default_factory=list)
    benchmarks: dict[str, float] = field(default_factory=dict)
    url: str = ""
    description: str = ""
    pricing: dict[str, str] = field(default_factory=dict)
    known_issues: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"{self.name} ({self.provider})\n"
            f"  Type: {self.model_type} | Parameters: {self.parameters}\n"
            f"  Context: {self.context_window} | Released: {self.release_date}\n"
            f"  Capabilities: {', '.join(self.capabilities[:5])}\n"
            f"  URL: {self.url}"
        )


@dataclass
class BenchmarkResult:
    """A benchmark result."""
    model: str
    benchmark: str
    score: float
    details: str = ""
    date: str = ""
    source: str = ""

    def __str__(self) -> str:
        return f"{self.model} | {self.benchmark}: {self.score}"


class LLMWikiClient:
    """LLM Wiki API client for model knowledge retrieval.

    Usage:
        client = LLMWikiClient()
        info = await client.get_model("gpt-4")
        benchmarks = await client.get_benchmarks("gpt-4")
        models = await client.search("vision models")
    """

    def __init__(
        self,
        api_base: str = DEFAULT_API_BASE,
        timeout: float = 30.0,
        config: dict[str, Any] | None = None,
    ) -> None:
        """Initialize LLM Wiki client.

        Args:
            api_base: API base URL.
            timeout: Request timeout.
            config: Configuration from config.toml [research.llm_wiki] section.
        """
        self._config = config or {}
        self._api_base = self._config.get("api_base", api_base)
        self._timeout = self._config.get("timeout", timeout)
        self._cache: dict[str, LLMModelInfo] = {}

    async def get_model(self, model_id: str) -> LLMModelInfo | None:
        """Get information about a specific LLM model.

        Args:
            model_id: Model identifier (e.g., 'gpt-4', 'claude-3-opus').

        Returns:
            LLMModelInfo or None if not found.
        """
        if model_id in self._cache:
            return self._cache[model_id]

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(f"{self._api_base}/models/{model_id}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
            model = self._parse_model_info(data)
            self._cache[model_id] = model
            return model

    async def get_benchmarks(
        self,
        model_id: str,
        benchmark: str | None = None,
    ) -> list[BenchmarkResult]:
        """Get benchmark results for a model.

        Args:
            model_id: Model identifier.
            benchmark: Optional benchmark name filter.

        Returns:
            List of BenchmarkResult objects.
        """
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self._api_base}/models/{model_id}/benchmarks",
                params={"benchmark": benchmark} if benchmark else {},
            )
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            return [self._parse_benchmark(item) for item in resp.json()]

    async def search(
        self,
        query: str,
        model_type: str | None = None,
        provider: str | None = None,
        limit: int = 20,
    ) -> list[LLMModelInfo]:
        """Search for LLM models.

        Args:
            query: Search query.
            model_type: Filter by model type.
            provider: Filter by provider.
            limit: Maximum results.

        Returns:
            List of matching LLMModelInfo objects.
        """
        params = {"q": query, "limit": str(limit)}
        if model_type:
            params["type"] = model_type
        if provider:
            params["provider"] = provider

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(f"{self._api_base}/models/search", params=params)
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            return [self._parse_model_info(item) for item in resp.json()]

    async def compare_models(
        self,
        model_ids: list[str],
    ) -> dict[str, LLMModelInfo]:
        """Compare multiple models side by side.

        Args:
            model_ids: List of model identifiers.

        Returns:
            Dict mapping model_id to LLMModelInfo.
        """
        results: dict[str, LLMModelInfo] = {}
        for model_id in model_ids:
            info = await self.get_model(model_id)
            if info:
                results[model_id] = info
        return results

    async def list_providers(self) -> list[str]:
        """List all available model providers."""
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(f"{self._api_base}/providers")
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            return [p.get("name", "") for p in resp.json()]

    def _parse_model_info(self, data: dict[str, Any]) -> LLMModelInfo:
        """Parse model info from API response."""
        return LLMModelInfo(
            name=data.get("name", ""),
            provider=data.get("provider", ""),
            model_type=data.get("model_type", "llm"),
            context_window=data.get("context_window", 0),
            parameters=str(data.get("parameters", "")),
            release_date=data.get("release_date", ""),
            capabilities=data.get("capabilities", []),
            benchmarks=data.get("benchmarks", {}),
            url=data.get("url", ""),
            description=data.get("description", ""),
            pricing=data.get("pricing", {}),
            known_issues=data.get("known_issues", []),
            tags=data.get("tags", []),
        )

    def _parse_benchmark(self, data: dict[str, Any]) -> BenchmarkResult:
        """Parse benchmark result from API response."""
        return BenchmarkResult(
            model=data.get("model", ""),
            benchmark=data.get("benchmark", ""),
            score=float(data.get("score", 0)),
            details=data.get("details", ""),
            date=data.get("date", ""),
            source=data.get("source", ""),
        )

    def clear_cache(self) -> None:
        """Clear the model cache."""
        self._cache.clear()
