"""Deterministic Build006 energy-strategy regression tests."""

from dataclasses import replace
from datetime import UTC, datetime

from custom_components.openems_zero_injection.battery import (
    BatteryHealth,
    BatteryResource,
)
from custom_components.openems_zero_injection.energy_policy import EnergyPolicyEngine
from custom_components.openems_zero_injection.energy_strategy import (
    BatteryPriorityContext,
    BatteryPriorityReasonCode,
    BatteryPriorityStrategy,
    EnergyStrategyEngine,
    EnergyStrategyInput,
    EnergyStrategyReasonCode,
    ZeroInjectionStrategy,
)


def test_zero_injection_strategy_preserves_the_pre_build006_output() -> None:
    """The encapsulated strategy must be indistinguishable to the controller."""
    timestamp = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
    target = -40.0

    legacy = EnergyPolicyEngine().decide(
        target,
        input_snapshot_id="snapshot-42",
        decision_timestamp=timestamp,
    )
    encapsulated = EnergyStrategyEngine(ZeroInjectionStrategy()).decide(
        target,
        input_snapshot_id="snapshot-42",
        decision_timestamp=timestamp,
    )

    assert encapsulated == legacy
    assert encapsulated.target_grid_power_w == target
    assert encapsulated.policy_id == "zero_injection"
    assert encapsulated.reason == "Configured zero-injection target"
    assert (
        encapsulated.reason_code
        is EnergyStrategyReasonCode.CONFIGURED_ZERO_INJECTION_TARGET
    )
    assert encapsulated.confidence == 1.0
    assert not encapsulated.fallback_used
    assert encapsulated.decision_timestamp == timestamp
    assert encapsulated.input_snapshot_id == "snapshot-42"


def test_default_engine_keeps_the_established_controller_call_shape() -> None:
    """Existing ``decide(float)`` users remain fully compatible."""
    decision = EnergyStrategyEngine().decide(-40)

    assert decision.target_grid_power_w == -40
    assert decision.policy_id == "zero_injection"
    assert decision.reason == "Configured zero-injection target"


def _healthy_battery(*, remaining_charge_power_w: float | None) -> BatteryResource:
    return BatteryResource(
        resource_id="battery-1",
        name="Test battery",
        adapter_id="test",
        adapter_version="test",
        available=True,
        health=BatteryHealth.HEALTHY,
        last_updated=datetime(2026, 7, 25, tzinfo=UTC),
        data_age_seconds=1,
        charge_power_w=0,
        discharge_power_w=0,
        remaining_charge_power_w=remaining_charge_power_w,
    )


def test_battery_priority_candidate_is_bounded_to_25_w() -> None:
    """A healthy complete battery only produces a passive 25 W candidate."""
    strategy_input = EnergyStrategyInput(
        -40, "snapshot-1", datetime(2026, 7, 25, tzinfo=UTC)
    )
    comparison = BatteryPriorityStrategy().compare(
        strategy_input,
        BatteryPriorityContext(
            (_healthy_battery(remaining_charge_power_w=800),), 800, "complete"
        ),
    )

    assert comparison.effective_target_grid_power_w == -40
    assert comparison.candidate_target_grid_power_w == -65
    assert comparison.target_delta_w == -25
    assert comparison.candidate_expected_storage_gain_w == 25
    assert (
        comparison.reason_code
        is BatteryPriorityReasonCode.BATTERY_PRIORITY_SIMULATION
    )
    assert not comparison.fallback_used


def test_battery_priority_unknown_capacity_is_exact_zero_injection_fallback() -> None:
    """No capacity estimate can ever change the historical target."""
    strategy_input = EnergyStrategyInput(
        -40, "snapshot-2", datetime(2026, 7, 25, tzinfo=UTC)
    )
    comparison = BatteryPriorityStrategy().compare(
        strategy_input,
        BatteryPriorityContext(
            (_healthy_battery(remaining_charge_power_w=None),), None, "complete"
        ),
    )

    assert comparison.effective_target_grid_power_w == -40
    assert comparison.candidate_target_grid_power_w == -40
    assert comparison.target_delta_w == 0
    assert comparison.candidate_expected_storage_gain_w == 0
    assert comparison.reason_code is BatteryPriorityReasonCode.BATTERY_CAPACITY_UNKNOWN
    assert comparison.fallback_used


def test_battery_priority_stale_or_partial_data_falls_back_exactly() -> None:
    """A healthy-looking value cannot bypass freshness or aggregate coverage."""
    strategy_input = EnergyStrategyInput(
        -40, "snapshot-3", datetime(2026, 7, 25, tzinfo=UTC)
    )
    stale = BatteryResource(
        resource_id="battery-1",
        name="Test battery",
        adapter_id="test",
        adapter_version="test",
        available=True,
        health=BatteryHealth.STALE,
        last_updated=datetime(2026, 7, 25, tzinfo=UTC),
        data_age_seconds=121,
        charge_power_w=0,
        remaining_charge_power_w=500,
    )
    stale_comparison = BatteryPriorityStrategy().compare(
        strategy_input, BatteryPriorityContext((stale,), 500, "complete")
    )
    partial_comparison = BatteryPriorityStrategy().compare(
        strategy_input,
        BatteryPriorityContext(
            (_healthy_battery(remaining_charge_power_w=500),), 500, "partial"
        ),
    )

    assert stale_comparison.candidate_target_grid_power_w == -40
    assert stale_comparison.reason_code is BatteryPriorityReasonCode.BATTERY_DATA_STALE
    assert partial_comparison.candidate_target_grid_power_w == -40
    assert (
        partial_comparison.reason_code
        is BatteryPriorityReasonCode.BATTERY_CAPACITY_PARTIAL
    )


def test_production_path_keeps_zero_injection_without_a_comparison() -> None:
    """Build007 never activates Battery Priority by merely wiring a provider."""
    engine = EnergyStrategyEngine(
        battery_context_provider=lambda: BatteryPriorityContext(
            (_healthy_battery(remaining_charge_power_w=500),), 500, "complete"
        )
    )

    decision = engine.decide(-40, compare_battery_priority=False)

    assert decision.target_grid_power_w == -40
    assert decision.policy_id == "zero_injection"
    assert decision.comparison is None


def _observed_context(
    *,
    charge_w: float,
    discharge_w: float = 0.0,
    second: int = 0,
) -> BatteryPriorityContext:
    battery = replace(
        _healthy_battery(remaining_charge_power_w=None),
        charge_power_w=charge_w,
        discharge_power_w=discharge_w,
        last_updated=datetime(2026, 7, 25, 0, 0, second, tzinfo=UTC),
    )
    return BatteryPriorityContext((battery,), None, "none")


def test_observed_conservative_activates_only_after_three_fresh_charges() -> None:
    """Production target changes only after the configured confirmation count."""
    sample = [0]
    engine = EnergyStrategyEngine(
        battery_context_provider=lambda: _observed_context(
            charge_w=999, second=sample[0]
        )
    )
    engine.configure_battery_priority(
        mode="observed_conservative",
        margin_w=25,
        charge_threshold_w=50,
        confirmation_samples=3,
    )

    first = engine.decide(-40, activate_battery_priority=True)
    sample[0] = 1
    second = engine.decide(-40, activate_battery_priority=True)
    sample[0] = 2
    active = engine.decide(-40, activate_battery_priority=True)

    assert first.target_grid_power_w == -40
    assert second.target_grid_power_w == -40
    assert active.target_grid_power_w == -65
    assert active.comparison is not None
    assert active.comparison.applied_margin_w == 25
    assert active.comparison.consecutive_charge_samples == 3


def test_disabled_battery_priority_preserves_exact_production_zero_injection() -> None:
    """The opt-in default cannot add a policy target or comparison in Production."""
    engine = EnergyStrategyEngine(
        battery_context_provider=lambda: _observed_context(charge_w=999)
    )

    decision = engine.decide(-40, activate_battery_priority=True)

    assert decision.target_grid_power_w == -40
    assert decision.policy_id == "zero_injection"
    assert not decision.fallback_used
    assert decision.comparison is None


def test_repeated_same_battery_publication_is_not_three_fresh_samples() -> None:
    """Grid changes cannot turn one battery publication into three confirmations."""
    engine = EnergyStrategyEngine(
        battery_context_provider=lambda: _observed_context(charge_w=999, second=0)
    )
    engine.configure_battery_priority(
        mode="observed_conservative",
        margin_w=25,
        charge_threshold_w=50,
        confirmation_samples=3,
    )

    decisions = [engine.decide(-40, activate_battery_priority=True) for _ in range(3)]

    assert [decision.target_grid_power_w for decision in decisions] == [-40, -40, -40]
    assert engine.battery_priority_diagnostics["consecutive_charge_samples"] == 1


def test_observed_conservative_discharge_immediately_falls_back() -> None:
    """One fresh significant discharge invalidates a previously active charge."""
    sample = [0]
    context = _observed_context(charge_w=999, second=sample[0])
    engine = EnergyStrategyEngine(battery_context_provider=lambda: context)
    engine.configure_battery_priority(
        mode="observed_conservative",
        margin_w=25,
        charge_threshold_w=50,
        confirmation_samples=3,
    )
    for _ in range(3):
        decision = engine.decide(-40, activate_battery_priority=True)
        sample[0] += 1
        context = _observed_context(charge_w=999, second=sample[0])
    assert decision.target_grid_power_w == -65

    context = _observed_context(charge_w=0, discharge_w=700)
    fallback = engine.decide(-40, activate_battery_priority=True)

    assert fallback.target_grid_power_w == -40
    assert fallback.fallback_used
    assert fallback.comparison is not None
    assert fallback.comparison.reason_code is BatteryPriorityReasonCode.BATTERY_DISCHARGING
    assert engine.battery_priority_diagnostics["consecutive_charge_samples"] == 0


def test_observed_conservative_maintains_active_priority_at_44_w() -> None:
    """The 50 W threshold activates priority; it does not turn it off."""
    sample = [0]
    context = _observed_context(charge_w=60, second=sample[0])
    engine = EnergyStrategyEngine(battery_context_provider=lambda: context)
    engine.configure_battery_priority(
        mode="observed_conservative",
        margin_w=25,
        charge_threshold_w=50,
        confirmation_samples=3,
    )

    for _ in range(3):
        decision = engine.decide(-40, activate_battery_priority=True)
        sample[0] += 1
        context = _observed_context(charge_w=60, second=sample[0])
    assert decision.target_grid_power_w == -65

    context = _observed_context(charge_w=44, second=sample[0])
    maintained = engine.decide(-40, activate_battery_priority=True)

    assert maintained.target_grid_power_w == -65
    assert maintained.comparison is not None
    assert not maintained.comparison.fallback_used
    assert maintained.comparison.observed_charge_power_w == 44


def test_observed_conservative_requires_three_low_samples_to_fallback() -> None:
    """Three distinct fresh readings below 5 W are required to deactivate."""
    sample = [0]
    context = _observed_context(charge_w=60, second=sample[0])
    engine = EnergyStrategyEngine(battery_context_provider=lambda: context)
    engine.configure_battery_priority(
        mode="observed_conservative",
        margin_w=25,
        charge_threshold_w=50,
        confirmation_samples=3,
    )

    for _ in range(3):
        engine.decide(-40, activate_battery_priority=True)
        sample[0] += 1
        context = _observed_context(charge_w=60, second=sample[0])

    context = _observed_context(charge_w=4, second=sample[0])
    first_low = engine.decide(-40, activate_battery_priority=True)
    repeated_low = engine.decide(-40, activate_battery_priority=True)
    assert engine.battery_priority_diagnostics["consecutive_low_charge_samples"] == 1

    sample[0] += 1
    context = _observed_context(charge_w=4, second=sample[0])
    second_low = engine.decide(-40, activate_battery_priority=True)
    sample[0] += 1
    context = _observed_context(charge_w=4, second=sample[0])
    third_low = engine.decide(-40, activate_battery_priority=True)

    assert [
        first_low.target_grid_power_w,
        repeated_low.target_grid_power_w,
        second_low.target_grid_power_w,
        third_low.target_grid_power_w,
    ] == [-65, -65, -65, -40]
    assert third_low.comparison is not None
    assert third_low.comparison.reason_code is BatteryPriorityReasonCode.BATTERY_IDLE
    assert engine.battery_priority_diagnostics["consecutive_low_charge_samples"] == 0


def test_observed_conservative_stale_data_falls_back_without_target_change() -> None:
    """A stale battery resource can never preserve a prior battery margin."""
    stale = BatteryResource(
        resource_id="battery-1",
        name="Test battery",
        adapter_id="test",
        adapter_version="test",
        available=True,
        health=BatteryHealth.STALE,
        last_updated=datetime(2026, 7, 25, tzinfo=UTC),
        data_age_seconds=121,
        charge_power_w=999,
        discharge_power_w=0,
    )
    engine = EnergyStrategyEngine(
        battery_context_provider=lambda: BatteryPriorityContext((stale,), None, "none")
    )
    engine.configure_battery_priority(
        mode="observed_conservative",
        margin_w=25,
        charge_threshold_w=50,
        confirmation_samples=3,
    )

    decision = engine.decide(-40, activate_battery_priority=True)

    assert decision.target_grid_power_w == -40
    assert decision.fallback_used
    assert decision.comparison is not None
    assert decision.comparison.reason_code is BatteryPriorityReasonCode.BATTERY_DATA_STALE
