"""Home Assistant scene management.

Provides scene listing, activation, creation, and deletion.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from core.smarthome.hass import HomeAssistantClient

logger = logging.getLogger(__name__)


@dataclass
class Scene:
    """Home Assistant scene representation."""

    scene_id: str
    name: str
    icon: str = ""
    entities: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)
    description: str = ""

    @property
    def entity_count(self) -> int:
        return len(self.entities)

    @property
    def entity_ids(self) -> list[str]:
        return list(self.entities.keys())


class ScenesClient:
    """Manage Home Assistant scenes.

    Provides scene listing, activation, creation, and deletion.
    Requires a HomeAssistantClient instance.
    """

    def __init__(self, hass: HomeAssistantClient) -> None:
        self.hass = hass

    async def get_all_scenes(self) -> list[Scene]:
        """Get all scenes from Home Assistant."""
        data = await self.hass._rest_get("scene")
        if not data:
            return []
        return [
            Scene(
                scene_id=item.get("entity_id", ""),
                name=item.get("attributes", {}).get("friendly_name", ""),
                icon=item.get("attributes", {}).get("icon", ""),
                entities=item.get("attributes", {}).get("entity_id", {}),
                state=item.get("attributes", {}),
            )
            for item in data
        ]

    async def get_scene(self, scene_id: str) -> Scene | None:
        """Get a specific scene by ID."""
        data = await self.hass._rest_get(f"scene/{scene_id}")
        if data:
            return Scene(
                scene_id=data.get("entity_id", ""),
                name=data.get("attributes", {}).get("friendly_name", ""),
                icon=data.get("attributes", {}).get("icon", ""),
                entities=data.get("attributes", {}).get("entity_id", {}),
                state=data.get("attributes", {}),
            )
        return None

    async def activate(self, scene_id: str) -> bool:
        """Activate a scene.

        Args:
            scene_id: Scene entity ID (e.g., 'scene.movie_night').

        Returns:
            True if activation succeeded.
        """
        result = await self.hass._rest_post(
            "scene/turn_on",
            {"entity_id": scene_id},
        )
        return result is not None

    async def create(
        self,
        scene_id: str,
        name: str,
        entities: dict[str, Any],
        description: str = "",
    ) -> bool:
        """Create a new scene.

        Args:
            scene_id: Scene entity ID (e.g., 'scene.living_room').
            name: Display name.
            entities: Dict of entity_id -> state/attributes.
            description: Scene description.

        Returns:
            True if creation succeeded.
        """
        import httpx

        payload = {
            "id": scene_id.replace(".", "_"),
            "name": name,
            "entities": entities,
        }
        if description:
            payload["description"] = description

        result = await self.hass._rest_post(
            "scene/create",
            payload,
        )
        return result is not None

    async def delete(self, scene_id: str) -> bool:
        """Delete a scene.

        Args:
            scene_id: Scene entity ID.

        Returns:
            True if deletion succeeded.
        """
        return await self.hass._rest_delete(f"scene/{scene_id}")

    async def get_entity_states(self, scene_id: str) -> dict[str, Any]:
        """Get the entity states that a scene would set."""
        scene = await self.get_scene(scene_id)
        if scene:
            return scene.state
        return {}

    async def create_from_entities(
        self,
        scene_id: str,
        name: str,
        entity_ids: list[str],
        description: str = "",
    ) -> bool:
        """Create a scene from current entity states.

        Args:
            scene_id: Scene entity ID.
            name: Display name.
            entity_ids: List of entity IDs to include.
            description: Scene description.

        Returns:
            True if creation succeeded.
        """
        states = await self.hass.get_all_states()
        entities: dict[str, Any] = {}
        for eid in entity_ids:
            if eid in states:
                state = states[eid]
                attrs = state.attributes.copy()
                # Remove non-serializable attributes
                attrs.pop("friendly_name", None)
                attrs.pop("unit_of_measurement", None)
                entities[eid] = {
                    "state": state.state,
                    "attributes": attrs,
                }

        return await self.create(scene_id, name, entities, description)

    async def get_scenes_by_area(
        self, area_name: str
    ) -> list[Scene]:
        """Get scenes associated with an area."""
        all_scenes = await self.get_all_scenes()
        areas = await self.hass.get_areas()
        area_id = None
        for a in areas:
            if a.get("name", "").lower() == area_name.lower():
                area_id = a.get("id")
                break
        if not area_id:
            return []

        # Filter scenes by checking their entities' areas
        result: list[Scene] = []
        for scene in all_scenes:
            for eid in scene.entity_ids:
                state = await self.hass.get_state(eid)
                if state:
                    area = state.attributes.get("area_id")
                    if area == area_id:
                        result.append(scene)
                        break
        return result
