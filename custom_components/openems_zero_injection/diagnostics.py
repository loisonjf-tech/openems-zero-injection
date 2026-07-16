"""Diagnostics support for OpenEMS Zero Injection."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_DTU_HOST, CONF_DTU_PORT, DEFAULT_DEVICE_ID, DOMAIN, VERSION
from .coordinator import DtuProSCoordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return non-sensitive connection diagnostics."""
    coordinator: DtuProSCoordinator = hass.data[DOMAIN][entry.entry_id]
    data = coordinator.data
    return {
        "dtu_ip": entry.data[CONF_DTU_HOST],
        "port": entry.data[CONF_DTU_PORT],
        "device_id": DEFAULT_DEVICE_ID,
        "integration_version": VERSION,
        "connection": {
            "connected": data.connected if data else False,
            "last_communication_error": data.last_error if data else None,
            "last_success": data.last_success.isoformat() if data and data.last_success else None,
            "response_time_ms": data.response_time_ms if data else None,
        },
        "manual_writes_enabled": coordinator.manual_writes_enabled,
        "measurements": {
            "inverter_count": data.inverter_count if data else None,
            "meter_count": data.meter_count if data else None,
            "serial_number": "redacted" if data and data.serial_number else None,
            "power_limit_registers": {
                "port_1_temporary": data.port_1_temporary_power_limit_percent if data else None,
                "port_1_permanent": data.port_1_permanent_power_limit_percent if data else None,
                "port_2_temporary": data.port_2_temporary_power_limit_percent if data else None,
                "port_2_permanent": data.port_2_permanent_power_limit_percent if data else None,
                "port_3_temporary": data.port_3_temporary_power_limit_percent if data else None,
                "port_3_permanent": data.port_3_permanent_power_limit_percent if data else None,
            },
        },
    }
