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
    PREDICTIVE_LIMIT_APPLIED = "Predictive limit applied"
    FINE_CORRECTION_APPLIED = "Fine correction applied"


@dataclass(frozen=True, slots=True)
class ControlDecision:
    """The transparent result of one deterministic calculation."""

    grid_error_w: float
    current_limit_percent: int
    calculated_limit_percent: int
    applied_limit_percent: int
    reason: DecisionReason
    command_needed: bool


@dataclass(frozen=True, slots=True)
class PredictiveControlDecision:
    """A deterministic predictive decision with its transparent inputs."""

    grid_error_w: float
    estimated_load_w: float
    calculated_limit_percent: int
    applied_limit_percent: int
    reason: DecisionReason
    strategy: str
    command_needed: bool

    @property
    def predictive_limit_percent(self) -> int:
        """Return the direct predicted limit under its explicit diagnostic name."""
        return self.calculated_limit_percent


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


def calculate_predictive_power_limit(
    *,
    grid_power_w: float,
    pv_power_w: float,
    target_grid_power_w: float,
    deadband_w: float,
    current_limit_percent: int,
    installed_nominal_power_w: float,
    predictive_error_threshold_w: float,
    fine_correction_step_percent: int,
    minimum_limit_percent: int,
    maximum_limit_percent: int,
) -> PredictiveControlDecision:
    """Choose a direct predictive target or a bounded fine correction.

    The calculation has no side effects.  A direct limit is used only for a
    significant grid error; near the target, the existing correction law is
    deliberately bounded to a small final step.
    """
    if installed_nominal_power_w <= 0:
        raise ValueError("installed_nominal_power_w must be positive")
    if deadband_w < 0 or predictive_error_threshold_w <= 0:
        raise ValueError("invalid predictive configuration")
    if fine_correction_step_percent < 1:
        raise ValueError("fine_correction_step_percent must be positive")

    error = grid_power_w - target_grid_power_w
    estimated_load = pv_power_w + grid_power_w
    predictive_limit = _clamp(
        _round_away_from_zero(
            (estimated_load - target_grid_power_w)
            / installed_nominal_power_w
            * 100
        ),
        minimum_limit_percent,
        maximum_limit_percent,
    )
    if abs(error) <= deadband_w:
        return PredictiveControlDecision(
            error,
            estimated_load,
            predictive_limit,
            current_limit_percent,
            DecisionReason.WITHIN_DEADBAND,
            "within_deadband",
            False,
        )
    if abs(error) >= predictive_error_threshold_w:
        return PredictiveControlDecision(
            error,
            estimated_load,
            predictive_limit,
            predictive_limit,
            DecisionReason.PREDICTIVE_LIMIT_APPLIED,
            "predictive",
            predictive_limit != current_limit_percent,
        )

    fine = calculate_power_limit(
        grid_power_w=grid_power_w,
        target_grid_power_w=target_grid_power_w,
        deadband_w=deadband_w,
        current_limit_percent=current_limit_percent,
        watts_per_percent=installed_nominal_power_w / 100,
        minimum_limit_percent=minimum_limit_percent,
        maximum_limit_percent=maximum_limit_percent,
        maximum_step_percent=fine_correction_step_percent,
    )
    return PredictiveControlDecision(
        error,
        estimated_load,
        predictive_limit,
        fine.applied_limit_percent,
        (
            DecisionReason.FINE_CORRECTION_APPLIED
            if fine.command_needed
            else fine.reason
        ),
        "fine_correction",
        fine.command_needed,
    )


def _round_away_from_zero(value: float) -> int:
    return int(value + 0.5) if value >= 0 else int(value - 0.5)


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))
