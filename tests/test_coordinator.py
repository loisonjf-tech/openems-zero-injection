"""Tests for Build002 read-only telemetry coordination."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, call, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.openems_zero_injection.const import (
    CONF_DTU_HOST,
    CONF_DTU_PORT,
    DOMAIN,
    TEMPORARY_LIMIT_SCAN_INTERVAL,
)
from custom_components.openems_zero_injection.coordinator import DtuProSCoordinator
from custom_components.openems_zero_injection.modbus import DtuConnectionError


async def test_coordinator_decodes_measurements(hass) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_DTU_HOST: "192.0.2.10", CONF_DTU_PORT: 502})
    values = {0x3004: [2], 0x3000: [0x1234, 0x5678, 0x9ABC], 0x3003: [1], 0x3100: [0, 0, 0, 100], 0x3104: [0, 0, 0, 5], 0x3108: [0, 1234], 0x310A: [0, 0]}
    with patch("custom_components.openems_zero_injection.coordinator.DtuProSModbusClient") as cls:
        cls.return_value.async_read_input_registers = AsyncMock(side_effect=lambda address, _count: values[address])
        cls.return_value.async_read_power_limit_register = AsyncMock(
            side_effect=lambda address: {
                0xD007: 50,
                0xD008: 50,
                0xD00D: 75,
                0xD00E: 75,
                0xD013: 100,
                0xD014: 100,
            }[address]
        )
        cls.return_value.connection_diagnostics.return_value = {
            "connected": True,
            "last_error": None,
            "last_response_time_ms": 12.5,
            "last_connection_time_ms": 3.0,
        }
        coordinator = DtuProSCoordinator(hass, entry)
        await coordinator.async_refresh()
    assert coordinator.data.inverter_count == 2
    assert coordinator.data.active_power_w == 123.4
    assert coordinator.data.daily_energy_wh == 5
    assert coordinator.data.response_time_ms is not None
    assert coordinator.data.response_time_ms == 12.5
    assert coordinator.cycle_timings_ms["power"] is not None
    assert coordinator.cycle_timings_ms["total_cycle"] is not None
    assert coordinator.data.port_1_temporary_power_limit_percent == 50
    assert coordinator.active_temporary_power_limit_ports() == (1, 2, 3)


async def test_telemetry_failure_keeps_last_value_stale_then_recovers(hass) -> None:
    """A transient active-power read never injects a synthetic zero value."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_DTU_HOST: "192.0.2.10", CONF_DTU_PORT: 502}
    )
    values = {
        0x3000: [0x1234, 0x5678, 0x9ABC],
        0x3003: [1],
        0x3004: [2],
        0x3100: [0, 0, 0, 100],
        0x3104: [0, 0, 0, 5],
        0x3108: [0, 1234],
        0x310A: [0, 0],
    }
    with patch("custom_components.openems_zero_injection.coordinator.DtuProSModbusClient") as cls:
        client = cls.return_value
        client.async_read_input_registers = AsyncMock(
            side_effect=lambda address, _count: values[address]
        )
        client.async_read_power_limit_register = AsyncMock(return_value=50)
        coordinator = DtuProSCoordinator(hass, entry)
        await coordinator.async_refresh()
        def fail_active_power(address: int, _count: int) -> list[int]:
            if address == 0x3108:
                raise DtuConnectionError("0 bytes read")
            return values[address]

        client.async_read_input_registers.side_effect = fail_active_power
        await coordinator.async_refresh()

        assert coordinator.last_update_success is True
        assert coordinator.data.active_power_w == 123.4
        stale_health = coordinator.measurement_health("active_power_w")
        assert stale_health["available"] is False
        assert stale_health["consecutive_failures"] == 1

        client.async_read_input_registers.side_effect = lambda address, _count: values[address]
        await coordinator.async_refresh()

    restored_health = coordinator.measurement_health("active_power_w")
    assert coordinator.data.active_power_w == 123.4
    assert restored_health["available"] is True
    assert restored_health["consecutive_failures"] == 0


async def test_telemetry_failures_rate_limit_warnings(hass, caplog) -> None:
    """Repeated identical telemetry failures do not flood Home Assistant logs."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_DTU_HOST: "192.0.2.10", CONF_DTU_PORT: 502}
    )
    with patch("custom_components.openems_zero_injection.coordinator.DtuProSModbusClient") as cls:
        client = cls.return_value
        def fail_active_power(address: int, count: int) -> list[int]:
            if address == 0x3108:
                raise DtuConnectionError("failed")
            return [0] * count

        client.async_read_input_registers = AsyncMock(side_effect=fail_active_power)
        client.async_read_power_limit_register = AsyncMock(return_value=50)
        coordinator = DtuProSCoordinator(hass, entry)
        await coordinator.async_refresh()
        await coordinator.async_refresh()

    warnings = [
        record for record in caplog.records if "0x3108 unavailable" in record.message
    ]
    assert len(warnings) == 1


async def test_coordinator_reports_primary_read_failure(hass) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_DTU_HOST: "192.0.2.10", CONF_DTU_PORT: 502})
    with patch("custom_components.openems_zero_injection.coordinator.DtuProSModbusClient") as cls:
        cls.return_value.async_read_input_registers = AsyncMock(side_effect=DtuConnectionError("refused"))
        cls.return_value.async_read_power_limit_register = AsyncMock(
            side_effect=DtuConnectionError("refused")
        )
        cls.return_value.connection_diagnostics.return_value = {"last_error": "refused"}
        coordinator = DtuProSCoordinator(hass, entry)
        await coordinator.async_refresh()
    assert coordinator.last_update_success is False


async def test_invalid_power_limit_only_marks_that_value_unavailable(hass) -> None:
    """An unavailable configuration register does not stop telemetry updates."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_DTU_HOST: "192.0.2.10", CONF_DTU_PORT: 502})
    with patch("custom_components.openems_zero_injection.coordinator.DtuProSModbusClient") as cls:
        cls.return_value.async_read_input_registers = AsyncMock(
            side_effect=lambda _address, count: [0] * count
        )
        cls.return_value.async_read_power_limit_register = AsyncMock(
            side_effect=lambda address: DtuConnectionError("bad register")
            if address == 0xD00D
            else 50
        )
        coordinator = DtuProSCoordinator(hass, entry)
        await coordinator.async_refresh()
    assert coordinator.last_update_success is True
    assert coordinator.data.port_2_temporary_power_limit_percent is None
    assert coordinator.data.port_1_temporary_power_limit_percent == 50


async def test_temporary_limit_failure_keeps_cached_value_and_blocks_writes(hass) -> None:
    """An isolated D00D failure retains its value but makes automatic writes unsafe."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_DTU_HOST: "192.0.2.10", CONF_DTU_PORT: 502})
    with patch("custom_components.openems_zero_injection.coordinator.DtuProSModbusClient") as cls:
        client = cls.return_value
        client.async_read_input_registers = AsyncMock(
            side_effect=lambda _address, count: [0] * count
        )
        client.async_read_power_limit_register = AsyncMock(return_value=50)
        client.async_write_temporary_power_limit = AsyncMock()
        coordinator = DtuProSCoordinator(hass, entry)
        await coordinator.async_refresh()
        def fail_port_two(address: int) -> int:
            if address == 0xD00D:
                raise DtuConnectionError("Modbus communication failed")
            return 50

        client.async_read_power_limit_register.side_effect = fail_port_two
        coordinator._last_temporary_limit_read = datetime.now(UTC) - TEMPORARY_LIMIT_SCAN_INTERVAL
        await coordinator.async_refresh()
        await coordinator.async_set_manual_writes_enabled(True)
        from homeassistant.exceptions import HomeAssistantError

        with pytest.raises(HomeAssistantError, match="stale or inconsistent"):
            await coordinator.async_set_all_temporary_power_limits(55)

    assert coordinator.last_update_success is True
    assert coordinator.data.port_2_temporary_power_limit_percent == 50
    assert not coordinator.power_limit_health(0xD00D)["available"]
    assert coordinator.temporary_limits_ready
    assert not coordinator.temporary_limits_fresh
    client.async_write_temporary_power_limit.assert_not_awaited()


async def test_permanent_limit_failure_does_not_affect_temporary_readiness(hass) -> None:
    """A diagnostic permanent-register timeout never pauses the control input."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_DTU_HOST: "192.0.2.10", CONF_DTU_PORT: 502})
    with patch("custom_components.openems_zero_injection.coordinator.DtuProSModbusClient") as cls:
        client = cls.return_value
        client.async_read_input_registers = AsyncMock(
            side_effect=lambda _address, count: [0] * count
        )
        def fail_permanent_port_three(address: int) -> int:
            if address == 0xD014:
                raise DtuConnectionError("Modbus communication failed")
            return 50

        client.async_read_power_limit_register = AsyncMock(
            side_effect=fail_permanent_port_three
        )
        coordinator = DtuProSCoordinator(hass, entry)
        await coordinator.async_refresh()

    assert coordinator.last_update_success is True
    assert coordinator.temporary_limits_ready
    assert not coordinator.power_limit_health(0xD014)["available"]


async def test_permanent_limits_are_not_read_on_each_fast_cycle(hass) -> None:
    """Permanent diagnostic registers are read only on their slow schedule."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_DTU_HOST: "192.0.2.10", CONF_DTU_PORT: 502}
    )
    with patch("custom_components.openems_zero_injection.coordinator.DtuProSModbusClient") as cls:
        client = cls.return_value
        client.async_read_input_registers = AsyncMock(
            side_effect=lambda _address, count: [0] * count
        )
        client.async_read_power_limit_register = AsyncMock(return_value=50)
        coordinator = DtuProSCoordinator(hass, entry)
        await coordinator.async_refresh()
        client.async_read_power_limit_register.reset_mock()
        await coordinator.async_refresh()

    assert client.async_read_power_limit_register.await_args_list == []


async def test_temporary_limit_recovers_after_all_three_reads_succeed(hass) -> None:
    """Production can resume only after all temporary registers refresh coherently."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_DTU_HOST: "192.0.2.10", CONF_DTU_PORT: 502})
    with patch("custom_components.openems_zero_injection.coordinator.DtuProSModbusClient") as cls:
        client = cls.return_value
        client.async_read_input_registers = AsyncMock(
            side_effect=lambda _address, count: [0] * count
        )
        client.async_read_power_limit_register = AsyncMock(return_value=50)
        coordinator = DtuProSCoordinator(hass, entry)
        await coordinator.async_refresh()
        def fail_port_two(address: int) -> int:
            if address == 0xD00D:
                raise DtuConnectionError("failed")
            return 50

        client.async_read_power_limit_register.side_effect = fail_port_two
        coordinator._last_temporary_limit_read = datetime.now(UTC) - TEMPORARY_LIMIT_SCAN_INTERVAL
        await coordinator.async_refresh()
        assert coordinator.temporary_limits_ready
        assert not coordinator.temporary_limits_fresh
        client.async_read_power_limit_register.side_effect = None
        client.async_read_power_limit_register.return_value = 50
        coordinator._last_temporary_limit_read = datetime.now(UTC) - TEMPORARY_LIMIT_SCAN_INTERVAL
        await coordinator.async_refresh()

    assert coordinator.temporary_limits_ready
    assert coordinator.temporary_limits_fresh
    assert coordinator.power_limit_health(0xD00D)["available"]


async def test_overlapping_refreshes_reuse_the_current_snapshot(hass) -> None:
    """A slow Modbus read cannot start a second coordinator transaction."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_DTU_HOST: "192.0.2.10", CONF_DTU_PORT: 502}
    )
    with patch("custom_components.openems_zero_injection.coordinator.DtuProSModbusClient") as cls:
        client = cls.return_value
        active_calls = 0
        max_active_calls = 0

        async def read(address: int, count: int) -> list[int]:
            nonlocal active_calls, max_active_calls
            active_calls += 1
            max_active_calls = max(max_active_calls, active_calls)
            await asyncio.sleep(0)
            active_calls -= 1
            return [0] * count

        client.async_read_input_registers = AsyncMock(side_effect=read)
        client.async_read_power_limit_register = AsyncMock(return_value=50)
        coordinator = DtuProSCoordinator(hass, entry)
        await coordinator.async_refresh()
        await asyncio.gather(
            coordinator._async_update_data(), coordinator._async_update_data()
        )

    assert active_calls == 0
    assert max_active_calls == 1


async def test_transport_failure_keeps_cached_power_until_global_threshold(hass) -> None:
    """A socket failure leaves already-valid power visible as stale data."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_DTU_HOST: "192.0.2.10", CONF_DTU_PORT: 502}
    )
    values = {0x3108: [0, 1234], 0x310A: [0, 0]}
    with patch("custom_components.openems_zero_injection.coordinator.DtuProSModbusClient") as cls:
        client = cls.return_value
        client.async_read_input_registers = AsyncMock(
            side_effect=lambda address, count: values.get(address, [0] * count)
        )
        client.async_read_power_limit_register = AsyncMock(return_value=50)
        client.connection_diagnostics.return_value = {"connected": True, "last_error": None}
        coordinator = DtuProSCoordinator(hass, entry)
        await coordinator.async_refresh()
        client.async_read_input_registers.side_effect = DtuConnectionError("socket closed")
        client.connection_diagnostics.return_value = {
            "connected": False,
            "last_error": "socket closed",
        }
        await coordinator.async_refresh()

    assert coordinator.last_update_success is True
    assert coordinator.data.active_power_w == 123.4
    assert coordinator.data.last_error == "socket closed"


async def test_shutdown_stops_periodic_controller_and_closes_client(hass) -> None:
    """Unload leaves no controller timer or persistent TCP client behind."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_DTU_HOST: "192.0.2.10", CONF_DTU_PORT: 502}
    )
    with patch("custom_components.openems_zero_injection.coordinator.DtuProSModbusClient") as cls:
        client = cls.return_value
        client.async_disconnect = AsyncMock()
        coordinator = DtuProSCoordinator(hass, entry)
        await coordinator.controller.async_start()
        assert coordinator.controller._cancel_tick is not None
        await coordinator.async_shutdown()

    assert coordinator.controller._cancel_tick is None
    client.async_disconnect.assert_awaited_once()


async def test_power_limit_failures_rate_limit_warnings(hass, caplog) -> None:
    """Repeated identical register failures do not spam Home Assistant logs."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_DTU_HOST: "192.0.2.10", CONF_DTU_PORT: 502})
    with patch("custom_components.openems_zero_injection.coordinator.DtuProSModbusClient") as cls:
        cls.return_value.async_read_power_limit_register = AsyncMock(
            side_effect=DtuConnectionError("failed")
        )
        coordinator = DtuProSCoordinator(hass, entry)
        await coordinator._async_refresh_power_limit(0xD00D)
        await coordinator._async_refresh_power_limit(0xD00D)

    warnings = [
        record for record in caplog.records if "0xD00D unavailable" in record.message
    ]
    assert len(warnings) == 1


async def test_permanent_registers_are_suppressed_after_two_failures(hass) -> None:
    """Unsupported permanent registers are not retried every five-minute cycle."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_DTU_HOST: "192.0.2.10", CONF_DTU_PORT: 502}
    )
    with patch("custom_components.openems_zero_injection.coordinator.DtuProSModbusClient") as cls:
        client = cls.return_value
        client.async_read_power_limit_register = AsyncMock(
            side_effect=DtuConnectionError("unsupported register")
        )
        client.connection_diagnostics.return_value = {"connected": True}
        coordinator = DtuProSCoordinator(hass, entry)
        now = datetime.now(UTC)
        await coordinator._async_refresh_power_limits(now)
        await coordinator._async_refresh_power_limits(now + timedelta(minutes=5))
        client.async_read_power_limit_register.reset_mock()
        coordinator._last_temporary_limit_read = now + timedelta(minutes=10)
        await coordinator._async_refresh_power_limits(now + timedelta(minutes=10))

    assert client.async_read_power_limit_register.await_count == 0


async def test_manual_write_is_gated_and_verified(hass) -> None:
    """A temporary write is blocked by default then updates only after re-read."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_DTU_HOST: "192.0.2.10", CONF_DTU_PORT: 502})
    with patch("custom_components.openems_zero_injection.coordinator.DtuProSModbusClient") as cls:
        client = cls.return_value
        client.async_read_input_registers = AsyncMock(
            side_effect=lambda _address, count: [0] * count
        )
        client.async_read_power_limit_register = AsyncMock(return_value=50)
        client.async_write_temporary_power_limit = AsyncMock()
        coordinator = DtuProSCoordinator(hass, entry)
        await coordinator.async_refresh()
        from homeassistant.exceptions import HomeAssistantError

        with pytest.raises(HomeAssistantError, match="disabled"):
            await coordinator.async_set_temporary_power_limit(1, 60)
        client.async_write_temporary_power_limit.assert_not_awaited()

        await coordinator.async_set_manual_writes_enabled(True)
        client.async_read_power_limit_register.side_effect = [60]
        await coordinator.async_set_temporary_power_limit(1, 60)

    client.async_write_temporary_power_limit.assert_awaited_once_with(0xD007, 60)
    assert coordinator.data.port_1_temporary_power_limit_percent == 60


@pytest.mark.parametrize("value", [1, 101])
async def test_manual_write_rejects_out_of_range_values(hass, value: int) -> None:
    """The coordinator never forwards an out-of-range manual command."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_DTU_HOST: "192.0.2.10", CONF_DTU_PORT: 502})
    coordinator = DtuProSCoordinator(hass, entry)
    await coordinator.async_set_manual_writes_enabled(True)
    from homeassistant.exceptions import HomeAssistantError

    with pytest.raises(HomeAssistantError, match="between 2 and 100"):
        await coordinator.async_set_temporary_power_limit(1, value)


async def test_manual_write_different_readback_preserves_last_confirmed_value(hass) -> None:
    """A mismatch does not overwrite the last confirmed Home Assistant value."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_DTU_HOST: "192.0.2.10", CONF_DTU_PORT: 502})
    with patch("custom_components.openems_zero_injection.coordinator.DtuProSModbusClient") as cls:
        client = cls.return_value
        client.async_read_input_registers = AsyncMock(
            side_effect=lambda _address, count: [0] * count
        )
        client.async_read_power_limit_register = AsyncMock(return_value=50)
        client.async_write_temporary_power_limit = AsyncMock()
        coordinator = DtuProSCoordinator(hass, entry)
        await coordinator.async_refresh()
        await coordinator.async_set_manual_writes_enabled(True)
        client.async_read_power_limit_register.side_effect = [40]
        from homeassistant.exceptions import HomeAssistantError

        with pytest.raises(HomeAssistantError, match="did not confirm"):
            await coordinator.async_set_temporary_power_limit(1, 60)

    assert coordinator.data.port_1_temporary_power_limit_percent == 50


async def test_automatic_write_updates_all_three_temporary_ports_only(hass) -> None:
    """Build004 writes and verifies exactly the three approved temporary ports."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_DTU_HOST: "192.0.2.10", CONF_DTU_PORT: 502})
    with patch("custom_components.openems_zero_injection.coordinator.DtuProSModbusClient") as cls:
        client = cls.return_value
        client.async_read_input_registers = AsyncMock(
            side_effect=lambda _address, count: [0] * count
        )
        client.async_read_power_limit_register = AsyncMock(return_value=50)
        client.async_write_temporary_power_limit = AsyncMock()
        coordinator = DtuProSCoordinator(hass, entry)
        await coordinator.async_refresh()
        await coordinator.async_set_manual_writes_enabled(True)
        client.async_read_power_limit_register.side_effect = [55, 55, 55]
        await coordinator.async_set_all_temporary_power_limits(55)

    assert client.async_write_temporary_power_limit.await_args_list == [
        call(0xD007, 55), call(0xD00D, 55), call(0xD013, 55)
    ]
    assert coordinator.data.port_1_temporary_power_limit_percent == 55
    assert coordinator.data.port_2_temporary_power_limit_percent == 55
    assert coordinator.data.port_3_temporary_power_limit_percent == 55


async def test_automatic_write_readback_mismatch_keeps_last_confirmed_values(hass) -> None:
    """A partial or inconsistent command is never treated as confirmed."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_DTU_HOST: "192.0.2.10", CONF_DTU_PORT: 502})
    with patch("custom_components.openems_zero_injection.coordinator.DtuProSModbusClient") as cls:
        client = cls.return_value
        client.async_read_input_registers = AsyncMock(
            side_effect=lambda _address, count: [0] * count
        )
        client.async_read_power_limit_register = AsyncMock(return_value=50)
        client.async_write_temporary_power_limit = AsyncMock()
        coordinator = DtuProSCoordinator(hass, entry)
        await coordinator.async_refresh()
        await coordinator.async_set_manual_writes_enabled(True)
        client.async_read_power_limit_register.side_effect = [55, 54, 55]
        from homeassistant.exceptions import HomeAssistantError

        with pytest.raises(HomeAssistantError, match="mismatch"):
            await coordinator.async_set_all_temporary_power_limits(55)

    assert coordinator.data.port_1_temporary_power_limit_percent == 50
