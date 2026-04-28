"""Home Assistant device management.

Provides device discovery, filtering, control, and information queries.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from core.smarthome.hass import (
    EntityCategory,
    EntityState,
    HomeAssistantClient,
    HAState,
)

logger = logging.getLogger(__name__)


@dataclass
class Device:
    """Home Assistant device representation."""

    device_id: str
    name: str
    area_id: str = ""
    area_name: str = ""
    floor_id: str = ""
    floor_name: str = ""
    manufacturer: str = ""
    model: str = ""
    model_url: str = ""
    hw_version: str = ""
    sw_version: str = ""
    sw_version_hard: str = ""
    sw_version_soft: str = ""
    configuration_url: str = ""
    config_entries: list[str] = field(default_factory=list)
    identifiers: list[str] = field(default_factory=list)
    connections: list[tuple[str, str]] = field(default_factory=list)
    via_device: str = ""
    primary_config_entry: str = ""
    disabled_by: str = ""
    entry_type: str = ""
    is_enabled: bool = True
    is_new: bool = False
    labels: list[str] = field(default_factory=list)
    suggested_area: str = ""
    serial_number: str = ""


@dataclass
class Area:
    """Home Assistant area representation."""

    area_id: str
    name: str
    picture: str = ""
    floor_id: str = ""
    icon: str = ""
    aliases: list[str] = field(default_factory=list)


class DevicesClient:
    """Manage Home Assistant devices and entities.

    Provides device discovery, filtering, and control.
    Requires a HomeAssistantClient instance.
    """

    def __init__(self, hass: HomeAssistantClient) -> None:
        self.hass = hass

    async def get_all_devices(
        self, area_id: str | None = None
    ) -> list[Device]:
        """Get all devices, optionally filtered by area.

        Args:
            area_id: Filter by area ID.

        Returns:
            List of Device objects.
        """
        raw_devices = await self.hass.get_devices(area_id)
        return [
            Device(
                device_id=d.get("id", ""),
                name=d.get("name_by_user", d.get("name", "")),
                area_id=d.get("area_id", ""),
                area_name=d.get("area_name", ""),
                floor_id=d.get("floor_id", ""),
                manufacturer=d.get("manufacturer", ""),
                model=d.get("model", ""),
                hw_version=d.get("hw_version", ""),
                sw_version=d.get("sw_version", ""),
                configuration_url=d.get("configuration_url", ""),
                config_entries=d.get("config_entries", []),
                identifiers=d.get("identifiers", []),
                connections=d.get("connections", []),
                via_device=d.get("via_device", ""),
                primary_config_entry=d.get("primary_config_entry", ""),
                disabled_by=d.get("disabled_by", ""),
                entry_type=d.get("entry_type", ""),
                is_enabled=d.get("disabled_by") is None,
                labels=d.get("labels", []),
                suggested_area=d.get("suggested_area", ""),
                serial_number=d.get("serial_number", ""),
            )
            for d in raw_devices
        ]

    async def get_device_by_id(self, device_id: str) -> Device | None:
        """Get a specific device by ID."""
        raw = await self.hass.get_devices()
        for d in raw:
            if d.get("id") == device_id:
                return Device(
                    device_id=d.get("id", ""),
                    name=d.get("name_by_user", d.get("name", "")),
                    area_id=d.get("area_id", ""),
                    area_name=d.get("area_name", ""),
                    manufacturer=d.get("manufacturer", ""),
                    model=d.get("model", ""),
                    hw_version=d.get("hw_version", ""),
                    sw_version=d.get("sw_version", ""),
                    config_entries=d.get("config_entries", []),
                    identifiers=d.get("identifiers", []),
                    connections=d.get("connections", []),
                    disabled_by=d.get("disabled_by", ""),
                    is_enabled=d.get("disabled_by") is None,
                    labels=d.get("labels", []),
                )
        return None

    async def get_entities_by_device(
        self, device_id: str
    ) -> list[EntityState]:
        """Get all entities associated with a device."""
        states = await self.hass.get_all_states()
        result: list[EntityState] = []
        for entity_id, state in states.items():
            # Check if entity belongs to device via config_entries
            if device_id in state.attributes.get("device_id", []):
                result.append(state)
        return result

    async def get_entities_by_area(
        self, area_id: str
    ) -> list[EntityState]:
        """Get all entities in a specific area."""
        states = await self.hass.get_all_states()
        result: list[EntityState] = []
        for entity_id, state in states.items():
            if state.attributes.get("device_id") in [
                d.get("id")
                for d in await self.hass.get_devices(area_id=area_id)
            ]:
                result.append(state)
        return result

    async def get_entities_by_domain(
        self, domain: str
    ) -> list[EntityState]:
        """Get all entities of a specific domain (light, switch, sensor, etc.)."""
        states = await self.hass.get_all_states()
        result: list[EntityState] = []
        for entity_id, state in states.items():
            if entity_id.startswith(f"{domain}."):
                result.append(state)
        return result

    async def get_entities_by_area_name(
        self, area_name: str
    ) -> list[EntityState]:
        """Get all entities by area name."""
        areas = await self.hass.get_areas()
        target_area = None
        for a in areas:
            if a.get("name", "").lower() == area_name.lower():
                target_area = a.get("id")
                break
        if not target_area:
            return []
        return await self.get_entities_by_area(target_area)

    async def get_areas(self) -> list[Area]:
        """Get all areas in Home Assistant."""
        raw = await self.hass.get_areas()
        return [
            Area(
                area_id=a.get("id", ""),
                name=a.get("name", ""),
                picture=a.get("picture", ""),
                floor_id=a.get("floor_id", ""),
                icon=a.get("icon", ""),
                aliases=a.get("aliases", []),
            )
            for a in raw
        ]

    async def get_floors(self) -> list[dict[str, Any]]:
        """Get all floors."""
        return await self.hass.get_floors()

    async def get_entities_by_domain(
        self, domain: str
    ) -> list[EntityState]:
        """Get all entities of a specific domain."""
        states = await self.hass.get_all_states()
        return [
            state
            for entity_id, state in states.items()
            if entity_id.startswith(f"{domain}.")
        ]

    async def get_entity_domain(self, entity_id: str) -> str:
        """Get the domain of an entity (e.g., 'light', 'switch')."""
        parts = entity_id.split(".")
        return parts[0] if len(parts) >= 2 else ""

    async def turn_on(self, entity_id: str) -> bool:
        """Turn on a light, switch, or other entity."""
        domain = await self.get_entity_domain(entity_id)
        return await self.hass.call_service(domain, "turn_on", {"entity_id": entity_id})

    async def turn_off(self, entity_id: str) -> bool:
        """Turn off a light, switch, or other entity."""
        domain = await self.get_entity_domain(entity_id)
        return await self.hass.call_service(domain, "turn_off", {"entity_id": entity_id})

    async def toggle(self, entity_id: str) -> bool:
        """Toggle a light, switch, or other entity."""
        domain = await self.get_entity_domain(entity_id)
        return await self.hass.call_service(domain, "toggle", {"entity_id": entity_id})

    async def set_brightness(self, entity_id: str, brightness: int) -> bool:
        """Set brightness of a light (0-255)."""
        return await self.hass.call_service(
            "light",
            "turn_on",
            {"entity_id": entity_id, "brightness": brightness},
        )

    async def set_color_temp(
        self, entity_id: str, color_temp: int
    ) -> bool:
        """Set color temperature in mired (153-500)."""
        return await self.hass.call_service(
            "light",
            "turn_on",
            {"entity_id": entity_id, "color_temp": color_temp},
        )

    async def set_rgb_color(
        self, entity_id: str, r: int, g: int, b: int
    ) -> bool:
        """Set RGB color (0-255 each)."""
        return await self.hass.call_service(
            "light",
            "turn_on",
            {"entity_id": entity_id, "rgb_color": [r, g, b]},
        )

    async def set_volume(self, entity_id: str, volume: float) -> bool:
        """Set volume on media player (0.0-1.0)."""
        return await self.hass.call_service(
            "media_player",
            "volume_set",
            {"entity_id": entity_id, "volume_level": volume},
        )

    async def set_climate_temperature(
        self, entity_id: str, temperature: float
    ) -> bool:
        """Set target temperature on climate entity."""
        return await self.hass.call_service(
            "climate",
            "set_temperature",
            {"entity_id": entity_id, "temperature": temperature},
        )

    async def set_climate_hvac_mode(
        self, entity_id: str, mode: str
    ) -> bool:
        """Set HVAC mode (heat, cool, auto, off, dry, fan)."""
        return await self.hass.call_service(
            "climate",
            "set_hvac_mode",
            {"entity_id": entity_id, "hvac_mode": mode},
        )

    async def set_fan_speed(
        self, entity_id: str, speed: str
    ) -> bool:
        """Set fan speed."""
        return await self.hass.call_service(
            "fan",
            "set_speed",
            {"entity_id": entity_id, "percentage": speed},
        )

    async def open_cover(self, entity_id: str) -> bool:
        """Open a cover (blind, curtain, garage door)."""
        return await self.hass.call_service(
            "cover", "open_cover", {"entity_id": entity_id}
        )

    async def close_cover(self, entity_id: str) -> bool:
        """Close a cover."""
        return await self.hass.call_service(
            "cover", "close_cover", {"entity_id": entity_id}
        )

    async def stop_cover(self, entity_id: str) -> bool:
        """Stop a cover in its current position."""
        return await self.hass.call_service(
            "cover", "stop_cover", {"entity_id": entity_id}
        )

    async def set_cover_position(self, entity_id: str, position: int) -> bool:
        """Set cover position (0-100)."""
        return await self.hass.call_service(
            "cover",
            "set_cover_position",
            {"entity_id": entity_id, "position": position},
        )

    async def lock(self, entity_id: str) -> bool:
        """Lock a lock entity."""
        return await self.hass.call_service(
            "lock", "lock", {"entity_id": entity_id}
        )

    async def unlock(self, entity_id: str) -> bool:
        """Unlock a lock entity."""
        return await self.hass.call_service(
            "lock", "unlock", {"entity_id": entity_id}
        )

    async def press_button(self, entity_id: str) -> bool:
        """Press a button entity."""
        return await self.hass.call_service(
            "button", "press", {"entity_id": entity_id}
        )

    async def set_input_boolean(
        self, entity_id: str, state: str = "on"
    ) -> bool:
        """Set input_boolean state."""
        return await self.hass.call_service(
            "input_boolean",
            "turn_" + state,
            {"entity_id": entity_id},
        )

    async def set_input_number(
        self, entity_id: str, value: float
    ) -> bool:
        """Set input_number value."""
        return await self.hass.call_service(
            "input_number",
            "set_value",
            {"entity_id": entity_id, "value": value},
        )

    async def set_input_select(
        self, entity_id: str, option: str
    ) -> bool:
        """Set input_select option."""
        return await self.hass.call_service(
            "input_select",
            "select_option",
            {"entity_id": entity_id, "option": option},
        )

    async def play_media(
        self,
        entity_id: str,
        media_content_id: str,
        media_content_type: str = "music",
    ) -> bool:
        """Play media on a media player."""
        return await self.hass.call_service(
            "media_player",
            "play_media",
            {
                "entity_id": entity_id,
                "media_content_id": media_content_id,
                "media_content_type": media_content_type,
            },
        )

    async def media_control(
        self, entity_id: str, command: str
    ) -> bool:
        """Send media control command (play, pause, next, previous, etc.)."""
        return await self.hass.call_service(
            "media_player",
            command,
            {"entity_id": entity_id},
        )

    async def set_alarm_panel_mode(self, entity_id: str, mode: str) -> bool:
        """Set alarm panel mode (arm_home, arm_away, arm_night, disarmed)."""
        return await self.hass.call_service(
            "alarm_control_panel",
            "alarm_disarm" if mode == "disarmed" else f"alarm_{mode}",
            {"entity_id": entity_id},
        )

    async def send_command(
        self, entity_id: str, command: str, data: dict | None = None
    ) -> bool:
        """Send a command to a generic media_player or climate entity."""
        return await self.hass.call_service(
            "media_player",
            "play_media" if "media" in command.lower() else "turn_on",
            {"entity_id": entity_id, **data} if data else {"entity_id": entity_id},
        )

    async def get_temperature(self, entity_id: str) -> float | None:
        """Get current temperature from a climate or sensor entity."""
        state = await self.hass.get_state(entity_id)
        if state:
            return state.temperature
        return None

    async def get_humidity(self, entity_id: str) -> float | None:
        """Get current humidity from a sensor entity."""
        state = await self.hass.get_state(entity_id)
        if state:
            return state.humidity
        return None

    async def get_battery_level(self, entity_id: str) -> int | None:
        """Get battery level from a sensor entity."""
        state = await self.hass.get_state(entity_id)
        if state:
            batt = state.attributes.get("battery_level")
            if batt is not None:
                return int(batt)
        return None

    async def get_co2_level(self, entity_id: str) -> float | None:
        """Get CO2 level from a sensor entity."""
        state = await self.hass.get_state(entity_id)
        if state:
            co2 = state.attributes.get("carbon_dioxide")
            if co2 is not None:
                return float(co2)
        return None

    async def get_pm25(self, entity_id: str) -> float | None:
        """Get PM2.5 level from a sensor entity."""
        state = await self.hass.get_state(entity_id)
        if state:
            pm25 = state.attributes.get("pm25")
            if pm25 is not None:
                return float(pm25)
        return None

    async def get_air_quality(self, entity_id: str) -> str | None:
        """Get air quality index from a sensor entity."""
        state = await self.hass.get_state(entity_id)
        if state:
            aqi = state.attributes.get("aqi")
            if aqi is not None:
                return str(aqi)
        return None

    async def get_power(self, entity_id: str) -> float | None:
        """Get current power consumption."""
        state = await self.hass.get_state(entity_id)
        if state:
            power = state.attributes.get("power")
            if power is not None:
                return float(power)
        return None

    async def get_energy(self, entity_id: str) -> float | None:
        """Get current energy reading."""
        state = await self.hass.get_state(entity_id)
        if state:
            energy = state.attributes.get("energy")
            if energy is not None:
                return float(energy)
        return None

    async def get_gas(self, entity_id: str) -> float | None:
        """Get current gas consumption."""
        state = await self.hass.get_state(entity_id)
        if state:
            gas = state.attributes.get("gas")
            if gas is not None:
                return float(gas)
        return None

    async def get_water(self, entity_id: str) -> float | None:
        """Get current water consumption."""
        state = await self.hass.get_state(entity_id)
        if state:
            water = state.attributes.get("water")
            if water is not None:
                return float(water)
        return None

    async def get_electrical(self, entity_id: str) -> dict[str, float] | None:
        """Get electrical readings (voltage, current, power)."""
        state = await self.hass.get_state(entity_id)
        if state:
            voltage = state.attributes.get("voltage")
            current = state.attributes.get("current")
            power = state.attributes.get("power")
            result: dict[str, float] = {}
            if voltage is not None:
                result["voltage"] = float(voltage)
            if current is not None:
                result["current"] = float(current)
            if power is not None:
                result["power"] = float(power)
            return result
        return None

    async def get_gas_consumption(self, entity_id: str) -> float | None:
        """Get gas consumption."""
        state = await self.hass.get_state(entity_id)
        if state:
            gas = state.attributes.get("gas")
            if gas is not None:
                return float(gas)
        return None

    async def get_water_consumption(self, entity_id: str) -> float | None:
        """Get water consumption."""
        state = await self.hass.get_state(entity_id)
        if state:
            water = state.attributes.get("water")
            if water is not None:
                return float(water)
        return None

    async def get_electrical_readings(self, entity_id: str) -> dict[str, float] | None:
        """Get electrical readings (voltage, current, power)."""
        state = await self.hass.get_state(entity_id)
        if state:
            result: dict[str, float] = {}
            voltage = state.attributes.get("voltage")
            current = state.attributes.get("current")
            power = state.attributes.get("power")
            if voltage is not None:
                result["voltage"] = float(voltage)
            if current is not None:
                result["current"] = float(current)
            if power is not None:
                result["power"] = float(power)
            return result if result else None
        return None
