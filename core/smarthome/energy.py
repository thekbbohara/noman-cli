"""Home Assistant energy monitoring.

Provides energy dashboard data, consumption tracking,
and solar/generation monitoring.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from core.smarthome.hass import HomeAssistantClient

logger = logging.getLogger(__name__)


@dataclass
class EnergyDaily:
    """Daily energy summary."""

    start: str  # ISO datetime
    end: str  # ISO datetime
    source_energy: float = 0.0  # Energy consumed from source
    source_cost: float = 0.0  # Cost of energy
    source_stat: str = ""  # Sensor entity ID
    back_energy: float = 0.0  # Energy returned to grid
    back_cost: float = 0.0  # Credit for returned energy
    back_stat: str = ""  # Sensor entity ID
    grid_cost: float = 0.0  # Grid cost
    solar_cost: float = 0.0  # Solar cost


@dataclass
class EnergyPreference:
    """Energy preference settings."""

    preference_id: str
    type: str  # grid, solar, battery
    name: str
    config: dict[str, Any] = field(default_factory=dict)


class EnergyClient:
    """Home Assistant energy monitoring client.

    Provides access to energy dashboard data, consumption tracking,
    solar/generation monitoring, and cost analysis.
    Requires a HomeAssistantClient instance.
    """

    def __init__(self, hass: HomeAssistantClient) -> None:
        self.hass = hass

    # ── Energy preferences ──

    async def get_preferences(self) -> list[EnergyPreference]:
        """Get energy preference settings."""
        data = await self.hass._rest_get("energy/preferences")
        if not data:
            return []
        return [
            EnergyPreference(
                preference_id=str(p.get("id", "")),
                type=p.get("type", ""),
                name=p.get("name", ""),
                config=p.get("config", {}),
            )
            for p in data
        ]

    async def get_default_energy_pref(self) -> EnergyPreference | None:
        """Get the default energy preference."""
        prefs = await self.get_preferences()
        for p in prefs:
            if p.type == "grid":
                return p
        return prefs[0] if prefs else None

    # ── Daily energy data ──

    async def get_daily(
        self, start_day: str, end_day: str | None = None
    ) -> list[EnergyDaily]:
        """Get daily energy data.

        Args:
            start_day: Start date (YYYY-MM-DD).
            end_day: End date (YYYY-MM-DD). Defaults to today.

        Returns:
            List of daily energy summaries.
        """
        if not end_day:
            end_day = start_day

        params = {
            "start_date": start_day,
            "end_date": end_day,
        }
        data = await self.hass._rest_get("energy/history", params=params)
        if not data:
            return []

        return [
            EnergyDaily(
                start=str(item.get("start", "")),
                end=str(item.get("end", "")),
                source_energy=item.get("source_energy", 0.0),
                source_cost=item.get("source_cost", 0.0),
                source_stat=item.get("source_stat", ""),
                back_energy=item.get("back_energy", 0.0),
                back_cost=item.get("back_cost", 0.0),
                back_stat=item.get("back_stat", ""),
                grid_cost=item.get("grid_cost", 0.0),
                solar_cost=item.get("solar_cost", 0.0),
            )
            for item in data
        ]

    async def get_weekly(self, start_week: str) -> list[EnergyDaily]:
        """Get weekly energy data starting from a date.

        Args:
            start_week: Start date (YYYY-MM-DD).

        Returns:
            List of daily energy summaries for the week.
        """
        return await self.get_daily(start_week, start_week)

    async def get_monthly(self, start_month: str) -> list[EnergyDaily]:
        """Get monthly energy data starting from a date.

        Args:
            start_month: Start date (YYYY-MM-DD).

        Returns:
            List of daily energy summaries for the month.
        """
        return await self.get_daily(start_month, start_month)

    # ── Current consumption ──

    async def get_current_consumption(self) -> dict[str, float]:
        """Get current power consumption from all sources.

        Returns:
            Dict of source_id -> current_power (W).
        """
        data = await self.hass._rest_get("energy/current")
        if not data:
            return {}
        return {
            str(item.get("key", "")): item.get("power", 0.0)
            for item in data
        }

    async def get_grid_consumption(self) -> float:
        """Get current grid consumption (W)."""
        consumption = await self.get_current_consumption()
        return consumption.get("grid", 0.0)

    async def get_solar_production(self) -> float:
        """Get current solar production (W)."""
        consumption = await self.get_current_consumption()
        return consumption.get("solar", 0.0)

    # ── Solar monitoring ──

    async def get_solar_daily(
        self, start_day: str, end_day: str | None = None
    ) -> list[float]:
        """Get daily solar production data.

        Args:
            start_day: Start date (YYYY-MM-DD).
            end_day: End date (YYYY-MM-DD).

        Returns:
            List of daily solar production values (Wh).
        """
        prefs = await self.get_preferences()
        solar_prefs = [p for p in prefs if p.type == "solar"]
        if not solar_prefs:
            return []

        data = await self.get_daily(start_day, end_day)
        return [d.source_energy for d in data]

    async def get_solar_power(self) -> float:
        """Get current solar production power (W)."""
        consumption = await self.get_current_consumption()
        return consumption.get("solar", 0.0)

    # ── Battery monitoring ──

    async def get_battery_state(self) -> dict[str, Any] | None:
        """Get battery storage state."""
        data = await self.hass._rest_get("energy/battery")
        return data

    async def get_battery_charge(self) -> float | None:
        """Get battery charge percentage."""
        state = await self.get_battery_state()
        if state:
            return state.get("charge", 0.0)
        return None

    async def get_battery_power(self) -> float | None:
        """Get battery power flow (W). Positive = charging, negative = discharging."""
        state = await self.get_battery_state()
        if state:
            return state.get("power", 0.0)
        return None

    # ── Cost analysis ──

    async def get_total_cost(
        self, start_day: str, end_day: str | None = None
    ) -> float:
        """Get total energy cost over a period.

        Args:
            start_day: Start date (YYYY-MM-DD).
            end_day: End date (YYYY-MM-DD).

        Returns:
            Total cost in configured currency.
        """
        days = await self.get_daily(start_day, end_day)
        return sum(d.source_cost + d.back_cost for d in days)

    async def get_grid_cost(
        self, start_day: str, end_day: str | None = None
    ) -> float:
        """Get grid energy cost over a period."""
        days = await self.get_daily(start_day, end_day)
        return sum(d.grid_cost for d in days)

    async def get_solar_cost(
        self, start_day: str, end_day: str | None = None
    ) -> float:
        """Get solar energy cost over a period."""
        days = await self.get_daily(start_day, end_day)
        return sum(d.solar_cost for d in days)

    async def get_net_cost(
        self, start_day: str, end_day: str | None = None
    ) -> float:
        """Get net cost (grid cost - solar credit)."""
        return await self.get_grid_cost(start_day, end_day) - await self.get_solar_cost(
            start_day, end_day
        )

    # ── Summary ──

    async def get_summary(
        self, start_day: str, end_day: str | None = None
    ) -> dict[str, Any]:
        """Get a comprehensive energy summary for a period.

        Args:
            start_day: Start date (YYYY-MM-DD).
            end_day: End date (YYYY-MM-DD).

        Returns:
            Summary dict with totals and breakdowns.
        """
        days = await self.get_daily(start_day, end_day)
        total_consumption = sum(d.source_energy for d in days)
        total_solar = sum(d.source_energy for d in days)
        total_back = sum(d.back_energy for d in days)
        total_cost = sum(d.source_cost + d.back_cost for d in days)

        return {
            "start_day": start_day,
            "end_day": end_day or start_day,
            "days": len(days),
            "total_consumption_wh": total_consumption,
            "total_solar_wh": total_solar,
            "total_back_to_grid_wh": total_back,
            "total_cost": total_cost,
            "daily_averages": {
                "consumption_wh": total_consumption / max(len(days), 1),
                "cost": total_cost / max(len(days), 1),
            },
        }

    async def get_energy_stats(self) -> dict[str, Any]:
        """Get overall energy statistics from Home Assistant."""
        data = await self.hass._rest_get("energy/stats")
        if not data:
            return {}
        return data
