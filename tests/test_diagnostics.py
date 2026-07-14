"""Tests for OpenEMS Zero Injection diagnostics."""

from unittest.mock import AsyncMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.openems_zero_injection import async_setup_entry
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
        assert await async_setup_entry(hass, entry)
        await hass.async_block_till_done()

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics == {
        "dtu_ip": "192.0.2.10",
        "port": 502,
        "connection": {"connected": True, "last_communication_error": None},
    }
