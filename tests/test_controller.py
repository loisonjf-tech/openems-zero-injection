"""Integration-level controller safety tests without a real DTU."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from custom_components.openems_zero_injection.acquisition import AcquisitionEngine
from custom_components.openems_zero_injection.const import ControllerMode, SchedulerState
from custom_components.openems_zero_injection.controller import ZeroInjectionController


def fake_coordinator(*, writes_enabled: bool = True):
    coordinator = SimpleNamespace(
        manual_writes_enabled=writes_enabled,
        temporary_limits_ready=True,
        data=SimpleNamespace(
            connected=True,
            active_power_w=900.0,
            port_1_temporary_power_limit_percent=50,
            port_2_temporary_power_limit_percent=50,
            port_3_temporary_power_limit_percent=50,
        ),
        async_set_all_temporary_power_limits=AsyncMock(),
        async_update_listeners=lambda: None,
    )
    return coordinator


async def test_disabled_and_simulation_never_write(hass) -> None:
    hass.states.async_set("sensor.grid", "-220")
    coordinator = fake_coordinator()
    controller = ZeroInjectionController(
        hass, coordinator, AcquisitionEngine(hass, "sensor.grid", False)
    )
    await controller.async_tick()
    coordinator.async_set_all_temporary_power_limits.assert_not_awaited()

    await controller.async_set_mode(ControllerMode.SIMULATION.value)
    for _ in range(3):
        await controller.async_tick()
    coordinator.async_set_all_temporary_power_limits.assert_not_awaited()
    assert controller.commands_simulated == 1


async def test_production_requires_three_valid_measurements_then_writes(hass) -> None:
    hass.states.async_set("sensor.grid", "-220")
    coordinator = fake_coordinator()
    controller = ZeroInjectionController(
        hass, coordinator, AcquisitionEngine(hass, "sensor.grid", False)
    )
    await controller.async_set_mode(ControllerMode.PRODUCTION.value)
    await controller.async_tick()
    await controller.async_tick()
    coordinator.async_set_all_temporary_power_limits.assert_not_awaited()
    await controller.async_tick()
    coordinator.async_set_all_temporary_power_limits.assert_awaited_once_with(45)
    assert controller.commands_succeeded == 1
    assert controller.scheduler.state is SchedulerState.WAITING


async def test_grid_sensor_loss_pauses_controller(hass) -> None:
    coordinator = fake_coordinator()
    controller = ZeroInjectionController(
        hass, coordinator, AcquisitionEngine(hass, "sensor.missing", False)
    )
    await controller.async_set_mode(ControllerMode.PRODUCTION.value)
    await controller.async_tick()
    assert controller.status.state == "Paused"
    assert controller.scheduler.state is SchedulerState.PAUSED
    coordinator.async_set_all_temporary_power_limits.assert_not_awaited()


async def test_inconsistent_limits_pause_without_a_command(hass) -> None:
    hass.states.async_set("sensor.grid", "-220")
    coordinator = fake_coordinator()
    coordinator.data.port_2_temporary_power_limit_percent = 40
    controller = ZeroInjectionController(
        hass, coordinator, AcquisitionEngine(hass, "sensor.grid", False)
    )
    await controller.async_set_mode(ControllerMode.PRODUCTION.value)
    for _ in range(3):
        await controller.async_tick()
    assert controller.status.state == "Paused"
    coordinator.async_set_all_temporary_power_limits.assert_not_awaited()


async def test_stale_temporary_limits_pause_production_without_a_command(hass) -> None:
    """Cached limits must not authorize an automatic production command."""
    hass.states.async_set("sensor.grid", "-220")
    coordinator = fake_coordinator()
    coordinator.temporary_limits_ready = False
    controller = ZeroInjectionController(
        hass, coordinator, AcquisitionEngine(hass, "sensor.grid", False)
    )
    await controller.async_set_mode(ControllerMode.PRODUCTION.value)
    for _ in range(3):
        await controller.async_tick()

    assert controller.status.state == "Paused"
    assert controller.status.last_error == "Temporary limits are stale or inconsistent"
    coordinator.async_set_all_temporary_power_limits.assert_not_awaited()
