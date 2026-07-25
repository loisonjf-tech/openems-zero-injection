"""Deterministic Build006 energy-strategy regression tests."""

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
