"""Tests for Build002 read-only telemetry coordination."""

from unittest.mock import AsyncMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.openems_zero_injection.const import CONF_DTU_HOST, CONF_DTU_PORT, DOMAIN
from custom_components.openems_zero_injection.coordinator import DtuProSCoordinator
from custom_components.openems_zero_injection.modbus import DtuConnectionError


async def test_coordinator_decodes_measurements(hass) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_DTU_HOST: "192.0.2.10", CONF_DTU_PORT: 502})
    values = {0x3004: [2], 0x3000: [0x1234, 0x5678, 0x9ABC], 0x3003: [1], 0x3100: [0, 0, 0, 100], 0x3104: [0, 0, 0, 5], 0x3108: [0, 1234], 0x310A: [0, 0]}
    with patch("custom_components.openems_zero_injection.coordinator.DtuProSModbusClient") as cls:
        cls.return_value.async_read_input_registers = AsyncMock(side_effect=lambda address, _count: values[address])
        coordinator = DtuProSCoordinator(hass, entry)
        await coordinator.async_refresh()
    assert coordinator.data.inverter_count == 2
    assert coordinator.data.active_power_w == 123.4
    assert coordinator.data.daily_energy_wh == 5
    assert coordinator.data.response_time_ms is not None


async def test_coordinator_reports_primary_read_failure(hass) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_DTU_HOST: "192.0.2.10", CONF_DTU_PORT: 502})
    with patch("custom_components.openems_zero_injection.coordinator.DtuProSModbusClient") as cls:
        cls.return_value.async_read_input_registers = AsyncMock(side_effect=DtuConnectionError("refused"))
        coordinator = DtuProSCoordinator(hass, entry)
        await coordinator.async_refresh()
    assert coordinator.last_update_success is False
