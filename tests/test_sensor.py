"""Tests for the OpenEMS connection diagnostic sensor."""

from unittest.mock import AsyncMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

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
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    state = hass.states.get("sensor.openems_connection")
    assert state is not None
    assert state.state == "Connected"
