"""Home Assistant + Smart Home integration module.

Provides Home Assistant client (WebSocket + REST), device management,
scene management, automation control, and energy monitoring.
"""

from __future__ import annotations

from core.smarthome.hass import HomeAssistantClient, HomeAssistantConfig
from core.smarthome.devices import DevicesClient
from core.smarthome.scenes import ScenesClient
from core.smarthome.automation import AutomationsClient
from core.smarthome.energy import EnergyClient

__all__ = [
    "HomeAssistantClient",
    "HomeAssistantConfig",
    "DevicesClient",
    "ScenesClient",
    "AutomationsClient",
    "EnergyClient",
]
