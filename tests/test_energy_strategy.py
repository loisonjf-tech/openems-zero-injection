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
    DtuControlDirective,
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


def test_capacity_release_battery_transition_requests_new_decision() -> None:
    """A discharge transition must not wait for a grid-power change."""
    timestamp = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
    battery = _healthy_battery(remaining_charge_power_w=600)
    battery = replace(
        battery,
        soc_percent=60,
        max_charge_power_w=1000,
        charge_power_w=400,
        source_freshness={
            "directional_power_w": "fresh",
            "soc_percent": "fresh",
            "max_charge_power_w": "fresh",
        },
        source_timestamps={"directional_power_w": timestamp},
    )
    context = [BatteryPriorityContext((battery,), 600, "complete")]
    engine = EnergyStrategyEngine(battery_context_provider=lambda: context[0])
    engine.configure_battery_priority(
        mode="capacity_release", margin_w=25, charge_threshold_w=50, confirmation_samples=3
    )
    engine.decide(-40, activate_battery_priority=True)
    assert not engine.battery_priority_input_changed()

    battery = replace(
        battery,
        discharge_power_w=100,
        source_timestamps={"directional_power_w": timestamp.replace(second=1)},
    )
    context[0] = BatteryPriorityContext((battery,), 600, "complete")
    assert engine.battery_priority_input_changed()


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


def _capacity_context(
    *,
    charge_w: float,
    discharge_w: float = 0.0,
    soc_percent: float = 60.0,
    second: int = 0,
    max_charge_w: float | None = 1000.0,
    freshness: str = "fresh",
) -> BatteryPriorityContext:
    battery = replace(
        _healthy_battery(remaining_charge_power_w=None),
        soc_percent=soc_percent,
        charge_power_w=charge_w,
        discharge_power_w=discharge_w,
        max_charge_power_w=max_charge_w,
        remaining_charge_power_w=(
            max(max_charge_w - charge_w, 0) if max_charge_w is not None else None
        ),
        last_updated=datetime(2026, 7, 25, 0, 0, second, tzinfo=UTC),
        source_freshness={
            "soc_percent": freshness,
            "max_charge_power_w": freshness,
        },
    )
    return BatteryPriorityContext((battery,), None, "none")


def _capacity_engine(context_holder: list[BatteryPriorityContext]) -> EnergyStrategyEngine:
    engine = EnergyStrategyEngine(battery_context_provider=lambda: context_holder[0])
    engine.configure_battery_priority(
        mode="capacity_release",
        margin_w=25,
        charge_threshold_w=50,
        confirmation_samples=3,
    )
    return engine


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


def test_capacity_release_releases_from_one_coherent_zero_w_snapshot() -> None:
    """An unchanged 0 W SolarFlow state must still allow charging to start."""
    contexts = [_capacity_context(charge_w=0, soc_percent=38, second=0)]
    engine = _capacity_engine(contexts)

    first = engine.decide(-40, activate_battery_priority=True)
    # No new directional publication: the same coherent zero-W snapshot must
    # remain released rather than waiting indefinitely for three state changes.
    repeated = engine.decide(-40, activate_battery_priority=True)

    assert first.dtu_control_directive is DtuControlDirective.RELEASE_DTU_TO_MAXIMUM
    assert repeated.dtu_control_directive is DtuControlDirective.RELEASE_DTU_TO_MAXIMUM
    assert first.requested_dtu_limit_percent == 100
    assert first.comparison is not None
    assert first.comparison.remaining_charge_power_w == 1000


def test_capacity_release_keeps_release_across_a_soc_refresh() -> None:
    """A SOC refresh cannot revoke an otherwise coherent released capacity."""
    contexts = [_capacity_context(charge_w=400, second=0)]
    engine = _capacity_engine(contexts)

    first = engine.decide(-40, activate_battery_priority=True)
    resource = replace(contexts[0].resources[0], soc_percent=61)
    contexts[0] = BatteryPriorityContext((resource,), None, "none")
    decision = engine.decide(-40, activate_battery_priority=True)

    assert first.dtu_control_directive is DtuControlDirective.RELEASE_DTU_TO_MAXIMUM
    assert decision.dtu_control_directive is DtuControlDirective.RELEASE_DTU_TO_MAXIMUM
    assert engine.battery_priority_diagnostics["consecutive_release_samples"] == 0


def test_capacity_release_holds_between_900_and_950_w() -> None:
    """The hysteresis band never flips an already released DTU by itself."""
    sample = [0]
    contexts = [_capacity_context(charge_w=400, second=sample[0])]
    engine = _capacity_engine(contexts)
    for _ in range(3):
        engine.decide(-40, activate_battery_priority=True)
        sample[0] += 1
        contexts[0] = _capacity_context(charge_w=400, second=sample[0])

    decisions = []
    for _ in range(3):
        contexts[0] = _capacity_context(charge_w=920, second=sample[0])
        decisions.append(engine.decide(-40, activate_battery_priority=True))
        sample[0] += 1

    assert all(
        decision.dtu_control_directive is DtuControlDirective.RELEASE_DTU_TO_MAXIMUM
        for decision in decisions
    )


def test_capacity_release_changes_to_normal_only_after_three_saturated_samples() -> None:
    """One 950 W measurement cannot stop a previously released DTU."""
    sample = [0]
    contexts = [_capacity_context(charge_w=400, second=sample[0])]
    engine = _capacity_engine(contexts)
    for _ in range(3):
        engine.decide(-40, activate_battery_priority=True)
        sample[0] += 1
        contexts[0] = _capacity_context(charge_w=400, second=sample[0])

    outcomes = []
    for _ in range(3):
        contexts[0] = _capacity_context(charge_w=950, second=sample[0])
        outcomes.append(engine.decide(-40, activate_battery_priority=True))
        sample[0] += 1

    assert [outcome.dtu_control_directive for outcome in outcomes] == [
        DtuControlDirective.RELEASE_DTU_TO_MAXIMUM,
        DtuControlDirective.RELEASE_DTU_TO_MAXIMUM,
        DtuControlDirective.NORMAL_REGULATION,
    ]
    assert outcomes[-1].comparison is not None
    assert outcomes[-1].comparison.reason_code is BatteryPriorityReasonCode.CAPACITY_RELEASE_SATURATED


def test_capacity_release_allows_a_discharging_battery_when_capacity_is_available() -> None:
    """A fresh discharge is intentionally not a release-blocking condition."""
    sample = [0]
    contexts = [_capacity_context(charge_w=0, discharge_w=300, second=sample[0])]
    engine = _capacity_engine(contexts)
    for _ in range(3):
        decision = engine.decide(-40, activate_battery_priority=True)
        sample[0] += 1
        contexts[0] = _capacity_context(
            charge_w=0, discharge_w=300, second=sample[0]
        )

    assert decision.dtu_control_directive is DtuControlDirective.RELEASE_DTU_TO_MAXIMUM
    assert (
        decision.comparison.reason_code
        is BatteryPriorityReasonCode.CAPACITY_RELEASE_DISCHARGING
    )


def test_capacity_release_reason_tracks_stale_discharge_then_charge_sequence() -> None:
    """A discharge reason cannot survive the next signed charging snapshot."""
    stale = _capacity_context(charge_w=0, second=0).resources[0]
    stale = replace(
        stale,
        health=BatteryHealth.STALE,
        directional_power_w=0,
        source_freshness={
            "soc_percent": "fresh",
            "directional_power_w": "stale",
            "max_charge_power_w": "cached",
        },
    )
    contexts = [BatteryPriorityContext((stale,), None, "none")]
    engine = _capacity_engine(contexts)

    t0 = engine.decide(-40, activate_battery_priority=True)

    discharging = replace(
        _capacity_context(charge_w=0, discharge_w=300, second=1).resources[0],
        directional_power_w=300,
    )
    contexts[0] = BatteryPriorityContext((discharging,), None, "none")
    t1 = engine.decide(-40, activate_battery_priority=True)

    charging = replace(
        _capacity_context(charge_w=100, second=2).resources[0],
        directional_power_w=-100,
    )
    contexts[0] = BatteryPriorityContext((charging,), None, "none")
    t2 = engine.decide(-40, activate_battery_priority=True)
    t3 = engine.decide(-40, activate_battery_priority=True)

    assert t0.comparison is not None
    assert t0.comparison.reason_code is BatteryPriorityReasonCode.BATTERY_DATA_STALE
    assert t1.comparison is not None
    assert (
        t1.comparison.reason_code
        is BatteryPriorityReasonCode.CAPACITY_RELEASE_DISCHARGING
    )
    for decision in (t2, t3):
        assert decision.comparison is not None
        assert (
            decision.comparison.reason_code
            is BatteryPriorityReasonCode.CAPACITY_RELEASE_ACTIVE
        )
        assert decision.dtu_control_directive is DtuControlDirective.RELEASE_DTU_TO_MAXIMUM


def test_capacity_release_does_not_prioritize_discharge_at_or_below_five_w() -> None:
    """The 5 W boundary filters noise; it is not a special release priority."""
    contexts = [_capacity_context(charge_w=950, discharge_w=5, soc_percent=60)]
    engine = _capacity_engine(contexts)

    decision = engine.decide(-40, activate_battery_priority=True)

    assert decision.dtu_control_directive is DtuControlDirective.NORMAL_REGULATION
    assert decision.comparison is not None
    assert decision.comparison.reason_code is BatteryPriorityReasonCode.CAPACITY_RELEASE_HOLD_NORMAL


def test_capacity_release_full_battery_cannot_be_overridden_by_discharge() -> None:
    """A full battery must resume Zero Injection despite a discharge sample."""
    contexts = [_capacity_context(charge_w=0, discharge_w=6, soc_percent=100)]
    engine = _capacity_engine(contexts)

    decision = engine.decide(-40, activate_battery_priority=True)

    assert decision.dtu_control_directive is DtuControlDirective.NORMAL_REGULATION
    assert decision.comparison is not None
    assert decision.comparison.reason_code is BatteryPriorityReasonCode.CAPACITY_RELEASE_FULL


def test_capacity_release_falls_back_when_soc_or_capacity_is_not_fresh() -> None:
    """A restored or stale capacity can never keep the DTU released."""
    contexts = [_capacity_context(charge_w=0, freshness="stale")]
    engine = _capacity_engine(contexts)

    decision = engine.decide(-40, activate_battery_priority=True)

    assert decision.dtu_control_directive is DtuControlDirective.NORMAL_REGULATION
    assert decision.comparison is not None
    assert decision.comparison.reason_code is BatteryPriorityReasonCode.CAPACITY_RELEASE_SOC_STALE


def test_capacity_release_accepts_a_verified_cached_charge_capacity() -> None:
    """A static, validated SolarFlow capacity remains usable after its first read."""
    context = _capacity_context(charge_w=724, soc_percent=43)
    battery = replace(
        context.resources[0],
        source_freshness={
            "soc_percent": "fresh",
            "max_charge_power_w": "cached",
        },
    )
    contexts = [BatteryPriorityContext((battery,), None, "none")]
    engine = _capacity_engine(contexts)

    decision = engine.decide(-40, activate_battery_priority=True)

    assert decision.dtu_control_directive is DtuControlDirective.RELEASE_DTU_TO_MAXIMUM
    assert decision.requested_dtu_limit_percent == 100


def test_capacity_release_treats_soc_100_as_full() -> None:
    """This first increment deliberately uses no speculative 99% full rule."""
    contexts = [_capacity_context(charge_w=0, soc_percent=100)]
    engine = _capacity_engine(contexts)

    decision = engine.decide(-40, activate_battery_priority=True)

    assert decision.dtu_control_directive is DtuControlDirective.NORMAL_REGULATION
    assert decision.comparison is not None
    assert decision.comparison.reason_code is BatteryPriorityReasonCode.CAPACITY_RELEASE_FULL


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
