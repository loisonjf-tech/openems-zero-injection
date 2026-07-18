"""Integration-level controller safety tests without a real DTU."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from datetime import UTC, datetime, timedelta

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
    assert controller.simulated_current_limit == 45

    await controller.async_tick()
    assert controller.commands_simulated == 1
    assert controller.status.last_decision == "Simulation awaiting measurement change"


async def test_simulation_requires_physical_change_after_virtual_command(hass) -> None:
    """Delay expiry alone cannot create a second virtual command."""
    hass.states.async_set("sensor.grid", "-220")
    coordinator = fake_coordinator()
    controller = ZeroInjectionController(
        hass, coordinator, AcquisitionEngine(hass, "sensor.grid", False)
    )
    await controller.async_set_mode(ControllerMode.SIMULATION.value)
    for _ in range(3):
        await controller.async_tick()
    assert controller.simulated_current_limit == 45
    assert coordinator.data.port_1_temporary_power_limit_percent == 50

    controller.scheduler._next_allowed_at = datetime.now(UTC) - timedelta(seconds=1)
    await controller.async_tick()
    assert controller.commands_simulated == 1
    assert controller.status.last_decision == "Simulation awaiting measurement change"

    hass.states.async_set("sensor.grid", "-260")
    await controller.async_tick()
    assert controller.commands_simulated == 2
    assert controller.simulated_current_limit == 45
    coordinator.async_set_all_temporary_power_limits.assert_not_awaited()


async def test_simulation_keeps_real_limit_separate_from_virtual_recommendation(hass) -> None:
    """A 2% recommendation must never overwrite a 100% Modbus limit."""
    hass.states.async_set("sensor.grid", "-3_200")
    coordinator = fake_coordinator()
    coordinator.data.port_1_temporary_power_limit_percent = 100
    coordinator.data.port_2_temporary_power_limit_percent = 100
    coordinator.data.port_3_temporary_power_limit_percent = 100
    controller = ZeroInjectionController(
        hass, coordinator, AcquisitionEngine(hass, "sensor.grid", False)
    )
    controller.set_maximum_step(100)
    await controller.async_set_mode(ControllerMode.SIMULATION.value)
    for _ in range(3):
        await controller.async_tick()

    assert controller.status.real_dtu_limit_percent == 100
    assert controller.simulated_current_limit == 2
    assert controller.status.calculated_limit_percent == 2


async def test_simulated_commands_never_exceed_session_decisions(hass) -> None:
    """Session counters use the same non-persistent accounting policy."""
    hass.states.async_set("sensor.grid", "-220")
    controller = ZeroInjectionController(
        hass, fake_coordinator(), AcquisitionEngine(hass, "sensor.grid", False)
    )
    await controller.async_set_mode(ControllerMode.SIMULATION.value)
    for _ in range(5):
        await controller.async_tick()

    assert controller.commands_simulated <= controller.decisions_evaluated


async def test_disabling_controller_clears_virtual_simulation_state(hass) -> None:
    """A virtual limit is session-only and is never retained after Disabled."""
    hass.states.async_set("sensor.grid", "-220")
    coordinator = fake_coordinator()
    controller = ZeroInjectionController(
        hass, coordinator, AcquisitionEngine(hass, "sensor.grid", False)
    )
    await controller.async_set_mode(ControllerMode.SIMULATION.value)
    for _ in range(3):
        await controller.async_tick()
    await controller.async_set_mode(ControllerMode.DISABLED.value)
    assert controller.simulated_current_limit is None
    assert controller.last_simulated_limit is None


async def test_nominal_power_derives_conversion_coefficient_and_updates_decision(hass) -> None:
    """The decision engine always receives the coefficient derived from PV power."""
    hass.states.async_set("sensor.grid", "-200")
    coordinator = fake_coordinator()
    controller = ZeroInjectionController(
        hass, coordinator, AcquisitionEngine(hass, "sensor.grid", False)
    )
    assert controller.installed_nominal_power_w == 3000
    assert controller.watts_per_percent == 30

    controller.set_installed_nominal_power(4000, source="entity")
    assert controller.watts_per_percent == 40
    await controller.async_set_mode(ControllerMode.SIMULATION.value)
    for _ in range(3):
        await controller.async_tick()

    assert controller.simulated_current_limit == 46
    coordinator.async_set_all_temporary_power_limits.assert_not_awaited()


def test_installed_nominal_power_rejects_invalid_values(hass) -> None:
    """Only a safe, whole nominal PV power can be configured."""
    controller = ZeroInjectionController(
        hass, fake_coordinator(), AcquisitionEngine(hass, "sensor.grid", False)
    )
    for value in (0, -10, 50_001, "3000"):
        try:
            controller.set_installed_nominal_power(value, source="entity")
        except ValueError:
            continue
        raise AssertionError(f"invalid nominal power accepted: {value!r}")


def test_nominal_power_can_be_restored_from_persisted_options(hass) -> None:
    """A recreated controller uses the stored option rather than a DTU reading."""
    controller = ZeroInjectionController(
        hass,
        fake_coordinator(),
        AcquisitionEngine(hass, "sensor.grid", False),
        installed_nominal_power_w=4000,
        installed_power_source="options",
    )
    assert controller.installed_nominal_power_w == 4000
    assert controller.watts_per_percent == 40
    assert controller.installed_power_source == "options"


def test_changing_nominal_power_never_sends_a_dtu_command(hass) -> None:
    """Configuration changes alone are local and do not actuate the DTU."""
    coordinator = fake_coordinator()
    controller = ZeroInjectionController(
        hass, coordinator, AcquisitionEngine(hass, "sensor.grid", False)
    )
    controller.set_installed_nominal_power(4000, source="entity")
    coordinator.async_set_all_temporary_power_limits.assert_not_awaited()


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
