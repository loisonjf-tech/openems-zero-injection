"""Pure deterministic zero-injection decision logic for Build004."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DecisionReason(StrEnum):
    """Reasons recorded in the bounded controller decision history."""

    WITHIN_DEADBAND = "Within deadband"
    EXCESS_EXPORT = "Excess export"
    GRID_IMPORT = "Grid import"
    LIMIT_UNCHANGED = "Limit unchanged"
    MAXIMUM_STEP_APPLIED = "Maximum step applied"


@dataclass(frozen=True, slots=True)
class ControlDecision:
    """The transparent result of one deterministic calculation."""

    grid_error_w: float
    current_limit_percent: int
    calculated_limit_percent: int
    applied_limit_percent: int
    reason: DecisionReason
    command_needed: bool


def calculate_power_limit(
    *,
    grid_power_w: float,
    target_grid_power_w: float,
    deadband_w: float,
    current_limit_percent: int,
    watts_per_percent: float,
    minimum_limit_percent: int,
    maximum_limit_percent: int,
    maximum_step_percent: int,
) -> ControlDecision:
    """Calculate one bounded limit change without side effects.

    Positive grid power means import. Therefore a positive error increases the
    DTU limit; excessive export produces a negative error and lowers it.
    Python's deterministic round-to-nearest-even is deliberately avoided:
    half values are rounded away from zero.
    """
    if watts_per_percent <= 0:
        raise ValueError("watts_per_percent must be positive")
    if deadband_w < 0 or maximum_step_percent < 1:
        raise ValueError("invalid controller configuration")

    error = grid_power_w - target_grid_power_w
    if abs(error) <= deadband_w:
        return ControlDecision(
            error,
            current_limit_percent,
            current_limit_percent,
            current_limit_percent,
            DecisionReason.WITHIN_DEADBAND,
            False,
        )

    correction = _round_away_from_zero(error / watts_per_percent)
    calculated = _clamp(
        current_limit_percent + correction,
        minimum_limit_percent,
        maximum_limit_percent,
    )
    step = calculated - current_limit_percent
    applied = _clamp(
        current_limit_percent + _clamp(step, -maximum_step_percent, maximum_step_percent),
        minimum_limit_percent,
        maximum_limit_percent,
    )
    if applied == current_limit_percent:
        reason = DecisionReason.LIMIT_UNCHANGED
    elif abs(step) > maximum_step_percent:
        reason = DecisionReason.MAXIMUM_STEP_APPLIED
    elif error < 0:
        reason = DecisionReason.EXCESS_EXPORT
    else:
        reason = DecisionReason.GRID_IMPORT
    return ControlDecision(
        error,
        current_limit_percent,
        calculated,
        applied,
        reason,
        applied != current_limit_percent,
    )


def _round_away_from_zero(value: float) -> int:
    return int(value + 0.5) if value >= 0 else int(value - 0.5)


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))
