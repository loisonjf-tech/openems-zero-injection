"""Build004 RC2 passive architecture-contract tests."""

from datetime import UTC, datetime

from custom_components.openems_zero_injection.calibration import (
    CalibrationConfidence,
    CalibrationManager,
    CalibrationSample,
)
from custom_components.openems_zero_injection.context import ContextAnalyzer, ContextKind
from custom_components.openems_zero_injection.energy_policy import EnergyPolicyEngine


def test_context_analyzer_is_explicitly_passive_in_rc2() -> None:
    result = ContextAnalyzer().classify()
    assert result.kind is ContextKind.UNKNOWN
    assert result.confidence == 0


def test_calibration_manager_observation_has_no_control_effect() -> None:
    manager = CalibrationManager()
    manager.observe(
        CalibrationSample(datetime.now(UTC), 12, 900, -20, 1)
    )
    assert manager.profile.confidence is CalibrationConfidence.NONE
    assert manager.profile.accepted_samples == 0


def test_zero_injection_policy_preserves_the_configured_target() -> None:
    decision = EnergyPolicyEngine().decide(-40)
    assert decision.target_grid_power_w == -40
    assert decision.policy_id == "zero_injection"
    assert not decision.fallback_used
