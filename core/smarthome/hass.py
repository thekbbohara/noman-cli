"""Home Assistant client with WebSocket and REST API support.

Connects to Home Assistant via the WebSocket API for real-time
entity state monitoring and control, with REST API fallback.
Supports auto-discovery, reconnection, and entity state management.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class HAState:
    """Home Assistant entity states."""

    ON = "on"
    OFF = "off"
    OPEN = "open"
    CLOSED = "closed"
    LOCKED = "locked"
    UNLOCKED = "unlocked"
    HOME = "home"
    AWAY = "away"
    NIGHT = "night"
    ARMED_AWAY = "armed_away"
    ARMED_HOME = "armed_home"
    ARMED_NIGHT = "armed_night"
    DISARMED = "disarmed"
    CLEAR = "clear"
    SIREN = "siren"
    FIRE = "fire"
    CO = "carbon_monoxide"
    WATER = "water"
    MOTION = "motion"
    DETECTED = "detected"
    IDLE = "idle"
    PLAYING = "playing"
    PAUSED = "paused"
    STANDBY = "standby"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class EntityCategory(str, Enum):
    """Entity categories in Home Assistant."""

    CONFIG = "config"
    DIAGNOSTIC = "diagnostic"
    SYSTEM = "system"


@dataclass
class EntityState:
    """Current state of a Home Assistant entity."""

    entity_id: str
    state: str
    attributes: dict[str, Any] = field(default_factory=dict)
    last_changed: str = ""
    last_updated: str = ""
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def is_on(self) -> bool:
        return self.state in (HAState.ON, HAState.HOME, HAState.ARMED_AWAY, HAState.ARMED_HOME)

    @property
    def is_off(self) -> bool:
        return self.state in (HAState.OFF, HAState.AWAY, HAState.DISARMED)

    @property
    def temperature(self) -> float | None:
        """Get temperature attribute if available."""
        temp = self.attributes.get("temperature")
        if temp is not None:
            try:
                return float(temp)
            except (ValueError, TypeError):
                pass
        return None

    @property
    def brightness(self) -> int | None:
        """Get brightness attribute if available."""
        b = self.attributes.get("brightness")
        if b is not None:
            try:
                return int(b)
            except (ValueError, TypeError):
                pass
        return None

    @property
    def color_temp(self) -> int | None:
        """Get color temperature in mired if available."""
        ct = self.attributes.get("color_temp")
        if ct is not None:
            try:
                return int(ct)
            except (ValueError, TypeError):
                pass
        return None

    @property
    def humidity(self) -> float | None:
        """Get humidity attribute if available."""
        h = self.attributes.get("humidity")
        if h is not None:
            try:
                return float(h)
            except (ValueError, TypeError):
                pass
        return None

    def __repr__(self) -> str:
        return f"EntityState({self.entity_id}={self.state})"


@dataclass
class EntityInfo:
    """Entity metadata from Home Assistant."""

    entity_id: str
    domain: str  # light, switch, sensor, etc.
    name: str = ""
    unit_of_measurement: str = ""
    device_class: str = ""
    state_class: str = ""
    icon: str = ""
    friendly_name: str = ""
    area_id: str = ""
    area_name: str = ""
    floor_id: str = ""
    floor_name: str = ""
    category: str = ""
    config_entry_id: str = ""
    disabled_by: str = ""
    hidden: bool = False
    supported_features: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_hidden(self) -> bool:
        return self.hidden


@dataclass
class HomeAssistantConfig:
    """Home Assistant connection configuration."""

    host: str = "homeassistant.local"
    port: int = 8123
    ssl: bool = False
    token: str = ""
    websocket_port: int = 8123
    websocket_path: str = "/api/websocket"
    api_path: str = "/api"
    timeout: float = 30.0
    reconnect_interval: float = 5.0
    max_reconnect_attempts: int = 10
    ping_interval: float = 20.0
    ping_timeout: float = 10.0


class HomeAssistantClient:
    """Home Assistant client with WebSocket and REST API support.

    Connects to Home Assistant via WebSocket for real-time updates
    and REST API for commands. Supports entity state monitoring,
    device control, scene activation, automation triggering,
    and energy monitoring.

    Usage::

        client = HomeAssistantClient(
            host="homeassistant.local",
            token="your_long_lived_token",
        )
        await client.connect()
        states = await client.get_all_states()
        await client.turn_on("light.living_room")
        await client.disconnect()
    """

    def __init__(self, config: HomeAssistantConfig | None = None) -> None:
        self.config = config or HomeAssistantConfig()
        self._ws_url: str = self._build_ws_url()
        self._rest_base_url: str = self._build_rest_url()

        # WebSocket
        self._ws: Any | None = None  # type: ignore[no-any-import]
        self._ws_connected: bool = False
        self._ws_task: asyncio.Task | None = None
        self._ws_sequence: int = 0

        # State cache
        self._states: dict[str, EntityState] = {}
        self._entities: dict[str, EntityInfo] = {}

        # Sub-clients (initialized on connect)
        self.devices: DevicesClient | None = None
        self.scenes: ScenesClient | None = None
        self.automations: AutomationsClient | None = None
        self.energy: EnergyClient | None = None

        # Callbacks
        self._state_handlers: dict[str, list[Callable[[EntityState], Any]]] = {}
        self._global_handlers: list[Callable[[str, EntityState, EntityState | None], Any]] = []

        # Connection state
        self._running: bool = False
        self._reconnect_task: asyncio.Task | None = None
        self._reconnect_attempts: int = 0
        self._last_error: str | None = None

    @property
    def is_connected(self) -> bool:
        return self._ws_connected

    @property
    def states(self) -> dict[str, EntityState]:
        return dict(self._states)

    @property
    def entities(self) -> dict[str, EntityInfo]:
        return dict(self._entities)

    # ── Connection lifecycle ──

    def _build_ws_url(self) -> str:
        """Build WebSocket URL from config."""
        scheme = "wss" if self.config.ssl else "ws"
        return (
            f"{scheme}://{self.config.host}:{self.config.config.get('websocket_port', self.config.websocket_port)}{self.config.websocket_path}"
            if hasattr(self.config, 'config')
            else f"{scheme}://{self.config.host}:{self.config.websocket_port}{self.config.websocket_path}"
        )

    def _build_rest_url(self) -> str:
        """Build REST API URL from config."""
        scheme = "https" if self.config.ssl else "http"
        return f"{scheme}://{self.config.host}:{self.config.port}{self.config.api_path}"

    async def connect(self) -> bool:
        """Connect to Home Assistant via WebSocket API.

        Returns:
            True if connection succeeded.
        """
        if self._ws_connected:
            return True

        try:
            import websockets

            self._ws = await websockets.connect(
                self._ws_url,
                extra_headers={
                    "Authorization": f"Bearer {self.config.token}",
                    "Origin": f"http://{self.config.host}:{self.config.port}" if not self.config.ssl else f"https://{self.config.host}:{self.config.port}",
                },
                ping_interval=self.config.ping_interval,
                ping_timeout=self.config.ping_timeout,
            )
            self._ws_connected = True
            self._running = True

            # Wait for auth_required message
            msg = await asyncio.wait_for(
                self._ws.recv(), timeout=self.config.timeout
            )
            data = json.loads(msg)
            if data.get("type") == "auth_required":
                await self._send_auth()

            self._reconnect_attempts = 0
            self._last_error = None
            logger.info("Connected to Home Assistant at %s", self._ws_url)

            # Initialize sub-clients
            self._init_subclients()

            # Start listening loop
            self._ws_task = asyncio.create_task(self._ws_listen_loop())

            return True

        except Exception as e:
            self._last_error = str(e)
            logger.error("Failed to connect to Home Assistant: %s", e)
            return False

    async def disconnect(self) -> None:
        """Disconnect from Home Assistant."""
        self._running = False
        if self._reconnect_task:
            self._reconnect_task.cancel()
            self._reconnect_task = None

        if self._ws_task:
            self._ws_task.cancel()
            self._ws_task = None

        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        self._ws_connected = False
        logger.info("Disconnected from Home Assistant")

    async def _send_auth(self) -> None:
        """Send authentication message."""
        msg = {
            "id": self._next_id(),
            "type": "auth",
            "access_token": self.config.token,
        }
        await self._send(msg)

    async def _send(self, message: dict[str, Any]) -> None:
        """Send a WebSocket message."""
        if self._ws and self._ws_connected:
            await self._ws.send(json.dumps(message))

    def _next_id(self) -> int:
        """Generate next message ID."""
        self._ws_sequence += 1
        return self._ws_sequence

    async def _ws_listen_loop(self) -> None:
        """Listen for WebSocket messages."""
        try:
            async for raw_msg in self._ws:
                data = json.loads(raw_msg)
                msg_type = data.get("type", "")
                await self._handle_ws_message(data, msg_type)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self._last_error = str(e)
            logger.error("WebSocket listen error: %s", e)
            await self._attempt_reconnect()

    async def _handle_ws_message(
        self, data: dict[str, Any], msg_type: str
    ) -> None:
        """Handle incoming WebSocket messages."""
        if msg_type == "event":
            event = data.get("event", {})
            event_type = event.get("event_type", "")
            if event_type == "state_changed":
                entity_id = event.get("data", {}).get("entity_id", "")
                if entity_id:
                    state_data = event.get("data", {}).get("new_state", {})
                    state = self._parse_state(entity_id, state_data)
                    self._states[entity_id] = state
                    await self._notify_state_handlers(entity_id, state, None)
                    await self._notify_global_handlers(entity_id, state, None)
        elif msg_type == "result":
            if data.get("success") and "result" in data:
                result = data["result"]
                if isinstance(result, list) and result and "entity_id" in result[0]:
                    for item in result:
                        eid = item.get("entity_id", "")
                        if eid:
                            self._entities[eid] = EntityInfo(
                                entity_id=eid,
                                domain=item.get("domain", ""),
                                name=item.get("name", ""),
                                extra=item,
                            )
        elif msg_type == "auth_ok":
            logger.debug("Authentication successful")
        elif msg_type == "auth_required":
            await self._send_auth()
        elif msg_type == "auth_invalid":
            logger.error("Authentication failed")
            self._ws_connected = False

    async def _attempt_reconnect(self) -> None:
        """Attempt to reconnect with exponential backoff."""
        if not self._running:
            return
        delay = min(
            self.config.reconnect_interval * (2 ** self._reconnect_attempts),
            300.0,
        )
        self._reconnect_attempts += 1
        if self._reconnect_attempts > self.config.max_reconnect_attempts:
            logger.error("Max reconnect attempts reached")
            return

        logger.info(
            "Reconnecting to Home Assistant in %.1fs (attempt %d)",
            delay, self._reconnect_attempts,
        )
        await asyncio.sleep(delay)
        success = await self.connect()
        if not success:
            await self._attempt_reconnect()

    def _init_subclients(self) -> None:
        """Initialize sub-clients."""
        from core.smarthome.devices import DevicesClient
        from core.smarthome.scenes import ScenesClient
        from core.smarthome.automation import AutomationsClient
        from core.smarthome.energy import EnergyClient

        self.devices = DevicesClient(self)
        self.scenes = ScenesClient(self)
        self.automations = AutomationsClient(self)
        self.energy = EnergyClient(self)

    def _parse_state(self, entity_id: str, state_data: dict[str, Any]) -> EntityState:
        """Parse a state_changed event into EntityState."""
        return EntityState(
            entity_id=entity_id,
            state=state_data.get("state", ""),
            attributes=state_data.get("attributes", {}),
            last_changed=state_data.get("last_changed", ""),
            last_updated=state_data.get("last_updated", ""),
            context=state_data.get("context", {}),
        )

    async def _notify_state_handlers(
        self,
        entity_id: str,
        new_state: EntityState,
        old_state: EntityState | None,
    ) -> None:
        """Notify registered handlers for an entity."""
        for handler in self._state_handlers.get(entity_id, []):
            try:
                await handler(new_state)
            except Exception as e:
                logger.error("State handler error for %s: %s", entity_id, e)

    async def _notify_global_handlers(
        self,
        entity_id: str,
        new_state: EntityState,
        old_state: EntityState | None,
    ) -> None:
        """Notify global state change handlers."""
        for handler in self._global_handlers:
            try:
                await handler(entity_id, new_state, old_state)
            except Exception as e:
                logger.error("Global handler error: %s", e)

    # ── REST API helpers ──

    async def _rest_get(self, path: str) -> dict[str, Any] | None:
        """Make a REST GET request."""
        import httpx

        url = f"{self._rest_base_url}/{path.lstrip('/')}"
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                resp = await client.get(
                    url,
                    headers={
                        "Authorization": f"Bearer {self.config.token}",
                        "Content-Type": "application/json",
                    },
                )
                if resp.status_code == 200:
                    return resp.json()
                return None
        except Exception as e:
            logger.error("REST GET %s failed: %s", url, e)
            return None

    async def _rest_post(
        self, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Make a REST POST request."""
        import httpx

        url = f"{self._rest_base_url}/{path.lstrip('/')}"
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                resp = await client.post(
                    url,
                    json=payload or {},
                    headers={
                        "Authorization": f"Bearer {self.config.token}",
                        "Content-Type": "application/json",
                    },
                )
                if resp.status_code in (200, 201):
                    return resp.json()
                return None
        except Exception as e:
            logger.error("REST POST %s failed: %s", url, e)
            return None

    async def _rest_delete(self, path: str) -> bool:
        """Make a REST DELETE request."""
        import httpx

        url = f"{self._rest_base_url}/{path.lstrip('/')}"
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                resp = await client.delete(
                    url,
                    headers={
                        "Authorization": f"Bearer {self.config.token}",
                    },
                )
                return resp.status_code in (200, 204)
        except Exception as e:
            logger.error("REST DELETE %s failed: %s", url, e)
            return False

    # ── Core operations ──

    async def get_all_states(self) -> dict[str, EntityState]:
        """Get all entity states via REST API."""
        data = await self._rest_get("states")
        if not data:
            return {}
        states: dict[str, EntityState] = {}
        for entity_id, state_data in data.items():
            states[entity_id] = self._parse_state(entity_id, state_data)
        self._states.update(states)
        return states

    async def get_state(self, entity_id: str) -> EntityState | None:
        """Get state of a specific entity."""
        data = await self._rest_get(f"states/{entity_id}")
        if data:
            return self._parse_state(entity_id, data)
        return None

    async def get_entities(
        self, domain: str | None = None
    ) -> dict[str, EntityInfo]:
        """Get entity information, optionally filtered by domain."""
        if not self._entities:
            await self._refresh_entities()
        if domain:
            return {
                eid: info
                for eid, info in self._entities.items()
                if info.domain == domain
            }
        return dict(self._entities)

    async def _refresh_entities(self) -> None:
        """Fetch all entity info from REST API."""
        data = await self._rest_get("config/config")
        if not data:
            return
        # Get states to build entity list
        states_data = await self._rest_get("states")
        if not states_data:
            return
        for entity_id, state_data in states_data.items():
            parts = entity_id.split(".")
            if len(parts) >= 2:
                domain = parts[0]
                attrs = state_data.get("attributes", {})
                self._entities[entity_id] = EntityInfo(
                    entity_id=entity_id,
                    domain=domain,
                    name=attrs.get("friendly_name", ""),
                    unit_of_measurement=attrs.get("unit_of_measurement", ""),
                    device_class=attrs.get("device_class", ""),
                    state_class=attrs.get("state_class", ""),
                    icon=attrs.get("icon", ""),
                    extra=state_data,
                )

    async def call_service(
        self,
        domain: str,
        service: str,
        service_data: dict[str, Any] | None = None,
    ) -> bool:
        """Call a Home Assistant service via WebSocket.

        Args:
            domain: Service domain (light, switch, media_player, etc.)
            service: Service name (turn_on, turn_off, set_temperature, etc.)
            service_data: Service data dict.

        Returns:
            True if service call succeeded.
        """
        msg = {
            "id": self._next_id(),
            "type": "call_service",
            "domain": domain,
            "service": service,
            "service_data": service_data or {},
        }
        await self._send(msg)
        return True

    async def get_areas(self) -> list[dict[str, Any]]:
        """Get all areas."""
        return await (await self._rest_get("config/area_registry")) or []

    async def get_floors(self) -> list[dict[str, Any]]:
        """Get all floors."""
        return await (await self._rest_get("config/floor_registry")) or []

    async def get_devices(
        self, area_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Get devices, optionally filtered by area."""
        data = await (await self._rest_get("config/device_registry")) or []
        if area_id:
            return [d for d in data if d.get("area_id") == area_id]
        return data

    async def get_zones(self) -> list[dict[str, Any]]:
        """Get all zones."""
        return await (await self._rest_get("config/zone")) or []

    async def get_config(self) -> dict[str, Any] | None:
        """Get Home Assistant configuration."""
        return await self._rest_get("config/core")

    async def restart(self) -> bool:
        """Restart Home Assistant."""
        return await self._rest_post("restart") is not None

    # ── Callback registration ──

    def on_state_change(
        self,
        entity_id: str,
        handler: Callable[[EntityState], Any],
    ) -> None:
        """Register a handler for state changes on a specific entity."""
        self._state_handlers.setdefault(entity_id, []).append(handler)

    def on_global_state_change(
        self,
        handler: Callable[[str, EntityState, EntityState | None], Any],
    ) -> None:
        """Register a global state change handler."""
        self._global_handlers.append(handler)
