"""Polymarket API client for prediction market data.

Searches and retrieves data from Polymarket's prediction markets:
    - Market search by keyword
    - Market details (outcomes, volume, liquidity, CLOB id)
    - Market history and price data
    - User positions and PnL

API: https://polymarket.com/api

Configuration (in ~/.noman/config.toml):
    [research.polymarket]
    api_base = "https://gamma-api.polymarket.com"
    data_api_base = "https://clob.polymarket.com"
    timeout = 30
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

DEFAULT_API_BASE = "https://gamma-api.polymarket.com"
DEFAULT_CLOB_BASE = "https://clob.polymarket.com"


@dataclass
class MarketSearchResult:
    """Result from a Polymarket market search."""
    id: str
    slug: str
    question: str
    outcome: str
    outcomes: list[str]
    volume: float
    liquidity: float
    closed: bool
    open_date: str
    close_date: str
    last_price: float
    outcome_prices: list[float]
    clob_token_id: str = ""
    symbol: str = ""
    condition_id: str = ""

    def __str__(self) -> str:
        return (
            f"[{self.question}]\n"
            f"  Outcome: {self.outcome}\n"
            f"  Price: ${self.last_price:.4f}\n"
            f"  Volume: ${self.volume:,.0f}\n"
            f"  Closed: {self.closed}\n"
            f"  ID: {self.id}"
        )


@dataclass
class MarketData:
    """Detailed market data."""
    id: str
    slug: str
    question: str
    outcomes: list[str]
    outcome_prices: list[float]
    volume: float
    liquidity: float
    open_interest: float
    closed: bool
    open_date: str
    close_date: str
    last_price: float
    clob_token_id: str = ""
    condition_id: str = ""
    category: str = ""
    tags: list[str] = field(default_factory=list)
    imageUrl: str = ""
    numerator: str = ""
    denominator: str = ""

    def get_outcome_price(self, outcome: str) -> float:
        """Get the current price for a specific outcome."""
        try:
            idx = self.outcomes.index(outcome)
            return self.outcome_prices[idx] if idx < len(self.outcome_prices) else 0.0
        except ValueError:
            return 0.0

    @property
    def expected_payout(self) -> float:
        """Get the expected payout based on current prices."""
        if self.outcome_prices:
            return sum(self.outcome_prices)
        return 0.0

    def __str__(self) -> str:
        price_str = " | ".join(
            f"{o}: ${p:.4f}" for o, p in zip(self.outcomes, self.outcome_prices)
        )
        return (
            f"[{self.question}]\n"
            f"  {price_str}\n"
            f"  Volume: ${self.volume:,.0f} | Liquidity: ${self.liquidity:,.0f}\n"
            f"  Closed: {self.closed} | Close: {self.close_date}"
        )


class PolymarketClient:
    """Polymarket API client for prediction market data.

    Usage:
        client = PolymarketClient()
        results = await client.search("bitcoin")
        for market in results:
            print(market)

        # Get detailed market data
        data = await client.get_market("market-id")
        print(data)
    """

    def __init__(
        self,
        api_base: str = DEFAULT_API_BASE,
        clob_base: str = DEFAULT_CLOB_BASE,
        timeout: float = 30.0,
        config: dict[str, Any] | None = None,
    ) -> None:
        """Initialize Polymarket client.

        Args:
            api_base: Gamma API base URL.
            clob_base: CLOB API base URL.
            timeout: Request timeout in seconds.
            config: Configuration dict from config.toml [research.polymarket] section.
        """
        self._config = config or {}
        self._api_base = self._config.get("api_base", api_base)
        self._clob_base = self._config.get("clob_base", clob_base)
        self._timeout = self._config.get("timeout", timeout)
        self._cache: dict[str, MarketData] = {}

    async def search(
        self,
        query: str,
        limit: int = 20,
        closed: bool = False,
        order_by: str = "volume",
    ) -> list[MarketSearchResult]:
        """Search markets by keyword.

        Args:
            query: Search query.
            limit: Maximum results.
            closed: Include closed markets.
            order_by: Sort field ('volume', 'liquidity', 'close_date').

        Returns:
            List of MarketSearchResult objects.
        """
        params = {
            "limit": str(limit),
            "order_by": order_by,
        }
        if not closed:
            params["closed"] = "false"

        # Search in question and tag fields
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            all_results: list[MarketSearchResult] = []

            # Search by query
            resp = await client.get(
                f"{self._api_base}/markets",
                params={**params, "q": query},
            )
            resp.raise_for_status()
            data = resp.json()

            for item in data:
                all_results.append(self._parse_market_search(item))

            # Also search by tags
            if not all_results:
                resp = await client.get(
                    f"{self._api_base}/markets",
                    params={**params, "tag": query},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    for item in data:
                        all_results.append(self._parse_market_search(item))

            return all_results[:limit]

    async def get_market(
        self,
        market_id: str,
    ) -> MarketData | None:
        """Get detailed data for a specific market.

        Args:
            market_id: Market ID.

        Returns:
            MarketData or None if not found.
        """
        if market_id in self._cache:
            return self._cache[market_id]

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self._api_base}/market/{market_id}",
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
            result = self._parse_market_data(data)
            self._cache[market_id] = result
            return result

    async def get_market_history(
        self,
        market_id: str,
        interval: str = "1h",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get price history for a market.

        Args:
            market_id: Market ID.
            interval: Time interval ('1m', '5m', '15m', '1h', '4h', '1d', '1w').
            limit: Maximum data points.

        Returns:
            List of price history entries.
        """
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self._clob_base}/depth/{market_id}",
                params={"interval": interval, "limit": str(limit)},
            )
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            data = resp.json()
            return data.get("bids", []) + data.get("asks", [])

    async def get_markets_by_tag(
        self,
        tag: str,
        limit: int = 20,
    ) -> list[MarketSearchResult]:
        """Get markets by tag.

        Args:
            tag: Tag name (e.g., 'politics', 'crypto', 'sports').
            limit: Maximum results.

        Returns:
            List of MarketSearchResult objects.
        """
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self._api_base}/markets",
                params={"limit": str(limit), "tag": tag},
            )
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            data = resp.json()
            return [self._parse_market_search(item) for item in data]

    async def get_active_markets(
        self,
        limit: int = 50,
        order_by: str = "volume",
    ) -> list[MarketSearchResult]:
        """Get active (non-closed) markets.

        Args:
            limit: Maximum results.
            order_by: Sort field.

        Returns:
            List of active MarketSearchResult objects.
        """
        return await self.search(query="", limit=limit, closed=False, order_by=order_by)

    def _parse_market_search(self, data: dict[str, Any]) -> MarketSearchResult:
        """Parse a market search result."""
        outcomes = data.get("outcomes", [])
        outcome_prices = data.get("outcome_prices", [])

        return MarketSearchResult(
            id=str(data.get("id", "")),
            slug=data.get("slug", ""),
            question=data.get("question", ""),
            outcome=data.get("outcome", ""),
            outcomes=outcomes,
            volume=float(data.get("volume", 0) or 0),
            liquidity=float(data.get("liquidity", 0) or 0),
            closed=data.get("closed", False),
            open_date=data.get("open_date", ""),
            close_date=data.get("close_date", ""),
            last_price=float(data.get("last_price", 0) or 0),
            outcome_prices=outcome_prices,
            clob_token_id=data.get("clob_token_id", ""),
            symbol=data.get("symbol", ""),
            condition_id=data.get("condition_id", ""),
        )

    def _parse_market_data(self, data: dict[str, Any]) -> MarketData:
        """Parse detailed market data."""
        outcomes = data.get("outcomes", [])
        outcome_prices = data.get("outcome_prices", [])
        tags = data.get("tags", [])
        if isinstance(tags, str):
            tags = [tags]

        return MarketData(
            id=str(data.get("id", "")),
            slug=data.get("slug", ""),
            question=data.get("question", ""),
            outcomes=outcomes,
            outcome_prices=[float(p) for p in outcome_prices],
            volume=float(data.get("volume", 0) or 0),
            liquidity=float(data.get("liquidity", 0) or 0),
            open_interest=float(data.get("open_interest", 0) or 0),
            closed=data.get("closed", False),
            open_date=data.get("open_date", ""),
            close_date=data.get("close_date", ""),
            last_price=float(data.get("last_price", 0) or 0),
            clob_token_id=data.get("clob_token_id", ""),
            condition_id=data.get("condition_id", ""),
            category=data.get("category", ""),
            tags=tags,
            imageUrl=data.get("imageUrl", ""),
            numerator=data.get("numerator", ""),
            denominator=data.get("denominator", ""),
        )

    def clear_cache(self) -> None:
        """Clear the market data cache."""
        self._cache.clear()
