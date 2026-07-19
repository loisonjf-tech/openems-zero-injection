"""Tests for the OpenEMS connection diagnostic sensor."""

from unittest.mock import AsyncMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry
from homeassistant.helpers import entity_registry as er

from custom_components.openems_zero_injection.const import (
    CONF_DTU_HOST,
    CONF_DTU_PORT,
    DOMAIN,
)


async def test_connection_sensor_reports_connected(hass) -> None:
    """The diagnostic sensor reports a successful DTU connection."""
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
        client_class.return_value.async_write_temporary_power_limit = AsyncMock()
        client_class.return_value.async_disconnect = AsyncMock()
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    registry = er.async_get(hass)
    registry_entry = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_connection_status"
    )
    assert registry_entry is not None
    state = hass.states.get(registry_entry)
    assert state is not None
    assert state.state == "Connecté"

    power_limit_entity = registry.async_get_entity_id(
        "number", DOMAIN, f"{entry.entry_id}_port_1_temporary_power_limit"
    )
    assert power_limit_entity is not None
    assert hass.states.get(power_limit_entity).state == "50.0"

    temporary_limit_sensor = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_port_1_temporary_power_limit_percent"
    )
    assert temporary_limit_sensor is not None
    assert hass.states.get(temporary_limit_sensor).state == "50"

    safety_switch = registry.async_get_entity_id(
        "switch", DOMAIN, f"{entry.entry_id}_enable_manual_dtu_writes"
    )
    assert safety_switch is not None
    assert hass.states.get(safety_switch).state == "off"

    expected_energy_manager_states = {
        "energy_manager_battery_count": "0",
        "energy_manager_total_max_charge_power_w": "0",
        "energy_manager_total_current_charge_power_w": "0",
        "energy_manager_total_remaining_charge_power_w": "0",
        "energy_manager_state": "Aucune batterie configurée",
    }
    for suffix, expected_state in expected_energy_manager_states.items():
        entity_id = registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_{suffix}"
        )
        assert entity_id is not None
        assert hass.states.get(entity_id).state == expected_state

    coordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.last_update_success = False
    coordinator.async_update_listeners()
    await hass.async_block_till_done()

    # A verified cached temporary limit remains visible; its attributes expose
    # that a later Modbus refresh might be stale.
    assert hass.states.get(temporary_limit_sensor).state == "50"

    for platform, unique_id in (
        ("select", f"{entry.entry_id}_controller_mode"),
        ("switch", f"{entry.entry_id}_enable_manual_dtu_writes"),
        ("number", f"{entry.entry_id}_installed_nominal_power"),
        ("sensor", f"{entry.entry_id}_controller_state"),
        ("sensor", f"{entry.entry_id}_commands_simulated"),
    ):
        entity_id = registry.async_get_entity_id(platform, DOMAIN, unique_id)
        assert entity_id is not None
        assert hass.states.get(entity_id).state != "unavailable"
