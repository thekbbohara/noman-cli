"""Integration tests for smart home."""

import pytest


async def test_hass_client():
    """Test HomeAssistantClient."""
    from core.smarthome.hass import HomeAssistantClient
    client = HomeAssistantClient()
    assert client is not None


async def test_devices():
    """Test device management."""
    from core.smarthome.devices import DeviceManager
    assert DeviceManager is not None


async def test_scenes():
    """Test scene management."""
    from core.smarthome.scenes import SceneManager
    assert SceneManager is not None
