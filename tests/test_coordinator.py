"""Tests for the DTU connection coordinator."""

from unittest.mock import AsyncMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.openems_zero_injection.const import (
    CONF_DTU_HOST,
    CONF_DTU_PORT,
    DOMAIN,
)
from custom_components.openems_zero_injection.coordinator import DtuProSCoordinator
from custom_components.openems_zero_injection.modbus import DtuConnectionError


async def test_coordinator_exposes_connected_status(hass) -> None:
    """The coordinator exposes a successful connectivity check."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_DTU_HOST: "192.0.2.10", CONF_DTU_PORT: 502},
    )
    with patch(
        "custom_components.openems_zero_injection.coordinator.DtuProSModbusClient"
    ) as client_class:
        client_class.return_value.async_check_connectivity = AsyncMock(return_value=True)
        coordinator = DtuProSCoordinator(hass, entry)
        await coordinator.async_refresh()

    assert coordinator.data.connected is True
    assert coordinator.data.last_error is None


async def test_coordinator_exposes_connection_error(hass) -> None:
    """A failed connectivity check does not prevent a diagnostic state."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_DTU_HOST: "192.0.2.10", CONF_DTU_PORT: 502},
    )
    with patch(
        "custom_components.openems_zero_injection.coordinator.DtuProSModbusClient"
    ) as client_class:
        client_class.return_value.async_check_connectivity = AsyncMock(
            side_effect=DtuConnectionError("Connection refused")
        )
        coordinator = DtuProSCoordinator(hass, entry)
        await coordinator.async_refresh()

    assert coordinator.data.connected is False
    assert coordinator.data.last_error == "Connection refused"
