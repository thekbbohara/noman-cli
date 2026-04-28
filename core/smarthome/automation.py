"""Home Assistant automation management.

Provides automation listing, triggering, creation, and deletion.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from core.smarthome.hass import HomeAssistantClient

logger = logging.getLogger(__name__)


@dataclass
class Automation:
    """Home Assistant automation representation."""

    automation_id: str
    name: str
    description: str = ""
    state: str = "on"  # on, off
    last_triggered: str = ""
    mode: str = "single"  # single, restart, queued, parallel
    max_passes: int = 0
    max_passes_seconds: int = 0
    icon: str = ""
    category: str = ""
    is_enabled: bool = True
    is_configured: bool = True
    options: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        return self.state == "on"


class AutomationsClient:
    """Manage Home Assistant automations.

    Provides automation listing, triggering, creation, and deletion.
    Requires a HomeAssistantClient instance.
    """

    def __init__(self, hass: HomeAssistantClient) -> None:
        self.hass = hass

    async def get_all_automations(self) -> list[Automation]:
        """Get all automations from Home Assistant."""
        data = await self.hass._rest_get("automation")
        if not data:
            return []
        return [
            Automation(
                automation_id=item.get("entity_id", ""),
                name=item.get("attributes", {}).get("friendly_name", ""),
                description=item.get("attributes", {}).get("friendly_name", ""),
                state=item.get("state", "off"),
                last_triggered=item.get("attributes", {}).get(
                    "last_triggered", ""
                ),
                mode=item.get("attributes", {}).get("mode", "single"),
                max_passes=item.get("attributes", {}).get(
                    "max_passes", 0
                ),
                max_passes_seconds=item.get("attributes", {}).get(
                    "max_passes_seconds", 0
                ),
                icon=item.get("attributes", {}).get("icon", ""),
                category=item.get("attributes", {}).get("category", ""),
                is_enabled=item.get("state") == "on",
                config=item.get("attributes", {}).get("config", {}),
            )
            for item in data
        ]

    async def get_automation(self, automation_id: str) -> Automation | None:
        """Get a specific automation by ID."""
        data = await self.hass._rest_get(f"automation/{automation_id}")
        if data:
            return Automation(
                automation_id=data.get("entity_id", ""),
                name=data.get("attributes", {}).get("friendly_name", ""),
                description=data.get("attributes", {}).get(
                    "friendly_name", ""
                ),
                state=data.get("state", "off"),
                last_triggered=data.get("attributes", {}).get(
                    "last_triggered", ""
                ),
                mode=data.get("attributes", {}).get("mode", "single"),
                icon=data.get("attributes", {}).get("icon", ""),
                category=data.get("attributes", {}).get("category", ""),
                is_enabled=data.get("state") == "on",
                config=data.get("attributes", {}).get("config", {}),
            )
        return None

    async def trigger(
        self,
        automation_id: str,
        skip_condition: bool = False,
        skip_action: bool = False,
    ) -> bool:
        """Trigger an automation.

        Args:
            automation_id: Automation entity ID (e.g., 'automation.morning').
            skip_condition: Skip condition evaluation.
            skip_action: Skip action execution (dry run).

        Returns:
            True if trigger succeeded.
        """
        payload: dict[str, Any] = {"entity_id": automation_id}
        if skip_condition:
            payload["skip_condition"] = True
        if skip_action:
            payload["skip_action"] = True

        result = await self.hass._rest_post(
            "automation/trigger",
            payload,
        )
        return result is not None

    async def toggle(self, automation_id: str) -> bool:
        """Toggle an automation (on <-> off)."""
        state_data = await self.hass.get_state(automation_id)
        if not state_data:
            return False
        new_state = "on" if state_data.state == "off" else "off"
        return await self.hass.call_service(
            "automation", f"turn_{new_state}", {"entity_id": automation_id}
        )

    async def turn_on(self, automation_id: str) -> bool:
        """Enable an automation."""
        return await self.hass.call_service(
            "automation", "turn_on", {"entity_id": automation_id}
        )

    async def turn_off(self, automation_id: str) -> bool:
        """Disable an automation."""
        return await self.hass.call_service(
            "automation", "turn_off", {"entity_id": automation_id}
        )

    async def create(
        self,
        automation_id: str,
        name: str,
        trigger: dict[str, Any],
        condition: dict[str, Any] | None = None,
        action: dict[str, Any] | None = None,
        mode: str = "single",
        description: str = "",
    ) -> bool:
        """Create a new automation.

        Args:
            automation_id: Automation entity ID (e.g., 'automation.away_mode').
            name: Display name.
            trigger: Trigger configuration dict.
            condition: Condition configuration dict.
            action: Action configuration dict.
            mode: Execution mode (single, restart, queued, parallel).
            description: Automation description.

        Returns:
            True if creation succeeded.
        """
        payload: dict[str, Any] = {
            "id": automation_id.replace(".", "_"),
            "name": name,
            "trigger": trigger,
        }
        if condition:
            payload["condition"] = condition
        if action:
            payload["action"] = action
        else:
            # Default: do nothing (useful for manual trigger)
            payload["action"] = {
                "alias": "Do nothing",
                "sequence": [],
            }
        if mode != "single":
            payload["mode"] = mode
        if description:
            payload["description"] = description

        result = await self.hass._rest_post(
            "automation/create",
            payload,
        )
        return result is not None

    async def delete(self, automation_id: str) -> bool:
        """Delete an automation.

        Args:
            automation_id: Automation entity ID.

        Returns:
            True if deletion succeeded.
        """
        return await self.hass._rest_delete(f"automation/{automation_id}")

    async def update(
        self,
        automation_id: str,
        name: str | None = None,
        trigger: dict[str, Any] | None = None,
        condition: dict[str, Any] | None = None,
        action: dict[str, Any] | None = None,
        mode: str | None = None,
    ) -> bool:
        """Update an existing automation.

        Args:
            automation_id: Automation entity ID.
            name: New display name.
            trigger: New trigger config.
            condition: New condition config.
            action: New action config.
            mode: New execution mode.

        Returns:
            True if update succeeded.
        """
        payload: dict[str, Any] = {"entity_id": automation_id}
        if name is not None:
            payload["name"] = name
        if trigger is not None:
            payload["trigger"] = trigger
        if condition is not None:
            payload["condition"] = condition
        if action is not None:
            payload["action"] = action
        if mode is not None:
            payload["mode"] = mode

        result = await self.hass._rest_post(
            "automation/update",
            payload,
        )
        return result is not None

    async def get_automations_by_area(
        self, area_name: str
    ) -> list[Automation]:
        """Get automations associated with an area."""
        all_a = await self.get_all_automations()
        areas = await self.hass.get_areas()
        area_id = None
        for a in areas:
            if a.get("name", "").lower() == area_name.lower():
                area_id = a.get("id")
                break
        if not area_id:
            return []
        # Filter by checking trigger entities
        result: list[Automation] = []
        for auto in all_a:
            if area_id in auto.config.get("trigger", []):
                result.append(auto)
        return result
