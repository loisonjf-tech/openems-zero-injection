"""Integration-level controller safety tests without a real DTU."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call
from datetime import UTC, datetime, timedelta
from dataclasses import replace

from custom_components.openems_zero_injection.acquisition import (
    AcquisitionEngine,
    GridMeasurement,
)
from custom_components.openems_zero_injection.battery import (
    BatteryHealth,
    BatteryResource,
)
from custom_components.openems_zero_injection.const import (
    ControllerMode,
    ProductionStartupStrategy,
    SchedulerState,
)
from custom_components.openems_zero_injection.controller import ZeroInjectionController
from custom_components.openems_zero_injection.energy_strategy import (
    BatteryPriorityContext,
)


def fake_coordinator(*, automatic_writes_enabled: bool = True):
    timestamp = datetime.now(UTC)
    coordinator = SimpleNamespace(
        automatic_write_allowed=automatic_writes_enabled,
        temporary_limits_ready=True,
        temporary_limits_timestamp=timestamp,
        data=SimpleNamespace(
            connected=True,
            active_power_w=900.0,
            last_success=timestamp,
            port_1_temporary_power_limit_percent=50,
            port_2_temporary_power_limit_percent=50,
            port_3_temporary_power_limit_percent=50,
        ),
        async_set_all_temporary_power_limits=AsyncMock(),
        async_takeover_temporary_power_limits=AsyncMock(),
        async_update_listeners=lambda: None,
    )
    return coordinator


async def test_takeover_establishes_a_reference_before_first_production_decision(hass) -> None:
    """Takeover is a single all-port command before normal Production control."""
    coordinator = fake_coordinator()
    controller = ZeroInjectionController(
        hass,
        coordinator,
        AcquisitionEngine(hass, "sensor.grid", False),
        production_startup_strategy=ProductionStartupStrategy.TAKEOVER,
        takeover_limit_percent=85,
    )

    await controller.async_set_mode(ControllerMode.PRODUCTION.value)
    await controller.async_tick()

    coordinator.async_takeover_temporary_power_limits.assert_awaited_once_with(85)
    coordinator.async_set_all_temporary_power_limits.assert_not_awaited()
    assert controller.commands_sent == 1
    assert controller.commands_succeeded == 1
    assert not controller.takeover_pending
    assert controller.status.current_limit_percent == 85
    assert controller.scheduler.state is SchedulerState.WAITING


async def test_auto_resume_runs_takeover_only_for_restored_production(hass) -> None:
    """An explicit opt-in restores Production through the same takeover path."""
    coordinator = fake_coordinator()
    controller = ZeroInjectionController(
        hass,
        coordinator,
        AcquisitionEngine(hass, "sensor.grid", False),
        initial_mode=ControllerMode.PRODUCTION,
        mode_restore_source="options",
        production_startup_strategy=ProductionStartupStrategy.TAKEOVER,
        takeover_limit_percent=90,
        auto_resume_production=True,
    )

    await controller.async_tick()

    coordinator.async_takeover_temporary_power_limits.assert_awaited_once_with(90)
    assert not controller.takeover_pending


async def test_disabled_and_simulation_never_write(hass) -> None:
    hass.states.async_set("sensor.grid", "-220")
    coordinator = fake_coordinator()
    controller = ZeroInjectionController(
        hass, coordinator, AcquisitionEngine(hass, "sensor.grid", False)
    )
    await controller.async_tick()
    coordinator.async_set_all_temporary_power_limits.assert_not_awaited()
    assert controller.status.grid_power_w == -220
    assert controller.status.scheduler_inactive_reason == "Controller disabled"

    await controller.async_set_mode(ControllerMode.SIMULATION.value)
    for _ in range(3):
        await controller.async_tick()
    coordinator.async_set_all_temporary_power_limits.assert_not_awaited()
    assert controller.commands_simulated == 1
    assert controller.simulated_current_limit == 48

    await controller.async_tick()
    assert controller.commands_simulated == 1
    assert controller.status.last_decision == "Simulation awaiting significant measurements"


async def test_battery_priority_simulation_comparison_never_writes_dtu(hass) -> None:
    """Build007 records a candidate but keeps Simulation strictly write-free."""
    hass.states.async_set("sensor.grid", "-220")
    coordinator = fake_coordinator()
    controller = ZeroInjectionController(
        hass, coordinator, AcquisitionEngine(hass, "sensor.grid", False)
    )
    battery = BatteryResource(
        resource_id="battery-1",
        name="Test battery",
        adapter_id="test",
        adapter_version="test",
        available=True,
        health=BatteryHealth.HEALTHY,
        last_updated=datetime.now(UTC),
        data_age_seconds=1,
        charge_power_w=0,
        discharge_power_w=0,
        remaining_charge_power_w=500,
    )
    controller.energy_policy_engine.set_battery_context_provider(
        lambda: BatteryPriorityContext((battery,), 500, "complete")
    )

    await controller.async_set_mode(ControllerMode.SIMULATION.value)
    for _ in range(3):
        await controller.async_tick()

    coordinator.async_set_all_temporary_power_limits.assert_not_awaited()
    comparison = controller.trace_recorder.strategy_comparisons[-1]
    assert comparison.candidate_target_grid_power_w == -65
    assert comparison.candidate_expected_storage_gain_w == 25


async def test_capacity_release_requests_verified_dtu_maximum_through_scheduler(hass) -> None:
    """The policy bypasses prediction, never Scheduler safeguards."""
    hass.states.async_set("sensor.grid", "-100")
    coordinator = fake_coordinator()
    controller = ZeroInjectionController(
        hass, coordinator, AcquisitionEngine(hass, "sensor.grid", False)
    )
    battery = [
        BatteryResource(
            resource_id="battery-1",
            name="Test battery",
            adapter_id="test",
            adapter_version="test",
            available=True,
            health=BatteryHealth.HEALTHY,
            last_updated=datetime.now(UTC),
            data_age_seconds=1,
            soc_percent=38,
            charge_power_w=0,
            discharge_power_w=0,
            max_charge_power_w=1000,
            remaining_charge_power_w=1000,
            source_freshness={
                "soc_percent": "fresh",
                "max_charge_power_w": "fresh",
            },
        )
    ]
    controller.energy_policy_engine.set_battery_context_provider(
        lambda: BatteryPriorityContext((battery[0],), None, "none")
    )
    controller.energy_policy_engine.configure_battery_priority(
        mode="capacity_release",
        margin_w=25,
        charge_threshold_w=50,
        confirmation_samples=3,
    )
    await controller.async_set_mode(ControllerMode.PRODUCTION.value)

    # The first actionable controller snapshot must release a coherent but
    # unchanged 0 W battery state so the SolarFlow can begin charging.
    for _ in range(3):
        await controller.async_tick()

    coordinator.async_set_all_temporary_power_limits.assert_awaited_once_with(100)
    assert controller.status.predictive_strategy == "battery_capacity_release"


async def test_disabled_controller_keeps_grid_power_visible(hass) -> None:
    """Disabled is a deliberate state, not an unavailable local measurement."""
    hass.states.async_set("sensor.grid", "-177")
    controller = ZeroInjectionController(
        hass, fake_coordinator(), AcquisitionEngine(hass, "sensor.grid", False)
    )

    await controller.async_tick()

    assert controller.mode is ControllerMode.DISABLED
    assert controller.status.grid_power_w == -177
    assert controller.status.last_decision == "Controller disabled"


def test_snapshot_sync_diagnostics_explain_an_old_grid_measurement(hass) -> None:
    """A failed snapshot exposes its exact freshness reason for diagnostics."""
    controller = ZeroInjectionController(
        hass, fake_coordinator(), AcquisitionEngine(hass, "sensor.grid", False)
    )

    snapshot = controller._build_snapshot(
        7.3, datetime.now(UTC) - timedelta(seconds=11)
    )

    assert snapshot is None
    assert (
        controller.measurement_sync_diagnostics.reason
        == "Grid measurement is older than the allowed age"
    )
    assert controller.measurement_sync_diagnostics.tolerance_seconds == 25


async def test_trace_recorder_follows_mode_without_affecting_scheduler(hass) -> None:
    """RC3 tracing starts and stops passively; it sends no DTU request itself."""
    coordinator = fake_coordinator()
    controller = ZeroInjectionController(
        hass, coordinator, AcquisitionEngine(hass, "sensor.grid", False)
    )

    await controller.async_set_mode(ControllerMode.PRODUCTION.value)

    assert controller.trace_recorder.session_active
    assert controller.scheduler.state is SchedulerState.IDLE
    coordinator.async_set_all_temporary_power_limits.assert_not_awaited()

    await controller.async_set_mode(ControllerMode.SIMULATION.value)

    assert not controller.trace_recorder.session_active
    coordinator.async_set_all_temporary_power_limits.assert_not_awaited()


async def test_simulation_does_not_chain_virtual_commands(hass) -> None:
    """A new measurement recalculates but never treats a virtual limit as real."""
    hass.states.async_set("sensor.grid", "-220")
    coordinator = fake_coordinator()
    controller = ZeroInjectionController(
        hass, coordinator, AcquisitionEngine(hass, "sensor.grid", False)
    )
    await controller.async_set_mode(ControllerMode.SIMULATION.value)
    for _ in range(3):
        await controller.async_tick()
    assert controller.simulated_current_limit == 48
    assert coordinator.data.port_1_temporary_power_limit_percent == 50

    await controller.async_tick()
    assert controller.commands_simulated == 1
    assert controller.status.last_decision == "Simulation awaiting significant measurements"

    hass.states.async_set("sensor.grid", "-260")
    await controller.async_tick()
    assert controller.decisions_evaluated == 2
    assert controller.commands_simulated == 1
    assert controller.simulated_current_limit == 48
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


async def test_simulation_exposes_each_power_limit_role_separately(hass) -> None:
    """The real, simulated, recommended, and proposed limits are not conflated."""
    hass.states.async_set("sensor.grid", "-356.5")
    coordinator = fake_coordinator()
    controller = ZeroInjectionController(
        hass, coordinator, AcquisitionEngine(hass, "sensor.grid", False)
    )
    controller.set_target_grid_power(-50)
    await controller.async_set_mode(ControllerMode.SIMULATION.value)
    for _ in range(3):
        await controller.async_tick()

    assert controller.status.real_dtu_limit_percent == 50
    assert controller.last_simulated_limit == 20
    assert controller.simulated_current_limit == 20
    assert controller.status.calculated_limit_percent == 20
    assert controller.commands_simulated == 1
    assert controller.commands_sent == 0
    assert controller.scheduler_display_state == "Simulation awaiting measurements"


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


async def test_same_measurement_generation_is_evaluated_only_once(hass) -> None:
    """Repeated controller callbacks must not create a recorder-flooding decision."""
    hass.states.async_set("sensor.grid", "-220")
    controller = ZeroInjectionController(
        hass, fake_coordinator(), AcquisitionEngine(hass, "sensor.grid", False)
    )
    await controller.async_set_mode(ControllerMode.SIMULATION.value)
    for _ in range(100):
        await controller.async_tick()

    assert controller.decisions_evaluated == 1
    assert controller.commands_simulated == 1


async def test_simulation_wait_does_not_republish_or_create_a_decision(hass) -> None:
    """Unchanged measurements only keep the physical-change waiting state."""
    hass.states.async_set("sensor.grid", "-220")
    coordinator = fake_coordinator()
    listener = Mock()
    coordinator.async_update_listeners = listener
    controller = ZeroInjectionController(
        hass, coordinator, AcquisitionEngine(hass, "sensor.grid", False)
    )
    listener.reset_mock()
    await controller.async_set_mode(ControllerMode.SIMULATION.value)
    for _ in range(3):
        await controller.async_tick()

    decisions = controller.decisions_evaluated
    sequence = controller.last_decision_sequence
    decision_time = controller.status.last_decision_time
    updates = listener.call_count
    for _ in range(10):
        await controller.async_tick()

    assert controller.waiting_state == "Nouvelles mesures significatives attendues"
    assert controller.status.last_decision == "Simulation awaiting significant measurements"
    assert controller.decisions_evaluated == decisions
    assert controller.last_decision_sequence == sequence
    assert controller.status.last_decision_time == decision_time
    assert listener.call_count == updates
    coordinator.async_set_all_temporary_power_limits.assert_not_awaited()


async def test_only_significant_measurement_changes_create_a_new_decision(hass) -> None:
    """Noise is ignored; a meaningful physical variation enables one evaluation."""
    hass.states.async_set("sensor.grid", "-220")
    controller = ZeroInjectionController(
        hass, fake_coordinator(), AcquisitionEngine(hass, "sensor.grid", False)
    )
    await controller.async_set_mode(ControllerMode.SIMULATION.value)
    for _ in range(3):
        await controller.async_tick()
    assert controller.decisions_evaluated == 1

    hass.states.async_set("sensor.grid", "-225")
    await controller.async_tick()
    assert controller.decisions_evaluated == 1

    hass.states.async_set("sensor.grid", "-260")
    await controller.async_tick()
    assert controller.decisions_evaluated == 2
    assert controller.commands_simulated == 1


async def test_paused_scheduler_does_not_create_simulation_decisions(hass) -> None:
    """A paused scheduler cannot turn unchanged Simulation ticks into decisions."""
    hass.states.async_set("sensor.grid", "-220")
    controller = ZeroInjectionController(
        hass, fake_coordinator(), AcquisitionEngine(hass, "sensor.grid", False)
    )
    await controller.async_set_mode(ControllerMode.SIMULATION.value)
    for _ in range(3):
        await controller.async_tick()
    decisions = controller.decisions_evaluated
    sequence = controller.last_decision_sequence
    decision_time = controller.status.last_decision_time

    controller.scheduler.pause()
    for _ in range(100):
        await controller.async_tick()

    assert controller.decisions_evaluated == decisions
    assert controller.last_decision_sequence == sequence
    assert controller.status.last_decision_time == decision_time


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


async def test_disabled_controller_publishes_latest_coherent_modbus_limit(hass) -> None:
    """A prior command value can never override the three current DTU limits."""
    coordinator = fake_coordinator()
    controller = ZeroInjectionController(
        hass, coordinator, AcquisitionEngine(hass, "sensor.grid", False)
    )
    controller._status = replace(
        controller.status, current_limit_percent=31, real_dtu_limit_percent=31
    )
    await controller.async_set_mode(ControllerMode.DISABLED.value)
    await controller.async_tick()

    assert controller.status.real_dtu_limit_percent == 50
    assert controller.status.current_limit_percent == 50
    assert controller.scheduler.state is SchedulerState.IDLE


async def test_disabled_controller_updates_after_manual_dtu_limit_change(hass) -> None:
    """The following disabled tick always adopts the latest coherent snapshot."""
    coordinator = fake_coordinator()
    controller = ZeroInjectionController(
        hass, coordinator, AcquisitionEngine(hass, "sensor.grid", False)
    )
    await controller.async_set_mode(ControllerMode.DISABLED.value)
    await controller.async_tick()
    coordinator.data.port_1_temporary_power_limit_percent = 40
    coordinator.data.port_2_temporary_power_limit_percent = 40
    coordinator.data.port_3_temporary_power_limit_percent = 40
    await controller.async_tick()

    assert controller.status.real_dtu_limit_percent == 40
    assert controller.status.current_limit_percent == 40
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

    assert controller.simulated_current_limit == 48
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
    coordinator.async_set_all_temporary_power_limits.assert_awaited_once_with(48)
    assert controller.commands_succeeded == 1
    assert controller.scheduler.state is SchedulerState.WAITING


async def test_production_writes_while_manual_control_is_locked(hass) -> None:
    """The Manual slider never blocks the Production scheduler."""
    hass.states.async_set("sensor.grid", "-220")
    coordinator = fake_coordinator()
    assert coordinator.automatic_write_allowed is True
    controller = ZeroInjectionController(
        hass, coordinator, AcquisitionEngine(hass, "sensor.grid", False)
    )

    await controller.async_set_mode(ControllerMode.PRODUCTION.value)
    for _ in range(3):
        await controller.async_tick()

    coordinator.async_set_all_temporary_power_limits.assert_awaited_once_with(48)


async def test_simulation_never_writes(hass) -> None:
    """Simulation cannot turn a proposal into a DTU command."""
    hass.states.async_set("sensor.grid", "-220")
    coordinator = fake_coordinator()
    controller = ZeroInjectionController(
        hass, coordinator, AcquisitionEngine(hass, "sensor.grid", False)
    )

    await controller.async_set_mode(ControllerMode.SIMULATION.value)
    for _ in range(3):
        await controller.async_tick()

    coordinator.async_set_all_temporary_power_limits.assert_not_awaited()


async def test_production_exposes_theoretical_and_next_commanded_limits(hass) -> None:
    """The UI separates the raw calculation from the maximum-step command."""
    hass.states.async_set("sensor.grid", "-356.5")
    coordinator = fake_coordinator(automatic_writes_enabled=False)
    controller = ZeroInjectionController(
        hass, coordinator, AcquisitionEngine(hass, "sensor.grid", False)
    )
    controller.set_target_grid_power(-50)
    controller.set_maximum_step(2)
    await controller.async_set_mode(ControllerMode.PRODUCTION.value)
    for _ in range(3):
        await controller.async_tick()

    assert controller.status.real_dtu_limit_percent == 50
    assert controller.status.calculated_limit_percent == 20
    assert controller.status.commanded_limit_percent == 20


async def test_expired_stabilization_displays_monitoring(hass) -> None:
    """An elapsed delay is surveillance, not an indefinitely waiting scheduler."""
    hass.states.async_set("sensor.grid", "-220")
    controller = ZeroInjectionController(
        hass, fake_coordinator(), AcquisitionEngine(hass, "sensor.grid", False)
    )
    await controller.async_set_mode(ControllerMode.PRODUCTION.value)
    for _ in range(3):
        await controller.async_tick()
    controller.scheduler._next_allowed_at = datetime.now(UTC) - timedelta(seconds=1)
    await controller.async_tick()

    assert controller.scheduler_display_state == "Monitoring"
    assert controller.status.state == "Monitoring"
    assert controller.status.last_decision == "Monitoring"


async def test_stabilization_wait_creates_no_failed_or_counted_command(hass) -> None:
    """Repeated ticks during stabilization are a safety state, never failures."""
    hass.states.async_set("sensor.grid", "-220")
    coordinator = fake_coordinator()
    controller = ZeroInjectionController(
        hass, coordinator, AcquisitionEngine(hass, "sensor.grid", False)
    )
    await controller.async_set_mode(ControllerMode.PRODUCTION.value)
    for _ in range(3):
        await controller.async_tick()
    assert controller.commands_sent == 1

    hass.states.async_set("sensor.grid", "-260")
    for _ in range(10):
        await controller.async_tick()

    assert controller.scheduler.state is SchedulerState.WAITING
    assert controller.status.last_decision == "Waiting for stabilization"
    assert controller.commands_sent == 1
    assert controller.commands_failed == 0
    assert controller.last_command_sequence == 1
    assert controller.status.last_error is None


async def test_production_predictive_command_uses_confirmed_real_limit_and_never_simulate(hass) -> None:
    """A strong deviation reaches the bounded predictive target in one command."""
    hass.states.async_set("sensor.grid", "-1_000")
    coordinator = fake_coordinator()

    async def apply_limit(value: int) -> None:
        coordinator.data.port_1_temporary_power_limit_percent = value
        coordinator.data.port_2_temporary_power_limit_percent = value
        coordinator.data.port_3_temporary_power_limit_percent = value
        coordinator.data.last_success = datetime.now(UTC)
        coordinator.temporary_limits_timestamp = coordinator.data.last_success

    coordinator.async_set_all_temporary_power_limits = AsyncMock(side_effect=apply_limit)
    controller = ZeroInjectionController(
        hass, coordinator, AcquisitionEngine(hass, "sensor.grid", False)
    )
    await controller.async_set_mode(ControllerMode.PRODUCTION.value)
    for _ in range(3):
        await controller.async_tick()

    assert controller.status.real_dtu_limit_percent == 2
    assert controller.commands_sent == 1
    assert controller.commands_succeeded == 1
    assert controller.commands_failed == 0
    assert controller.commands_simulated == 0
    assert controller.last_simulated_limit is None
    assert controller.simulated_current_limit is None
    assert controller.last_command_sequence == 1
    assert coordinator.async_set_all_temporary_power_limits.await_args_list == [call(2)]


async def test_entering_production_clears_simulation_values(hass) -> None:
    """Simulation recommendations and counters cannot leak into Production UI."""
    hass.states.async_set("sensor.grid", "-220")
    controller = ZeroInjectionController(
        hass, fake_coordinator(), AcquisitionEngine(hass, "sensor.grid", False)
    )
    await controller.async_set_mode(ControllerMode.SIMULATION.value)
    for _ in range(3):
        await controller.async_tick()
    assert controller.commands_simulated == 1

    await controller.async_set_mode(ControllerMode.PRODUCTION.value)
    assert controller.commands_simulated == 0
    assert controller.simulated_current_limit is None
    assert controller.last_simulated_limit is None


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


async def test_valid_snapshot_clears_transient_measurement_error_without_command(hass) -> None:
    """A recovered snapshot restores monitoring even when no command is due."""
    coordinator = fake_coordinator(automatic_writes_enabled=False)
    controller = ZeroInjectionController(
        hass, coordinator, AcquisitionEngine(hass, "sensor.grid", False)
    )
    await controller.async_set_mode(ControllerMode.PRODUCTION.value)
    controller._valid_grid_measurements = 3
    controller._acquisition.read_grid_power = lambda: GridMeasurement(
        -40, None, datetime.now(UTC)
    )
    await controller.async_tick()

    controller._acquisition.read_grid_power = lambda: GridMeasurement(
        -40, None, datetime.now(UTC) - timedelta(seconds=11)
    )

    await controller.async_tick()

    assert controller.status.state == "Paused"
    assert controller.status.last_error == "Grid measurement is older than the allowed age"

    controller._acquisition.read_grid_power = lambda: GridMeasurement(
        -40, None, datetime.now(UTC)
    )
    await controller.async_tick()

    assert controller.status.state == "Monitoring"
    assert controller.status.last_decision == "Monitoring"
    assert controller.status.last_error is None
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
