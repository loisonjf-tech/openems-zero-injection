"""Tests for OpenEMS Zero Injection diagnostics."""

from unittest.mock import AsyncMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.openems_zero_injection.const import (
    CONF_DTU_HOST,
    CONF_DTU_PORT,
    DOMAIN,
)
from custom_components.openems_zero_injection.diagnostics import (
    async_get_config_entry_diagnostics,
)


async def test_diagnostics_include_connection_state(hass) -> None:
    """Diagnostics expose the configured endpoint and connection state."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_DTU_HOST: "192.0.2.10", CONF_DTU_PORT: 502},
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.openems_zero_injection.coordinator.DtuProSModbusClient"
    ) as client_class:
        client_class.return_value.async_check_connectivity = AsyncMock(return_value=True)
        client_class.return_value.async_read_input_registers = AsyncMock(
            side_effect=lambda _address, count: [0] * count
        )
        client_class.return_value.async_read_power_limit_register = AsyncMock(
            return_value=50
        )
        client_class.return_value.connection_diagnostics.return_value = {
            "connected": True,
            "total_errors": 0,
            "consecutive_failures": 0,
            "last_error": None,
            "reconnections": 0,
        }
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["dtu_ip"] == "192.0.2.10"
    assert diagnostics["device_id"] == 1
    assert diagnostics["measurements"]["serial_number"] == "redacted"
    assert diagnostics["controller"]["temporary_limits_ready"] is True
    assert diagnostics["measurements"]["power_limit_health"]["0xD00D"]["available"] is True
    assert diagnostics["measurements"]["unavailable_power_limit_registers"] == []
    energy_manager = diagnostics["energy_manager"]
    assert energy_manager["battery_count"] == 0
    assert energy_manager["total_max_charge_power_w"] is None
    assert energy_manager["total_current_charge_power_w"] is None
    assert energy_manager["total_remaining_charge_power_w"] is None
    assert energy_manager["batteries"] == []
    assert diagnostics["trace_recorder"]["mode"] == "normal"
    assert diagnostics["trace_recorder"]["session_active"] is False
    assert diagnostics["trace_recorder"]["schema_version"] == 3
    assert diagnostics["trace_recorder"]["detailed_trace_capacity"] == 100
    assert diagnostics["controller"]["dtu_limit_power_observation"] is None
    sync = diagnostics["controller"]["measurement_synchronization"]
    assert sync["tolerance_seconds"] == 25


async def test_diagnostics_expose_correlated_dtu_limit_power_observation(hass) -> None:
    """A snapshot is exported as evidence only; diagnostics do not poll the DTU."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_DTU_HOST: "192.0.2.10", CONF_DTU_PORT: 502},
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.openems_zero_injection.coordinator.DtuProSModbusClient"
    ) as client_class:
        client_class.return_value.async_check_connectivity = AsyncMock(return_value=True)
        client_class.return_value.async_read_input_registers = AsyncMock(
            side_effect=lambda _address, count: [0] * count
        )
        client_class.return_value.async_read_power_limit_register = AsyncMock(
            return_value=30
        )
        client_class.return_value.connection_diagnostics.return_value = {
            "connected": True,
            "total_errors": 0,
            "consecutive_failures": 0,
            "last_error": None,
            "reconnections": 0,
        }
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.controller._last_dtu_limit_observation = {
        "installed_nominal_power_w": 3000,
        "requested_limit_percent": 30,
        "theoretical_max_power_w": 900,
        "active_power_w": 1480,
        "temporary_port_limits_percent": {"port_1": 30, "port_2": 30, "port_3": 30},
        "limits_confirmation_age_seconds": 34,
        "scheduler_state": "Stable",
        "scheduler_stabilizing": False,
    }
    read_count_before = client_class.return_value.async_read_input_registers.await_count

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    observation = diagnostics["controller"]["dtu_limit_power_observation"]

    assert observation["theoretical_max_power_w"] == 900
    assert observation["active_power_w"] == 1480
    assert observation["temporary_port_limits_percent"]["port_3"] == 30
    assert observation["scheduler_stabilizing"] is False
    assert client_class.return_value.async_read_input_registers.await_count == read_count_before
