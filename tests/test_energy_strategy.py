"""Deterministic Build006 energy-strategy regression tests."""

from datetime import UTC, datetime

from custom_components.openems_zero_injection.energy_policy import EnergyPolicyEngine
from custom_components.openems_zero_injection.energy_strategy import (
    EnergyStrategyEngine,
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
