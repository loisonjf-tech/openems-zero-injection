"""Diagnostics support for OpenEMS Zero Injection."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_DTU_HOST,
    CONF_DTU_PORT,
    CONF_GRID_POWER_ENTITY_ID,
    CONF_GRID_POWER_INVERTED,
    DEFAULT_DEVICE_ID,
    DEFAULT_GRID_POWER_ENTITY_ID,
    DEFAULT_GRID_POWER_INVERTED,
    DOMAIN,
    VERSION,
)
from .coordinator import DtuProSCoordinator
from .controller import display_label
from .registers import (
    PORT_PERMANENT_POWER_LIMIT_REGISTERS,
    PORT_TEMPORARY_POWER_LIMIT_REGISTERS,
)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return non-sensitive connection diagnostics."""
    coordinator: DtuProSCoordinator = hass.data[DOMAIN][entry.entry_id]
    data = coordinator.data
    controller = coordinator.controller
    power_limit_addresses = (
        *PORT_TEMPORARY_POWER_LIMIT_REGISTERS.values(),
        *PORT_PERMANENT_POWER_LIMIT_REGISTERS.values(),
    )
    power_limit_health = {
        f"0x{address:04X}": coordinator.power_limit_health(address)
        for address in power_limit_addresses
    }
    telemetry_health = {
        field: coordinator.measurement_health(field)
        for field in (
            "serial_number",
            "inverter_count",
            "meter_count",
            "total_energy_wh",
            "daily_energy_wh",
            "active_power_w",
            "reactive_power_var",
        )
    }
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
            **coordinator.connection_diagnostics(),
        },
        "manual_writes_enabled": coordinator.manual_writes_enabled,
        "controller": {
            "mode": controller.mode.value,
            "state": controller.status.state,
            "grid_power_entity_id": entry.options.get(
                CONF_GRID_POWER_ENTITY_ID, DEFAULT_GRID_POWER_ENTITY_ID
            ),
            "grid_power_inverted": entry.options.get(
                CONF_GRID_POWER_INVERTED, DEFAULT_GRID_POWER_INVERTED
            ),
            "scheduler_state": controller.scheduler.state.value,
            "next_command_allowed_in_seconds": controller.scheduler.remaining_seconds(),
            "last_error": controller.status.last_error,
            "last_decision_code": controller.status.last_decision,
            "last_decision_label": display_label(controller.status.last_decision),
            "last_decision_sequence": controller.last_decision_sequence,
            "last_command_sequence": controller.last_command_sequence,
            "real_dtu_limit": controller.status.real_dtu_limit_percent,
            "current_recommended_limit": controller.simulated_current_limit,
            "next_proposed_limit": controller.status.calculated_limit_percent,
            "waiting_state": controller.waiting_state,
            "installed_nominal_power_w": controller.installed_nominal_power_w,
            "watts_per_percent": controller.watts_per_percent,
            "installed_power_source": controller.installed_power_source,
            "installed_power_updated_at": (
                controller.installed_power_updated_at.isoformat()
                if controller.installed_power_updated_at
                else None
            ),
            "previous_installed_nominal_power_w": (
                controller.previous_installed_nominal_power_w
            ),
            "simulated_current_limit": controller.simulated_current_limit,
            "last_simulated_limit": controller.last_simulated_limit,
            "last_simulated_command_time": (
                controller.last_simulated_command_time.isoformat()
                if controller.last_simulated_command_time
                else None
            ),
            "temporary_limits_ready": coordinator.temporary_limits_ready,
            "temporary_limits_fresh": coordinator.temporary_limits_fresh,
            "counters": {
                "decisions_evaluated_since_start": controller.decisions_evaluated,
                "commands_sent": controller.commands_sent,
                "commands_succeeded": controller.commands_succeeded,
                "commands_failed": controller.commands_failed,
                "commands_simulated": controller.commands_simulated,
                "blocked_stabilization": controller.decisions_blocked_stabilization,
                "limit_unchanged": controller.decisions_limit_unchanged,
                "within_deadband": controller.decisions_within_deadband,
            },
            "recent_decisions": controller.history.latest_records(),
        },
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
            "power_limit_health": power_limit_health,
            "unavailable_power_limit_registers": [
                address
                for address, health in power_limit_health.items()
                if not health["available"]
            ],
            "telemetry_health": telemetry_health,
            "stale_telemetry_registers": [
                field for field, health in telemetry_health.items() if not health["available"]
            ],
        },
    }
