# Smart Home Reference

## Overview

NoMan integrates with Home Assistant for smart home control.

## CLI Commands

```bash
noman hass list              # List devices
noman hass control light.living on
noman hass control climate.thermostat set_temperature 22
noman hass scenes activate living_room
noman hass automations trigger morning_routine
noman hass energy today       # View energy data
```

## Features

- Device state monitoring
- Device control (on/off, temperature, etc.)
- Scene activation
- Automation triggering
- Energy monitoring
- Auto-discovery of devices
