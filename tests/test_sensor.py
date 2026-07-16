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
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    registry = er.async_get(hass)
    registry_entry = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_connection_status"
    )
    assert registry_entry is not None
    state = hass.states.get(registry_entry)
    assert state is not None
    assert state.state == "Connected"

    power_limit_entity = registry.async_get_entity_id(
        "number", DOMAIN, f"{entry.entry_id}_port_1_temporary_power_limit"
    )
    assert power_limit_entity is not None
    assert hass.states.get(power_limit_entity).state == "50.0"

    safety_switch = registry.async_get_entity_id(
        "switch", DOMAIN, f"{entry.entry_id}_enable_manual_dtu_writes"
    )
    assert safety_switch is not None
    assert hass.states.get(safety_switch).state == "off"
