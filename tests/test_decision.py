"""Tests for Build004's pure deterministic decision engine."""

import pytest

from custom_components.openems_zero_injection.decision import (
    DecisionReason,
    calculate_power_limit,
)


def decide(grid_power_w: float, current: int = 50, **overrides):
    params = {
        "grid_power_w": grid_power_w,
        "target_grid_power_w": -40,
        "deadband_w": 30,
        "current_limit_percent": current,
        "watts_per_percent": 30,
        "minimum_limit_percent": 2,
        "maximum_limit_percent": 100,
        "maximum_step_percent": 5,
    }
    params.update(overrides)
    return calculate_power_limit(**params)


def test_excess_export_reduces_limit_with_maximum_step() -> None:
    decision = decide(-220)
    assert decision.applied_limit_percent == 45
    assert decision.reason is DecisionReason.MAXIMUM_STEP_APPLIED


def test_grid_import_increases_limit_with_correct_sign() -> None:
    decision = decide(140)
    assert decision.applied_limit_percent == 55
    assert decision.reason is DecisionReason.MAXIMUM_STEP_APPLIED


def test_within_deadband_needs_no_command() -> None:
    decision = decide(-60)
    assert not decision.command_needed
    assert decision.reason is DecisionReason.WITHIN_DEADBAND


def test_limit_saturates_at_minimum_and_maximum() -> None:
    assert decide(-10_000, current=5).applied_limit_percent == 2
    assert decide(10_000, current=98).applied_limit_percent == 100


def test_small_correction_and_unchanged_limit_are_not_sent() -> None:
    decision = decide(-45, deadband_w=0)
    assert decision.applied_limit_percent == 50
    assert not decision.command_needed
    assert decision.reason is DecisionReason.LIMIT_UNCHANGED


def test_invalid_watts_per_percent_is_rejected() -> None:
    with pytest.raises(ValueError):
        decide(-200, watts_per_percent=0)
