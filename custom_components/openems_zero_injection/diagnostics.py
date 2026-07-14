"""Diagnostics support for OpenEMS Zero Injection."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_DTU_HOST, CONF_DTU_PORT, DOMAIN
from .coordinator import DtuProSCoordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return non-sensitive connection diagnostics."""
    coordinator: DtuProSCoordinator = hass.data[DOMAIN][entry.entry_id]
    return {
        "dtu_ip": entry.data[CONF_DTU_HOST],
        "port": entry.data[CONF_DTU_PORT],
        "connection": {
            "connected": coordinator.data.connected,
            "last_communication_error": coordinator.data.last_error,
        },
    }
